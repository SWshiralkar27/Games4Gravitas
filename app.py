
# app.py - v4.7 - Quota-guarded Leadership AI Digest
# Root: app.py
# CHANGELOG v4.7:
# - Sidebar quota panel: live used / limit / remaining for GEMINI_MODEL, with progress bar
# - Pre-flight warning BEFORE Assess / Draft / Test: if remaining < needed, yellow warning in sidebar + main
# - No API call is made if it would exceed RPD - gemini_client raises GeminiQuotaExceeded without calling API
# - Assess: uses Gemini for min(12, remaining) posts, rest heuristic - never overruns
# - Draft: if remaining == 0, shows template only, no Gemini call
# - Manual sync: if you used Gemini in AI Studio outside app, enter that number - app takes max(internal, manual)
# Discovery uses 0 Gemini calls. Scoring heuristic uses 0 calls. Only Assess / Draft / Test use Gemini.
import os, json, re

import streamlit as st

from config import GEMINI_MODEL, MODEL_QUOTAS, QUOTA_ASSESS_NEEDS, QUOTA_DRAFT_NEEDS, QUOTA_TEST_NEEDS, QUOTA_FALLBACK_MODEL

# --- Quota ---
try:
    from quota import get_usage, can_afford, quota_level, quota_message, set_manual_used
except Exception as e:
    def get_usage(m): return {"model": m, "label": m, "used": 0, "limit": 20, "remaining": 20, "pct": 0, "reset_label": "midnight Pacific"}
    def can_afford(m, n=1): return True
    def quota_level(m, n=1): return "ok"
    def quota_message(m, n=1): return ""
    def set_manual_used(m, n): return get_usage(m)

# --- Gemini ---
try:
    from gemini_client import GeminiClient, GeminiQuotaExceeded, GeminiInitError
except Exception as e:
    GeminiClient = None
    class GeminiQuotaExceeded(Exception): pass
    class GeminiInitError(Exception): pass
    _GEMINI_IMPORT_ERR = e
else:
    _GEMINI_IMPORT_ERR = None

# --- Discovery ---
try:
    from discovery import run_discovery_with_stats
    import discovery as _disc_mod
    DISCOVERY_VERSION = getattr(_disc_mod, "__VERSION__", "OLD")
    DISCOVERY_IS_NEW = hasattr(_disc_mod, "_normalize_post") and str(DISCOVERY_VERSION) in ("4.4", "4.5", "4.6", "4.7")
except Exception as e:
    run_discovery_with_stats = None
    DISCOVERY_VERSION = "OLD - import failed"
    DISCOVERY_IS_NEW = False
    _DISCOVERY_ERR = e
else:
    _DISCOVERY_ERR = None

# --- Formatting / Scoring (fail-open) ---
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

# --- Session state ---
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
        else: seen.add(line)
        if "|" in line and not line.startswith("http"):
            seen.add(line.split("|")[0].strip())
    return seen

# ================= SIDEBAR =================
st.sidebar.title("Leadership AI Daily Digest")

# Secrets status (no values shown)
st.sidebar.write(f"Gemini Key: {'OK' if os.getenv('GEMINI_API_KEY') else 'MISSING'}")
st.sidebar.write(f"Grok Key: {'OK' if os.getenv('GROK_API_KEY') else 'MISSING'}")
st.sidebar.write(f"Gemini Model: {GEMINI_MODEL}")
st.sidebar.write(f"Discovery file: {DISCOVERY_VERSION}")
if not DISCOVERY_IS_NEW:
    st.sidebar.error("Discovery file is OLD. Re-upload discovery/__init__.py v4.7 to discovery/ folder (not root).")

# --- QUOTA PANEL (NEW v4.7) ---
st.sidebar.subheader("Gemini Quota - Free Tier")
# Manual sync - if user used Gemini outside app (AI Studio), enter that count
# Use a separate key so number_input does not clash with value+key rule: only key, no value
manual = st.sidebar.number_input(
    "Already used today in AI Studio (outside app, 0 if none)",
    min_value=0, max_value=1000, step=1, key="quota_manual_input"
)
# Apply manual sync when it changes
if "quota_manual_applied" not in st.session_state:
    st.session_state.quota_manual_applied = -1
if manual != st.session_state.quota_manual_applied:
    try:
        set_manual_used(GEMINI_MODEL, int(manual))
        st.session_state.quota_manual_applied = int(manual)
    except Exception:
        pass

u = get_usage(GEMINI_MODEL)
st.sidebar.write(f"{u['label']}: {u['used']}/{u['limit']} used today")
st.sidebar.progress(min(1.0, u['used'] / u['limit']) if u['limit'] else 0)
st.sidebar.write(f"Remaining: {u['remaining']}  |  Resets: {u['reset_label']}")
st.sidebar.write(f"Assess needs {QUOTA_ASSESS_NEEDS}  |  Draft needs {QUOTA_DRAFT_NEEDS}  |  Test needs {QUOTA_TEST_NEEDS}")

lvl = quota_level(GEMINI_MODEL, QUOTA_ASSESS_NEEDS)
if lvl == "block":
    st.sidebar.error(f"Quota OUT for {u['label']}. Use heuristic / template drafts only. Or switch GEMINI_MODEL to {QUOTA_FALLBACK_MODEL} (500/day) in Secrets and reboot.")
elif lvl == "warn":
    st.sidebar.warning(f"Not enough for full Assess: need {QUOTA_ASSESS_NEEDS}, have {u['remaining']} left. Will use Gemini for {u['remaining']} posts + heuristic for rest.")
else:
    st.sidebar.success(f"Safe to Assess: need {QUOTA_ASSESS_NEEDS}, have {u['remaining']} left.")

# Seen posts
seen_file = st.sidebar.file_uploader("Upload seen_posts.txt", type=["txt"], key="seen_uploader")
seen_urls = set()
if seen_file is not None:
    try:
        seen_urls = _parse_seen(seen_file.read().decode("utf-8", errors="ignore"))
        st.sidebar.write(f"Seen loaded: {len(seen_urls)}")
    except Exception as e:
        st.sidebar.error(f"Seen file error: {e}")

# ================= MAIN =================
st.title("Leadership AI Daily Digest")
st.write("Step 1: Run Discovery (0 Gemini calls) -> Assess (max 12 Gemini calls, rest heuristic) -> Step 2: Review drafts.")

# --- Step 1: Discovery ---
st.header("Step 1 - Discovery")
if st.button("Run Discovery", key="run_discovery_btn"):
    if run_discovery_with_stats is None:
        st.error(f"Discovery import failed: {_DISCOVERY_ERR}")
    else:
        try:
            pruned, stats = run_discovery_with_stats(seen_urls=seen_urls)
        except Exception as e:
            st.error(f"Discovery failed: {e}")
            pruned, stats = [], {}
        st.session_state.discovered = pruned or []
        st.session_state.assessed = []
        _log(f"Discovery: raw={stats.get('raw','?')} invalid_skipped={stats.get('invalid_skipped',0)} seen_filtered={stats.get('seen_filtered',0)} deduped={stats.get('deduped','?')} social={stats.get('social','?')} web_pruned={stats.get('web_pruned',0)} kept={stats.get('kept_for_assessment', len(pruned))} fallback={stats.get('fallback', False)}")
        st.success(f"Discovery returned {stats.get('raw','?')} raw posts before dedupe / pruned to {len(pruned)} for assessment. Seen filtered: {stats.get('seen_filtered',0)}. Invalid skipped: {stats.get('invalid_skipped',0)}. Web articles pruned: {stats.get('web_pruned',0)}. Social threads: {stats.get('social','?')}. Per-source: {stats.get('per_source', {})}")

if st.session_state.discovered:
    st.write(f"Discovered: {len(st.session_state.discovered)} ready for Assess. Discovery uses 0 Gemini calls.")

# --- Assess ---
if st.button("Assess posts (Gemini: max 12, rest heuristic)", key="assess_btn"):
    posts = st.session_state.discovered or []
    if not posts:
        st.warning("Run Discovery first.")
    else:
        # PRE-FLIGHT: how many Gemini calls can we afford?
        usage = get_usage(GEMINI_MODEL)
        gemini_budget = max(0, min(QUOTA_ASSESS_NEEDS, usage["remaining"]))
        if gemini_budget < QUOTA_ASSESS_NEEDS:
            st.warning(quota_message(GEMINI_MODEL, QUOTA_ASSESS_NEEDS))
            if gemini_budget == 0:
                st.info("Quota out - running heuristic-only Assess (0 Gemini calls). Use template drafts.")
        else:
            st.info(f"Quota OK - Gemini will assess up to {gemini_budget} posts, rest heuristic.")
        # Pick top candidates for Gemini
        try:
            candidates = select_for_gemini(posts)
        except Exception:
            candidates = posts[:gemini_budget]
        gemini_posts = candidates[:gemini_budget]
        gemini_ids = {id(p) for p in gemini_posts}
        assessed = []
        quota_hit = False
        # Gemini client (only if we have budget)
        gclient = None
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
                    # Parse Gemini JSON
                    try:
                        import json as _json
                        # Strip fences
                        _t = re.sub(r"^```(?:json)?\s*", "", data.strip())
                        _t = re.sub(r"\s*```$", "", _t)
                        d = _json.loads(_t)
                    except Exception:
                        m = re.search(r"\{.*\}", data, re.S)
                        d = json.loads(m.group(0)) if m else {}
                    relevance = int(d.get("relevance", 50)); conversation = int(d.get("conversation", 50)); recency = int(d.get("recency", 70))
                    promo = round(relevance*0.30 + conversation*0.35 + recency*0.15 + 20)
                    opp = round((relevance*0.40 + conversation*0.35 + recency*0.25)/10, 1)
                    theme = d.get("theme", "other") or "other"
                    if d.get("sensitive"):
                        decision = "D_SENSITIVE"
                    elif d.get("is_breaking"):
                        decision = "C_WAIT"
                    elif promo >= 80:
                        decision = "A_PROMOTE"
                    elif promo >= 60:
                        decision = "B_ENGAGE"
                    else:
                        decision = "D_SKIP"
                    assessed.append({**p, "decision": decision, "promo": promo, "opp": opp, "theme": theme, "reason": str(d.get("reason","Gemini"))[:200]})
                    continue
                except GeminiQuotaExceeded as qe:
                    st.warning(f"{qe} Switching remaining posts to heuristic.")
                    quota_hit = True
                    st.session_state.quota_hit = True
                    gclient = None
                except Exception as e:
                    st.warning(f"Gemini analyse failed for {str(p.get('title',''))[:60]}: {e}")
                    # fall through to heuristic
            # Heuristic fallback
            try:
                h = heuristic_assess(p)
            except Exception:
                h = {"decision": "D_SKIP", "promo": 0, "opp": 0.0, "theme": "other", "reason": "Heuristic failed."}
            assessed.append({**p, **h})
        st.session_state.assessed = assessed
        # Theme cap: max 2 Promote per theme
        counts = {}
        for a in assessed:
            if a.get("decision") == "A_PROMOTE":
                counts[a.get("theme","other")] = counts.get(a.get("theme","other"),0)+1
                if counts[a.get("theme","other")] > 2:
                    a["decision"] = "B_ENGAGE"
                    a["reason"] += " Theme cap: downgraded Promote -> Engage (max 2/theme)."
        _log(f"Assessed: {len(assessed)} (Gemini budget was {gemini_budget})")
        st.success(f"Assessed: {len(assessed)}")

if st.session_state.assessed:
    a_list = st.session_state.assessed
    def _c(d): return sum(1 for x in a_list if x.get("decision")==d)
    st.subheader(f"{len(a_list)} assessed: {_c('A_PROMOTE')} promote - {_c('B_ENGAGE')} engage - {_c('D_SENSITIVE')} sensitive - {_c('C_WAIT')} wait - {_c('D_SKIP')} skip")

# --- Step 2: Review drafts ---
st.header("Step 2 - Review drafts")
if not st.session_state.assessed:
    st.info("Run Discovery, then Assess posts.")
else:
    view = st.radio("Show", ["Recommended only (Promote + Engage)", "All", "Skipped / Wait only"], horizontal=True, key="view_radio")
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
                key = f"draft_{idx}_{str(post.get('link',''))[:30]}"
                if st.button("Generate draft anyway for this post", key=key):
                    # PRE-FLIGHT for draft: need 1 Gemini call
                    usage2 = get_usage(GEMINI_MODEL)
                    if usage2["remaining"] <= 0:
                        st.warning(f"Quota out ({usage2['used']}/{usage2['limit']} used). Using template draft only - 0 Gemini calls.")
                        draft_a = template_draft(post)
                        draft_a = format_draft(draft_a)
                    else:
                        st.info(f"Draft needs 1 Gemini call. You have {usage2['remaining']} left.")
                        draft_a = None
                        try:
                            if GeminiClient is not None:
                                g = GeminiClient(api_key=os.getenv("GEMINI_API_KEY",""), model=GEMINI_MODEL)
                                if g.is_ready():
                                    draft_a = g.generate(f"Write ONE comment in CEA structure: Compliment (1 sentence) - Expand (1-2 sentences) - Ask (1 open question). Max 70 words. Plain text. Post: {post.get('title','')} {post.get('snippet','')[:1200]}")
                                else:
                                    raise GeminiInitError(g.init_error)
                            else:
                                raise GeminiInitError("GeminiClient not available")
                        except GeminiQuotaExceeded as qe:
                            st.warning(f"{qe} Using template draft.")
                            draft_a = template_draft(post)
                        except Exception as e:
                            st.warning(f"Gemini failed ({e}) - using template draft.")
                            draft_a = template_draft(post)
                        if not draft_a:
                            draft_a = template_draft(post)
                        draft_a = format_draft(draft_a)
                    st.subheader("Option A - Gemini / Template (formatted)")
                    st.markdown(draft_a)
                    st.code(draft_a, language="markdown")
                    st.text_area("Copy Option A", value=draft_a, key=f"copy_a_{idx}", height=150)

# --- Debug ---
with st.expander("Debug"):
    if st.button("Test Gemini now", key="test_gemini_btn"):
        # PRE-FLIGHT: Test needs 1 call
        u3 = get_usage(GEMINI_MODEL)
        if u3["remaining"] <= 0:
            st.error(f"Quota out: {u3['used']}/{u3['limit']} used. Resets {u3['reset_label']}. Do NOT keep clicking Test - it would burn a call if quota were available.")
        elif GeminiClient is None:
            st.error(f"Gemini import failed: {_GEMINI_IMPORT_ERR}")
        else:
            try:
                c = GeminiClient(api_key=os.getenv("GEMINI_API_KEY",""), model=GEMINI_MODEL)
                if not c.is_ready():
                    st.error(f"Gemini init failed: {c.init_error}")
                else:
                    st.success(f"Gemini OK ({c.model}): {c.test()}")
            except GeminiQuotaExceeded as qe:
                st.error(f"QuotaExceeded: {qe}")
            except Exception as e:
                st.error(f"Gemini failed (real error): {e}")
    st.write(f"GEMINI_MODEL in use: {GEMINI_MODEL}")
    st.write(f"Quota file: quota_usage.json (auto-created, resets midnight Pacific)")

st.subheader("Last Run log")
st.code("\n".join(st.session_state.last_run_log) if st.session_state.last_run_log else "No runs yet.")

