
# app.py - v4.7.4 - Compact sidebar + copyable discovery error + Discovery diagnostic
# Root: app.py
# CHANGELOG v4.7.1 vs v4.7:
# - Seen_posts.txt uploader moved back to TOP of sidebar (was pushed below quota panel, looked gone)
# - Effectiveness.txt uploader restored (was missing in v4.7)
# - Quota panel moved BELOW Seen / Effectiveness, so it never hides them
# - Discovery check: accepts 4.4/4.5/4.6/4.7, shows REAL import error in sidebar if import fails (not just OLD)
# - If discovery import fails, uses in-app fallback discovery so app still works
import os, json, re

import streamlit as st

from config import GEMINI_MODEL, MODEL_QUOTAS, QUOTA_ASSESS_NEEDS, QUOTA_DRAFT_NEEDS, QUOTA_TEST_NEEDS, QUOTA_FALLBACK_MODEL

# --- Quota ---
try:
    from quota import get_usage, can_afford, quota_level, quota_message, set_manual_used
except Exception:
    def get_usage(m): return {"model": m, "label": m, "used": 0, "limit": 20, "remaining": 20, "pct": 0, "reset_label": "midnight Pacific"}
    def can_afford(m, n=1): return True
    def quota_level(m, n=1): return "ok"
    def quota_message(m, n=1): return ""
    def set_manual_used(m, n): return get_usage(m)

try:
    from gemini_client import GeminiClient, GeminiQuotaExceeded, GeminiTransientError, GeminiInitError
except Exception as e:
    GeminiClient = None
    class GeminiQuotaExceeded(Exception): pass
    class GeminiTransientError(Exception): pass
    class GeminiInitError(Exception): pass
    _GEMINI_IMPORT_ERR = e
else:
    _GEMINI_IMPORT_ERR = None

# --- Discovery with diagnostic ---
_DISCOVERY_ERR = None
_DISCOVERY_ERR_FULL = ""
try:
    from discovery import run_discovery_with_stats
    import discovery as _disc_mod
    DISCOVERY_VERSION = getattr(_disc_mod, "__VERSION__", "OLD")
    _has_norm = hasattr(_disc_mod, "_normalize_post")
    # Accept 4.4, 4.5, 4.6, 4.7 - all are good, do NOT call 4.5 OLD
    DISCOVERY_IS_NEW = _has_norm and str(DISCOVERY_VERSION) in ("4.4", "4.5", "4.6", "4.7", "4.7.3") or str(DISCOVERY_VERSION).startswith("4.")
    if not DISCOVERY_IS_NEW and str(DISCOVERY_VERSION) not in ("OLD",):
        # Version exists but not in list - still treat as OK if _normalize_post exists
        DISCOVERY_IS_NEW = _has_norm
except Exception as e:
    import traceback
    run_discovery_with_stats = None
    DISCOVERY_VERSION = "OLD - import failed"
    DISCOVERY_IS_NEW = False
    _DISCOVERY_ERR = str(e)
    _DISCOVERY_ERR_FULL = traceback.format_exc()[:2000]

try:
    from drafting.formatting import format_draft
except Exception:
    def format_draft(x): return x or ""
try:
    from scoring.selection import heuristic_assess, select_for_gemini, template_draft
except Exception:
    def heuristic_assess(p):
        return {"decision": "D_SKIP", "promo": 0, "opp": 0.0, "theme": "other", "reason": "Heuristic unavailable."}
    def select_for_gemini(posts): return (posts or [])[:12]
    def template_draft(p, a=None): return format_draft("Template draft unavailable.")

for k, v in [("discovered", []), ("assessed", []), ("last_run_log", []), ("quota_hit", False)]:
    if k not in st.session_state:
        st.session_state[k] = v

def _log(msg):
    st.session_state.last_run_log.append(str(msg))

def _parse_seen(text):
    seen = set()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line: continue
        m = re.search(r"https?://[^\s|]+", line)
        if m: seen.add(m.group(0).strip().rstrip(","))
        elif "|" in line:
            # title | url - but no URL found, keep title part as seen key
            seen.add(line.split("|")[0].strip())
        else: seen.add(line)
    return seen

def _fb_run_discovery(seen_urls=None):
    """Fallback if discovery/__init__.py import fails - same normalisation/pruning as v4.4"""
    seen_urls = seen_urls or set()
    from config import SEARCH_TERMS, MAX_RESULTS_PER_SOURCE
    all_posts = []
    per_source = {}
    try:
        from discovery.web_search import search_web
        for q in SEARCH_TERMS:
            try:
                res = search_web(q, MAX_RESULTS_PER_SOURCE)
                if isinstance(res, list): all_posts.extend(res)
            except Exception: pass
        per_source["web_search"] = len(all_posts)
    except Exception as e:
        per_source["web_search_error"] = str(e)[:100]
    try:
        from discovery.medium import fetch_medium
        try: m = fetch_medium()
        except TypeError: m = fetch_medium(None)
        if isinstance(m, list): all_posts.extend(m); per_source["medium"] = len(m)
    except Exception as e:
        per_source["medium_error"] = str(e)[:100]
    try:
        from discovery.youtube import fetch_youtube
        try: y = fetch_youtube()
        except TypeError: y = fetch_youtube(None)
        if isinstance(y, list): all_posts.extend(y); per_source["youtube"] = len(y)
    except Exception as e:
        per_source["youtube_error"] = str(e)[:100]
    # Normalise + dedupe + prune (simple version)
    norm = []
    for p in all_posts:
        if isinstance(p, dict):
            link = str(p.get("link") or p.get("url") or "").strip()
            title = str(p.get("title") or "").strip()
            if not title and not link: continue
            norm.append({"title": title, "link": link, "snippet": str(p.get("snippet") or p.get("summary") or "")[:800], "platform": str(p.get("platform") or "Web")})
        elif isinstance(p, str):
            norm.append({"title": p[:200], "link": "", "snippet": p[:800], "platform": "Web"})
    seen_filtered = 0; deduped = []
    seen_links = set()
    for p in norm:
        if p["link"] and p["link"] in seen_urls:
            seen_filtered += 1; continue
        if p["link"] and p["link"] in seen_links: continue
        if p["link"]: seen_links.add(p["link"])
        deduped.append(p)
    kept = deduped[:23]
    stats = {"raw": len(all_posts), "invalid_skipped": 0, "seen_filtered": seen_filtered, "deduped": len(deduped), "social": 0, "web_pruned": max(0, len(deduped)-len(kept)), "kept_for_assessment": len(kept), "fallback": True, "per_source": per_source}
    return kept, stats

# ================= SIDEBAR - COMPACT v4.7.4 =================
st.sidebar.title("Leadership AI Daily Digest")

# 1. SEEN - TOP, always visible, compact
st.sidebar.caption("Seen posts")
seen_file = st.sidebar.file_uploader("Upload seen_posts.txt", type=["txt"], key="seen_uploader_v472")
seen_urls = set()
if seen_file is not None:
    try:
        seen_urls = _parse_seen(seen_file.read().decode("utf-8", errors="ignore"))
        st.sidebar.success(f"Seen loaded: {len(seen_urls)}")
    except Exception as e:
        st.sidebar.error(f"Seen error: {e}")
else:
    st.sidebar.caption("Re-upload after every reboot.")

# 2. KEYS + DISCOVERY - one line each
st.sidebar.caption(f"Gemini: {'OK' if os.getenv('GEMINI_API_KEY') else 'MISSING'} | Grok: {'OK' if os.getenv('GROK_API_KEY') else 'MISSING'} | Model: {GEMINI_MODEL}")
st.sidebar.caption(f"Discovery: {DISCOVERY_VERSION}")
if not DISCOVERY_IS_NEW:
    if _DISCOVERY_ERR:
        st.sidebar.error("Discovery import failed - app uses fallback.")
        with st.sidebar.expander("Tap to see discovery error - copy it"):
            st.sidebar.code(_DISCOVERY_ERR_FULL[:2000])
            st.sidebar.caption("Copy the text above and paste it here. Also check GitHub > discovery folder has exactly: __init__.py, medium.py, web_search.py, youtube.py")
    else:
        st.sidebar.error(f"Discovery OLD ({DISCOVERY_VERSION}). Re-upload discovery/__init__.py to discovery/ folder.")

# 3. QUOTA - summary line + details in expander (so sidebar stays short)
u = get_usage(GEMINI_MODEL)
st.sidebar.caption(f"Quota {u['label']}: {u['used']}/{u['limit']} used, {u['remaining']} left")
# Reboot warning - local counter forgets on reboot, like seen_posts.txt
try:
    from quota import quota_reboot_warning
    _rw = quota_reboot_warning(GEMINI_MODEL)
    if _rw and u['used'] == 0:
        st.sidebar.caption("Reboot? If you used Gemini today BEFORE this reboot, enter that number in AI Studio sync below.")
except Exception:
    pass
st.sidebar.progress(min(1.0, u['used'] / u['limit']) if u['limit'] else 0)
lvl = quota_level(GEMINI_MODEL, QUOTA_ASSESS_NEEDS)
if lvl == "block":
    st.sidebar.error("Quota OUT - heuristic / template only.")
elif lvl == "warn":
    st.sidebar.warning(f"Need {QUOTA_ASSESS_NEEDS} for Assess, have {u['remaining']} left.")
else:
    st.sidebar.success(f"Safe to Assess - {u['remaining']} left.")
with st.sidebar.expander("Quota details + AI Studio sync"):
    st.sidebar.write(f"Resets: {u['reset_label']}")
    st.sidebar.write(f"Assess needs {QUOTA_ASSESS_NEEDS} | Draft {QUOTA_DRAFT_NEEDS} | Test {QUOTA_TEST_NEEDS}")
    st.sidebar.write(f"If you used Gemini in AI Studio outside app, enter that number:")
    manual = st.sidebar.number_input("Already used in AI Studio", min_value=0, max_value=1000, step=1, key="quota_manual_input_v472")
    if "quota_manual_applied_v472" not in st.session_state:
        st.session_state.quota_manual_applied_v472 = -1
    if manual != st.session_state.quota_manual_applied_v472:
        try:
            set_manual_used(GEMINI_MODEL, int(manual))
            st.session_state.quota_manual_applied_v472 = int(manual)
        except Exception:
            pass

with st.sidebar.expander("Effectiveness (optional)"):
    eff_file = st.sidebar.file_uploader("Upload effectiveness.txt", type=["txt"], key="eff_uploader_v472")
    if eff_file is not None:
        try:
            txt = eff_file.read().decode("utf-8", errors="ignore")
            st.sidebar.write(f"Loaded: {len([l for l in txt.splitlines() if l.strip()])} lines")
        except Exception as e:
            st.sidebar.error(f"Error: {e}")

# ================= MAIN =================
st.title("Leadership AI Daily Digest")
st.write("Step 1: Run Discovery (0 Gemini calls) -> Assess (max 12 Gemini calls, rest heuristic) -> Step 2: Review drafts.")
st.header("Step 1 - Discovery")
if st.button("Run Discovery", key="run_discovery_btn_v472"):
    # Use real discovery if available, else fallback
    if run_discovery_with_stats is not None:
        try:
            pruned, stats = run_discovery_with_stats(seen_urls=seen_urls)
            _log(f"Discovery: raw={stats.get('raw','?')} invalid_skipped={stats.get('invalid_skipped',0)} seen_filtered={stats.get('seen_filtered',0)} deduped={stats.get('deduped','?')} social={stats.get('social','?')} web_pruned={stats.get('web_pruned',0)} kept={stats.get('kept_for_assessment', len(pruned))} fallback={stats.get('fallback', False)}")
            st.session_state.discovered = pruned or []
            st.session_state.assessed = []
            st.success(f"Discovery returned {stats.get('raw','?')} raw posts before dedupe / pruned to {len(pruned)} for assessment. Seen filtered: {stats.get('seen_filtered',0)}. Invalid skipped: {stats.get('invalid_skipped',0)}. Web articles pruned: {stats.get('web_pruned',0)}. Social threads: {stats.get('social','?')}. Per-source: {stats.get('per_source', {})}")
        except Exception as e:
            st.warning(f"Real discovery failed ({e}) - using fallback discovery.")
            pruned, stats = _fb_run_discovery(seen_urls=seen_urls)
            st.session_state.discovered = pruned or []
            st.session_state.assessed = []
            st.success(f"[SAFE FALLBACK USED] Discovery returned {stats.get('raw','?')} raw / pruned to {len(pruned)}. Seen filtered: {stats.get('seen_filtered',0)}.")
    else:
        st.warning("Discovery import failed - using fallback discovery (see sidebar error).")
        pruned, stats = _fb_run_discovery(seen_urls=seen_urls)
        st.session_state.discovered = pruned or []
        st.session_state.assessed = []
        st.success(f"[SAFE FALLBACK USED] Discovery returned {stats.get('raw','?')} raw / pruned to {len(pruned)}. Seen filtered: {stats.get('seen_filtered',0)}.")

if st.session_state.discovered:
    st.write(f"Discovered: {len(st.session_state.discovered)} ready for Assess. Discovery uses 0 Gemini calls.")

if st.button("Assess posts (Gemini: max 12, rest heuristic)", key="assess_btn_v472"):
    posts = st.session_state.discovered or []
    if not posts:
        st.warning("Run Discovery first.")
    else:
        usage = get_usage(GEMINI_MODEL)
        gemini_budget = max(0, min(QUOTA_ASSESS_NEEDS, usage["remaining"]))
        if gemini_budget < QUOTA_ASSESS_NEEDS:
            st.warning(quota_message(GEMINI_MODEL, QUOTA_ASSESS_NEEDS))
            if gemini_budget == 0:
                st.info("Quota out - running heuristic-only Assess (0 Gemini calls). Use template drafts.")
        else:
            st.info(f"Quota OK - Gemini will assess up to {gemini_budget} posts, rest heuristic.")
        try:
            candidates = select_for_gemini(posts)
        except Exception:
            candidates = posts[:gemini_budget]
        gemini_posts = candidates[:gemini_budget]
        gemini_ids = {id(p) for p in gemini_posts}
        assessed = []; quota_hit = False; gclient = None
        if gemini_budget > 0 and GeminiClient is not None:
            try:
                gclient = GeminiClient(api_key=os.getenv("GEMINI_API_KEY", ""), model=GEMINI_MODEL)
                if not gclient.is_ready():
                    st.warning(f"Gemini init failed, using heuristic: {gclient.init_error}")
                    gclient = None
            except Exception as e:
                st.warning(f"Gemini init failed, using heuristic: {e}")
                gclient = None
        for p in posts:
            if id(p) in gemini_ids and gclient is not None and not quota_hit:
                try:
                    data = gclient.generate(f"Assess this post for Leadership+AI digest. Return ONLY valid JSON: {{\"relevance\":0-100,\"conversation\":0-100,\"recency\":0-100,\"theme\":\"book theme or other\",\"sensitive\":true/false,\"is_breaking\":true/false,\"reason\":\"short\"}}. Title: {p.get('title','')[:500]} Snippet: {p.get('snippet','')[:1200]} Platform: {p.get('platform','')}")
                    try:
                        _t = re.sub(r"^```(?:json)?\s*", "", data.strip()); _t = re.sub(r"\s*```$", "", _t)
                        d = json.loads(_t)
                    except Exception:
                        m = re.search(r"\{.*\}", data, re.S)
                        d = json.loads(m.group(0)) if m else {}
                    relevance = int(d.get("relevance", 50)); conversation = int(d.get("conversation", 50)); recency = int(d.get("recency", 70))
                    promo = round(relevance*0.30 + conversation*0.35 + recency*0.15 + 20)
                    opp = round((relevance*0.40 + conversation*0.35 + recency*0.25)/10, 1)
                    theme = d.get("theme", "other") or "other"
                    if d.get("sensitive"): decision = "D_SENSITIVE"
                    elif d.get("is_breaking"): decision = "C_WAIT"
                    elif promo >= 80: decision = "A_PROMOTE"
                    elif promo >= 60: decision = "B_ENGAGE"
                    else: decision = "D_SKIP"
                    assessed.append({**p, "decision": decision, "promo": promo, "opp": opp, "theme": theme, "reason": str(d.get("reason","Gemini"))[:200]})
                    continue
                except GeminiTransientError as te:
                    st.warning(f"Gemini overloaded for this post only (503) - using heuristic for this post, continuing to next. {te}")
                    # fall through to heuristic for this post only, do NOT set quota_hit
                except GeminiQuotaExceeded as qe:
                    st.warning(f"{qe} Switching remaining posts to heuristic.")
                    quota_hit = True; st.session_state.quota_hit = True; gclient = None
                except Exception as e:
                    st.warning(f"Gemini analyse failed for {str(p.get('title',''))[:60]}: {e}")
            try:
                h = heuristic_assess(p)
            except Exception:
                h = {"decision": "D_SKIP", "promo": 0, "opp": 0.0, "theme": "other", "reason": "Heuristic failed."}
            assessed.append({**p, **h})
        st.session_state.assessed = assessed
        counts = {}
        for a in assessed:
            if a.get("decision") == "A_PROMOTE":
                counts[a.get("theme","other")] = counts.get(a.get("theme","other"),0)+1
                if counts[a.get("theme","other")] > 2:
                    a["decision"] = "B_ENGAGE"; a["reason"] += " Theme cap: downgraded Promote -> Engage (max 2/theme)."
        _log(f"Assessed: {len(assessed)} (Gemini budget was {gemini_budget})")
        st.success(f"Assessed: {len(assessed)}")

if st.session_state.assessed:
    a_list = st.session_state.assessed
    def _c(d): return sum(1 for x in a_list if x.get("decision")==d)
    st.subheader(f"{len(a_list)} assessed: {_c('A_PROMOTE')} promote - {_c('B_ENGAGE')} engage - {_c('D_SENSITIVE')} sensitive - {_c('C_WAIT')} wait - {_c('D_SKIP')} skip")

st.header("Step 2 - Review drafts")
if not st.session_state.assessed:
    st.info("Run Discovery, then Assess posts.")
else:
    view = st.radio("Show", ["Recommended only (Promote + Engage)", "All", "Skipped / Wait only"], horizontal=True, key="view_radio_v472")
    filtered = st.session_state.assessed
    if view == "Recommended only (Promote + Engage)":
        filtered = [x for x in filtered if x.get("decision") in ("A_PROMOTE","B_ENGAGE")]
    elif view == "Skipped / Wait only":
        filtered = [x for x in filtered if x.get("decision") in ("D_SKIP","C_WAIT","D_SENSITIVE")]
    st.write(f"Showing {len(filtered)} of {len(st.session_state.assessed)} after filter")
    for idx, post in enumerate(filtered):
        if not isinstance(post, dict): continue
        title = str(post.get("title","Untitled"))[:120]
        with st.expander(f"{post.get('platform','Web')} - {title} | Suggested: {post.get('decision')} | Promo: {post.get('promo')} | Opp: {post.get('opp')} | Why: {str(post.get('reason',''))[:120]}"):
            st.markdown(f"Link: [{str(post.get('link',''))[:80]}]({post.get('link','')})")
            st.write(f"**Platform:** {post.get('platform')}")
            st.write(f"**Why:** {post.get('reason')}")
            st.write(f"**Snippet:** {str(post.get('snippet',''))[:400]}")
            if post.get("decision") == "D_SENSITIVE":
                st.warning("Sensitive - drafting blocked.")
            else:
                key = f"draft_{idx}_{str(post.get('link',''))[:30]}_v472"
                if st.button("Generate draft anyway for this post", key=key):
                    usage2 = get_usage(GEMINI_MODEL)
                    if usage2["remaining"] <= 0:
                        st.warning(f"Quota out ({usage2['used']}/{usage2['limit']} used). Using template draft only - 0 Gemini calls.")
                        draft_a = format_draft(template_draft(post))
                    else:
                        st.info(f"Draft needs 1 Gemini call. You have {usage2['remaining']} left.")
                        draft_a = None
                        try:
                            if GeminiClient is not None:
                                g = GeminiClient(api_key=os.getenv("GEMINI_API_KEY",""), model=GEMINI_MODEL)
                                if g.is_ready():
                                    draft_a = g.generate(f"Write ONE comment in CEA structure: Compliment (1 sentence) - Expand (1-2 sentences) - Ask (1 open question). Max 70 words. Plain text. Post: {post.get('title','')} {post.get('snippet','')[:1200]}")
                                else: raise GeminiInitError(g.init_error)
                            else: raise GeminiInitError("GeminiClient not available")
                        except GeminiQuotaExceeded as qe:
                            st.warning(f"{qe} Using template draft."); draft_a = template_draft(post)
                        except Exception as e:
                            st.warning(f"Gemini failed ({e}) - using template draft."); draft_a = template_draft(post)
                        if not draft_a: draft_a = template_draft(post)
                        draft_a = format_draft(draft_a)
                    st.subheader("Option A - Gemini / Template (formatted)")
                    st.markdown(draft_a); st.code(draft_a, language="markdown")
                    st.text_area("Copy Option A", value=draft_a, key=f"copy_a_{idx}_v472", height=150)

with st.expander("Debug"):
    if st.button("Test Gemini now", key="test_gemini_btn_v472"):
        u3 = get_usage(GEMINI_MODEL)
        if u3["remaining"] <= 0:
            st.error(f"Quota out: {u3['used']}/{u3['limit']} used. Resets {u3['reset_label']}. Do NOT keep clicking Test.")
        elif GeminiClient is None:
            st.error(f"Gemini import failed: {_GEMINI_IMPORT_ERR}")
        else:
            try:
                c = GeminiClient(api_key=os.getenv("GEMINI_API_KEY",""), model=GEMINI_MODEL)
                if not c.is_ready(): st.error(f"Gemini init failed: {c.init_error}")
                else: st.success(f"Gemini OK ({c.model}): {c.test()}")
            except GeminiQuotaExceeded as qe: st.error(f"QuotaExceeded: {qe}")
            except Exception as e: st.error(f"Gemini failed (real error): {e}")
    st.write(f"GEMINI_MODEL in use: {GEMINI_MODEL}")
    st.write(f"Quota file: quota_usage.json (auto-created, resets midnight Pacific)")

st.subheader("Last Run log")
st.code("\n".join(st.session_state.last_run_log) if st.session_state.last_run_log else "No runs yet.")
