# app.py - v4.9.3.3 - Compact sidebar + copyable discovery error + Discovery diagnostic
# Root: app.py
import os, json, re

import streamlit as st

from config import GEMINI_MODEL, MODEL_QUOTAS, QUOTA_ASSESS_NEEDS, QUOTA_DRAFT_NEEDS, QUOTA_TEST_NEEDS, QUOTA_FALLBACK_MODEL, SEARCH_TERMS, SEARCH_PROVIDER, SERPER_API_KEY

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

# --- Grok fallback (separate quota) ---
try:
    from grok_client import GrokClient, GrokQuotaExceeded, GrokTransientError
    from config import GROK_MODEL
except Exception:
    GrokClient = None
    class GrokQuotaExceeded(Exception): pass
    class GrokTransientError(Exception): pass
    GROK_MODEL = "llama-3.3-70b-versatile"


# --- Discovery with diagnostic ---
_DISCOVERY_ERR = None
_DISCOVERY_ERR_FULL = ""
try:
    from discovery import run_discovery_with_stats
    import discovery as _disc_mod
    DISCOVERY_VERSION = getattr(_disc_mod, "__VERSION__", "OLD")
    _has_norm = hasattr(_disc_mod, "_normalize_post")
    DISCOVERY_IS_NEW = bool(_has_norm and str(DISCOVERY_VERSION).strip().startswith("4."))
    if not DISCOVERY_IS_NEW and str(DISCOVERY_VERSION) not in ("OLD",):
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
    from drafting.generator import generate_drafts
except Exception:
    def format_draft(x): return x or ""
    def generate_drafts(*args, **kwargs): pass
try:
    from scoring.selection import heuristic_assess, select_for_gemini, template_draft
except Exception:
    def heuristic_assess(p):
        _hay = ((p.get("title") or "") + " " + (p.get("snippet") or "") + " " + (p.get("_deep_text") or "")).lower()
        _strong = ["upskill", "reskill", "corporate training", "l&d", "learning and development", "hybrid intelligence", "human edge", "game-based", "experiential learning"]
        _medium = ["ai training", "ai upskilling", "leadership", "coaching", "workforce", "future of work", "adaptability", "critical thinking"]
        _s = sum(1 for k in _strong if k in _hay)
        _m = sum(1 for k in _medium if k in _hay)
        if _s >= 1:
            return {"decision": "A_PROMOTE", "promo": 70, "opp": 6.5, "theme": "upskilling", "reason": f"Heuristic fallback - strong keyword ({_s} strong) - title/body matched upskilling / human edge."}
        if _m >= 2:
            return {"decision": "B_ENGAGE", "promo": 55, "opp": 5.0, "theme": "leadership", "reason": f"Heuristic fallback - medium keywords ({_m}) - leadership / AI training."}
        return {"decision": "D_SKIP", "promo": 0, "opp": 0.0, "theme": "other", "reason": "Heuristic fallback - no AI/upskilling keywords in title/snippet/body."}
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
            seen.add(line.split("|")[0].strip())
        else: seen.add(line)
    return seen

def _fb_run_discovery(seen_urls=None, search_terms=None):
    seen_urls = seen_urls or set()
    from config import MAX_RESULTS_PER_SOURCE
    _terms = search_terms if search_terms else SEARCH_TERMS
    all_posts = []
    per_source = {}
    try:
        from discovery.web_search import search_web
        for q in _terms:
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


def _load_grounding():
    try:
        from pathlib import Path as _P
        gdir = _P(__file__).parent / "grounding"
        out = {}
        for fname, key in [("00_book_core.txt","core"),("01_hybrid_intelligence.txt","cat1"),("02_passive_ld.txt","cat2"),("03_roi_architecture.txt","cat3"),("04_voice.txt","voice")]:
            try:
                p = gdir / fname
                out[key] = p.read_text(encoding="utf-8")[:4000] if p.exists() else ""
            except Exception:
                out[key] = ""
        return out
    except Exception:
        return {"core":"","cat1":"","cat2":"","cat3":"","voice":""}

def _pick_grounding_category(post, grounding):
    try:
        hay = ((post.get("title") or "") + " " + (post.get("snippet") or "") + " " + (post.get("_deep_text") or "")).lower()
        c2 = sum(1 for k in ["passive", "lecture", "slide", "webinar", "e-learning", "elearning", "training module", "course"] if k in hay)
        c3 = sum(1 for k in ["roi", "budget", "executive", "transformation", "change management", "adoption", "debrief", "facilitat", "6 pillar"] if k in hay)
        c1 = sum(1 for k in ["automation", "automate", "ai tool", "reskill", "upskill", "hybrid", "human edge", "workforce"] if k in hay)
        if c2 > c1 and c2 >= c3:
            return ("cat2", "Category 2 - Passive L&D", grounding.get("cat2",""))
        if c3 > c1 and c3 >= c2:
            return ("cat3", "Category 3 - ROI & Architecture", grounding.get("cat3",""))
        return ("cat1", "Category 1 - Hybrid Intelligence Era", grounding.get("cat1",""))
    except Exception:
        return ("cat1", "Category 1 - Hybrid Intelligence Era", grounding.get("cat1",""))

def _build_grounding_prompt(post, grounding):
    try:
        core = grounding.get("core","")
        voice = grounding.get("voice","")
        key, label, cat_text = _pick_grounding_category(post, grounding)
        parts = []
        if core: parts.append(core.strip())
        if cat_text: parts.append(cat_text.strip())
        if voice: parts.append(voice.strip())
        return ("\n\n".join(parts)[:3500], label)
    except Exception:
        return ("", "Category 1 - Hybrid Intelligence Era")

# ================= SIDEBAR =================
st.sidebar.title("Leadership AI Daily Digest")

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

if st.session_state.get("discovered") or st.session_state.get("discovery_raw_links"):
    _all_seen = set(seen_urls) | set(st.session_state.get("discovery_raw_links", [])) | {p.get("link", "") for p in st.session_state.get("discovered", []) if p.get("link")}
    _seen_txt = "\n".join(sorted(_all_seen))
    st.sidebar.download_button("⬇ Download seen_posts.txt (all 75 raw)", _seen_txt, file_name="seen_posts.txt", mime="text/plain", key="download_seen_v493")

st.sidebar.caption(f"Gemini: {'OK' if os.getenv('GEMINI_API_KEY') else 'MISSING'} | Grok: {'OK' if os.getenv('GROQ_API_KEY') else 'MISSING'} | Model:         ")
st.sidebar.caption(f"Search: {SEARCH_PROVIDER} | Serper key: {'OK' if SERPER_API_KEY else 'not set - using DuckDuckGo'}")
st.sidebar.caption(f"Discovery: {DISCOVERY_VERSION}")
if not DISCOVERY_IS_NEW:
    if _DISCOVERY_ERR:
        st.sidebar.error("Discovery import failed - app uses fallback.")
        with st.sidebar.expander("Tap to see discovery error - copy it"):
            st.sidebar.code(_DISCOVERY_ERR_FULL[:2000])
            st.sidebar.caption("Copy the text above and paste it here.")
    else:
        st.sidebar.error(f"Discovery OLD ({DISCOVERY_VERSION}).")

u = get_usage(GEMINI_MODEL)
st.sidebar.caption(f"Quota {u['label']}: {u['used']}/{u['limit']} used, {u['remaining']} left")
try:
    from quota import quota_reboot_warning
    _rw = quota_reboot_warning(GEMINI_MODEL)
    if _rw and u['used'] == 0:
        st.sidebar.caption("Reboot? Enter that number in AI Studio sync below if used today.")
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
if "kill_requested" not in st.session_state:
    st.session_state.kill_requested = False
if "current_task" not in st.session_state:
    st.session_state.current_task = ""
_top_left, _top_right = st.columns([5, 1])
with _top_left:
    st.title("Leadership AI Daily Digest")
with _top_right:
    st.write("")
    if st.button("⏹ Stop task", key="kill_btn_top_v492", help="Stop current task."):
        st.session_state.kill_requested = True
        st.warning("Stop requested.")
if st.session_state.kill_requested:
    st.warning(f"Stop requested for: {st.session_state.current_task or 'current task'}.")

def _check_kill():
    if st.session_state.get("kill_requested"):
        raise InterruptedError("Stopped by user")

def _clear_kill(task_name):
    st.session_state.kill_requested = False
    st.session_state.current_task = task_name

st.write("Step 1: Run Discovery -> Assess -> Step 2: Review drafts.")
_has_discovered = bool(st.session_state.get("discovered"))
_has_assessed = bool(st.session_state.get("assessed"))
if _has_discovered and _has_assessed:
    _current_step = "draft"
elif _has_discovered:
    _current_step = "assess"
else:
    _current_step = "discovery"

st.caption(f"Current step: {_current_step.upper()} | Discovery → Assess → Draft.")
_show_discovery = False
if _current_step != "discovery":
    with st.expander(f"Step 1 - Discovery (done - {len(st.session_state.get('discovered',[]))} posts) - tap to re-run"):
        _show_discovery = True
else:
    st.header("Step 1 - Discovery")
    _show_discovery = True

if _show_discovery:
    st.subheader("Step 1 - Discovery")
    st.caption(f"Search provider: {SEARCH_PROVIDER}")

st.subheader("Search terms - edit before Discovery")
try:
    _default_terms = "\n".join(SEARCH_TERMS)
except Exception:
    _default_terms = "corporate upskilling AI\nAI upskilling program\nL&D AI training\nreskilling workforce AI"
if "search_terms_text_v491" not in st.session_state:
    st.session_state.search_terms_text_v491 = _default_terms
search_terms_text = st.text_area("Search terms (one per line)", value=st.session_state.search_terms_text_v491, height=180, key="search_terms_editor_v491")
_parsed_terms = [l.strip() for l in (search_terms_text or "").splitlines() if l.strip()]
_seen_q = set(); _parsed_dedup = []
for _q in _parsed_terms:
    if _q not in _seen_q:
        _seen_q.add(_q); _parsed_dedup.append(_q)
_parsed_terms = _parsed_dedup

col_reset, col_info = st.columns([1, 3])
with col_reset:
    if st.button("Reset to defaults", key="reset_terms_btn_v491"):
        st.session_state.search_terms_text_v491 = _default_terms
        st.rerun()
with col_info:
    st.caption("Tip: add site:linkedin.com to force social results.")

if not _parsed_terms:
    st.warning("No search terms - add at least 1 term or click Reset to defaults.")

if st.button("Run Discovery", key="run_discovery_btn_v472"):
    _clear_kill("Discovery")
    _disc_status = st.empty()
    _disc_prog = st.progress(0)
    _disc_status.info("Discovery running...")
    if run_discovery_with_stats is not None:
        try:
            pruned, stats = run_discovery_with_stats(seen_urls=seen_urls, search_terms=_parsed_terms, progress_cb=lambda done, total: (_disc_prog.progress(min(1.0, done/total)) if total else None, _disc_status.info(f'Discovery Deep check {done}/{total}...')))
            _log(f"Discovery: raw={stats.get('raw','?')} kept={stats.get('kept_for_assessment', len(pruned))}")
            st.session_state.discovered = pruned or []
            st.session_state.discovery_raw_links = stats.get("raw_links", [])
            st.session_state.assessed = []
            _disc_prog.progress(1.0)
            _disc_status.success("Discovery done.")
            st.success(f"Discovery complete: Kept {len(pruned)} for assessment.")
        except Exception as e:
            st.warning(f"Real discovery failed ({e}) - using fallback discovery.")
            pruned, stats = _fb_run_discovery(seen_urls=seen_urls, search_terms=_parsed_terms)
            st.session_state.discovered = pruned or []
            st.session_state.assessed = []
            st.success(f"[SAFE FALLBACK USED] Discovery returned {len(pruned)} posts.")
    else:
        pruned, stats = _fb_run_discovery(seen_urls=seen_urls, search_terms=_parsed_terms)
        st.session_state.discovered = pruned or []
        st.session_state.assessed = []
        st.success(f"[SAFE FALLBACK USED] Discovery returned {len(pruned)} posts.")

_has_discovered = bool(st.session_state.get("discovered"))
_has_assessed = bool(st.session_state.get("assessed"))
if _has_discovered and _has_assessed:
    _current_step = "draft"
elif _has_discovered:
    _current_step = "assess"
else:
    _current_step = "discovery"

if st.session_state.discovered:
    st.write(f"Discovered: {len(st.session_state.discovered)} ready for Assess.")

_show_assess = False
if _current_step == "discovery" and not _has_discovered:
    st.info("Complete Step 1 Discovery first.")
elif _current_step != "assess" and _has_assessed:
    with st.expander(f"Step 2 - Assess (done - {len(st.session_state.get('assessed',[]))} assessed) - tap to re-assess"):
        _show_assess = True
else:
    st.header("Step 2 - Assess")
    _show_assess = True

if _show_assess and st.button("Assess posts (Gemini: max 12, rest heuristic)", key="assess_btn_v472"):
    _clear_kill("Assess")
    _assess_status = st.empty()
    _assess_prog = st.progress(0)
    posts = st.session_state.discovered or []
    if not posts:
        st.warning("Run Discovery first.")
    else:
        usage = get_usage(GEMINI_MODEL)
        gemini_budget = max(0, min(QUOTA_ASSESS_NEEDS, usage["remaining"]))
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
                if not gclient.is_ready(): gclient = None
            except Exception:
                gclient = None
        
        grok_client_for_assess = None
        if GrokClient is not None:
            try:
                _gc = GrokClient(api_key=os.getenv("GROK_API_KEY", ""), model=GROK_MODEL)
                if _gc.is_ready(): grok_client_for_assess = _gc
            except Exception:
                grok_client_for_assess = None

        _assess_total = len(posts)
        _assess_done = 0
        for p in posts:
            try:
                _check_kill()
            except InterruptedError:
                break
            _assess_done += 1
            _assess_prog.progress(min(1.0, _assess_done / max(1, _assess_total)))
            
            if id(p) in gemini_ids and gclient is not None and not quota_hit:
                try:
                    data = gclient.generate(f"Assess this post for Leadership+AI digest. Return ONLY valid JSON: {{\"relevance\":0-100,\"conversation\":0-100,\"recency\":0-100,\"theme\":\"book theme or other\",\"sensitive\":true/false,\"is_breaking\":true/false,\"reason\":\"short\"}}. Title: {p.get('title','')[:500]} Snippet: {p.get('snippet','')[:800]}")
                    _t = re.sub(r"^```(?:json)?\s*", "", data.strip()); _t = re.sub(r"\s*```$", "", _t)
                    d = json.loads(_t)
                    relevance = int(d.get("relevance", 50)); conversation = int(d.get("conversation", 50)); recency = int(d.get("recency", 70))
                    promo = round(relevance*0.30 + conversation*0.35 + recency*0.15 + 20)
                    opp = round((relevance*0.40 + conversation*0.35 + recency*0.25)/10, 1)
                    theme = d.get("theme", "other") or "other"
                    decision = "A_PROMOTE" if promo >= 80 else ("B_ENGAGE" if promo >= 60 else "D_SKIP")
                    assessed.append({**p, "decision": decision, "promo": promo, "opp": opp, "theme": theme, "reason": str(d.get("reason","Gemini"))[:200]})
                    continue
                except GeminiQuotaExceeded:
                    quota_hit = True; gclient = None
                except Exception:
                    pass

            _grok_done = False
            if grok_client_for_assess is not None and (quota_hit or id(p) not in gemini_ids or gclient is None):
                try:
                    _gdata = grok_client_for_assess.generate(f"Assess this post. Return ONLY valid JSON: {{\"relevance\":0-100,\"conversation\":0-100,\"recency\":0-100,\"theme\":\"other\",\"sensitive\":false,\"is_breaking\":false,\"reason\":\"short\"}}. Title: {p.get('title','')[:500]}")
                    _t2 = re.sub(r"^```(?:json)?\s*", "", _gdata.strip()); _t2 = re.sub(r"\s*```$", "", _t2)
                    _d2 = json.loads(_t2)
                    _rel = int(_d2.get("relevance", 50)); _conv = int(_d2.get("conversation", 50)); _rec = int(_d2.get("recency", 70))
                    _promo = round(_rel*0.30 + _conv*0.35 + _rec*0.15 + 20)
                    _opp = round((_rel*0.40 + _conv*0.35 + _rec*0.25)/10, 1)
                    _dec = "A_PROMOTE" if _promo >= 80 else ("B_ENGAGE" if _promo >= 60 else "D_SKIP")
                    assessed.append({**p, "decision": _dec, "promo": _promo, "opp": _opp, "theme": _d2.get("theme", "other"), "reason": "Grok Assess"})
                    _grok_done = True
                    continue
                except Exception:
                    pass

            if _grok_done: continue
            try:
                h = heuristic_assess(p)
            except Exception:
                h = {"decision": "D_SKIP", "promo": 0, "opp": 0.0, "theme": "other", "reason": "Heuristic failed."}
            assessed.append({**p, **h})

        st.session_state.assessed = assessed
        st.success(f"Assessed: {len(assessed)}")

if st.session_state.assessed:
    a_list = st.session_state.assessed
    def _c(d): return sum(1 for x in a_list if x.get("decision")==d)
    st.subheader(f"{len(a_list)} assessed: {_c('A_PROMOTE')} promote - {_c('B_ENGAGE')} engage - {_c('D_SKIP')} skip")

if not _has_assessed:
    st.info("Step 3 - Review drafts: Complete Assess first.")
else:
    st.header("Step 3 - Review drafts")

if st.session_state.assessed:
    view = st.radio("Show", ["Promote only", "Recommended only (Promote + Engage)", "All"], horizontal=True, key="view_radio_v472")
    filtered = st.session_state.assessed
    if view == "Promote only":
        filtered = [x for x in filtered if x.get("decision") == "A_PROMOTE"]
    elif view == "Recommended only (Promote + Engage)":
        filtered = [x for x in filtered if x.get("decision") in ("A_PROMOTE","B_ENGAGE")]

    for idx, post in enumerate(filtered):
        if not isinstance(post, dict): continue
        title = str(post.get("title","Untitled"))[:120]
        with st.expander(f"{post.get('platform','Web')} - {title} | Suggested: {post.get('decision')} | Promo: {post.get('promo')}"):
            st.markdown(f"Link: [{str(post.get('link',''))[:80]}]({post.get('link','')})")
            if st.button("Generate template draft only (no AI, instant)", key=f"draft_{idx}_template"):
                _tmpl = format_draft(template_draft(post))
                st.write(_tmpl)
            if st.button("Generate draft anyway for this post", key=f"draft_{idx}_ai"):
                with st.spinner("Generating fresh grounded draft..."):
                    # 2026-11-11: Fix - do NOT force decision to A_PROMOTE, keep original (Engage stays Engage).
                    # Reason: old code promoted every Engage post to Promote.
                    from drafting.generator import generate_drafts
                    generate_drafts(
                        client=st.session_state.get("gemini_client"), 
                        item=post, 
                        variant=0, 
                        grok_client=st.session_state.get("grok_client")
                    )
                # 2026-11-11: Fix - show draft, do NOT st.rerun() immediately.
                # Reason: old st.rerun() hid the draft, button looked like it did nothing.
                st.subheader("Option A - Draft")
                st.write(post.get("comment", "No draft generated - check logs."))
                if post.get("grok_comment"):
                    st.subheader("Option B - Grok reviewed")
                    st.write(post.get("grok_comment"))
                    st.caption(post.get("grok_note", ""))

# --- Dual-Engine Debug & Diagnostic ---
with st.expander("Dual-Engine Debug & Diagnostic"):
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        if st.button("Test Gemini now", key="test_gemini_diag_v493"):
            u3 = get_usage(GEMINI_MODEL)
            if u3["remaining"] <= 0:
                st.error(f"Quota out: {u3['used']}/{u3['limit']} used.")
            elif GeminiClient is None:
                st.error(f"Gemini import failed: {_GEMINI_IMPORT_ERR}")
            else:
                try:
                    c = GeminiClient(api_key=os.getenv("GEMINI_API_KEY",""), model=GEMINI_MODEL)
                    if not c.is_ready(): st.error(f"Gemini init failed: {c.init_error}")
                    else: st.success(f"Gemini OK ({c.model}): {c.test()}")
                except Exception as e: st.error(f"Gemini failed: {e}")
    with col_g2:
        if st.button("Test Groq Now", key="test_groq_diag_v493"):
            if GrokClient is None:
                st.error("GroqClient failed to import.")
            else:
                try:
                    gc = GrokClient(api_key=os.getenv("GROQ_API_KEY", ""), model=GROK_MODEL)
                    if not gc.is_ready(): st.error(f"Groq init failed: {gc.init_error}")
                    else: st.success(f"Groq OK: {gc.generate('Say Hi in 2 words.')}")
                except Exception as ge: st.error(f"Groq failed: {ge}")
    st.write(f"GEMINI_MODEL: {GEMINI_MODEL} | GROQ_MODEL: {GROK_MODEL}")

st.subheader("Last Run log")
st.code("\n".join(st.session_state.last_run_log) if st.session_state.last_run_log else "No runs yet.")
