
# app.py - v4.9.3.3 - Compact sidebar + copyable discovery error + Discovery diagnostic
# Root: app.py
# CHANGELOG v4.7.1 vs v4.7:
# - Seen_posts.txt uploader moved back to TOP of sidebar (was pushed below quota panel, looked gone)
# - Effectiveness.txt uploader restored (was missing in v4.7)
# - Quota panel moved BELOW Seen / Effectiveness, so it never hides them
# - Discovery check: accepts 4.4/4.5/4.6/4.7, shows REAL import error in sidebar if import fails (not just OLD)
# - If discovery import fails, uses in-app fallback discovery so app still works
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
    GROK_MODEL = "grok-3-mini"

# --- Discovery with diagnostic ---
_DISCOVERY_ERR = None
_DISCOVERY_ERR_FULL = ""
try:
    from discovery import run_discovery_with_stats
    import discovery as _disc_mod
    DISCOVERY_VERSION = getattr(_disc_mod, "__VERSION__", "OLD")
    _has_norm = hasattr(_disc_mod, "_normalize_post")
    # v4.9.3.3 FIX: any 4.x with _normalize_post is NEW. Old check used a hardcoded tuple and operator precedence made it fragile.
    # OLD is now ONLY when import failed (VERSION = "OLD - import failed") or no _normalize_post and no 4.x version.
    DISCOVERY_IS_NEW = bool(_has_norm and str(DISCOVERY_VERSION).strip().startswith("4."))
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
        # Fallback heuristic when scoring/selection.py import fails - keyword check, not always Skip
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
            # title | url - but no URL found, keep title part as seen key
            seen.add(line.split("|")[0].strip())
        else: seen.add(line)
    return seen

def _fb_run_discovery(seen_urls=None, search_terms=None):
    """Fallback if discovery/__init__.py import fails - same normalisation/pruning as v4.4"""
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


# --- Grounding (v4.9.3.3) - loads from grounding/ folder in same repo, fail-open ---
def _load_grounding():
    """Load grounding files from grounding/ folder next to app.py. Returns dict, empty if missing."""
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
    """Pick 1 category file based on post title+snippet+deep text. Returns (key, label, text)."""
    try:
        hay = ((post.get("title") or "") + " " + (post.get("snippet") or "") + " " + (post.get("_deep_text") or "")).lower()
        # Category 2 signals: passive / lecture / slide / webinar / e-learning
        c2 = sum(1 for k in ["passive", "lecture", "slide", "webinar", "e-learning", "elearning", "training module", "course"] if k in hay)
        # Category 3 signals: ROI / budget / executive / transformation / adoption / debrief / facilitat
        c3 = sum(1 for k in ["roi", "budget", "executive", "transformation", "change management", "adoption", "debrief", "facilitat", "6 pillar"] if k in hay)
        # Category 1 signals: automation / ai tool / reskill / upskill / hybrid / human edge
        c1 = sum(1 for k in ["automation", "automate", "ai tool", "reskill", "upskill", "hybrid", "human edge", "workforce"] if k in hay)
        if c2 > c1 and c2 >= c3:
            return ("cat2", "Category 2 - Passive L&D", grounding.get("cat2",""))
        if c3 > c1 and c3 >= c2:
            return ("cat3", "Category 3 - ROI & Architecture", grounding.get("cat3",""))
        return ("cat1", "Category 1 - Hybrid Intelligence Era", grounding.get("cat1",""))
    except Exception:
        return ("cat1", "Category 1 - Hybrid Intelligence Era", grounding.get("cat1",""))

def _build_grounding_prompt(post, grounding):
    """Build grounding text for draft prompt: core + 1 category + voice. Returns (grounding_text, label)."""
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

# ================= SIDEBAR - COMPACT v4.9.3.3 =================
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
# NEW: Download - separate from Upload above. Does not change Upload / filtering.
# Shows only after Discovery. Downloads ALL 75 raw (kept 23 + pruned 50) + old seen, so next run skips all of them.
if st.session_state.get("discovered") or st.session_state.get("discovery_raw_links"):
    _all_seen = set(seen_urls) | set(st.session_state.get("discovery_raw_links", [])) | {p.get("link", "") for p in st.session_state.get("discovered", []) if p.get("link")}
    _seen_txt = "\n".join(sorted(_all_seen))
    st.sidebar.download_button("⬇ Download seen_posts.txt (all 75 raw)", _seen_txt, file_name="seen_posts.txt", mime="text/plain", key="download_seen_v493")

# 2. KEYS + DISCOVERY - one line each
st.sidebar.caption(f"Gemini: {'OK' if os.getenv('GEMINI_API_KEY') else 'MISSING'} | Grok: {'OK' if os.getenv('GROK_API_KEY') else 'MISSING'} | Model: {GEMINI_MODEL}")
# v4.9.3.3: show Serper status so you can see it is being used
st.sidebar.caption(f"Search: {SEARCH_PROVIDER} | Serper key: {'OK' if SERPER_API_KEY else 'not set - using DuckDuckGo'}")
st.sidebar.caption(f"Discovery: {DISCOVERY_VERSION}")
if not DISCOVERY_IS_NEW:
    if _DISCOVERY_ERR:
        st.sidebar.error("Discovery import failed - app uses fallback.")
        with st.sidebar.expander("Tap to see discovery error - copy it"):
            st.sidebar.code(_DISCOVERY_ERR_FULL[:2000])
            st.sidebar.caption("Copy the text above and paste it here. Also check GitHub > discovery folder has exactly: __init__.py, medium.py, web_search.py, youtube.py")
    else:
        st.sidebar.error(f"Discovery OLD ({DISCOVERY_VERSION}). Check GitHub > discovery folder has __init__.py (with __ on both sides, NOT init.py) + medium.py + web_search.py + youtube.py + deep.py. If __init__.py is named init.py, rename it.")

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
# --- Top bar (v4.9.3.3) - title left, Kill button right ---
if "kill_requested" not in st.session_state:
    st.session_state.kill_requested = False
if "current_task" not in st.session_state:
    st.session_state.current_task = ""
_top_left, _top_right = st.columns([5, 1])
with _top_left:
    st.title("Leadership AI Daily Digest")
with _top_right:
    st.write("")  # align
    if st.button("⏹ Stop task", key="kill_btn_top_v492", help="Stop the current Discovery / Assess / Draft task. It will stop after the current post (max 30s) because AI calls now have timeouts."):
        st.session_state.kill_requested = True
        st.warning("Stop requested - current task will stop after current post (max 30s). If it does not stop, Reboot from Manage app.")
if st.session_state.kill_requested:
    st.warning(f"Stop requested for: {st.session_state.current_task or 'current task'}. Next post will abort. Click a task button again to clear this and start fresh.")
    # Clear on next task start - tasks set kill_requested=False at start

def _check_kill():
    """Raise if user pressed Stop. Checked between posts, not mid-call (calls have 30s timeout)."""
    if st.session_state.get("kill_requested"):
        raise InterruptedError("Stopped by user (Stop button)")

def _clear_kill(task_name):
    st.session_state.kill_requested = False
    st.session_state.current_task = task_name
st.write("Step 1: Run Discovery (0 Gemini calls) -> Assess (max 12 Gemini calls, rest heuristic) -> Step 2: Review drafts.")
# --- Step-wise UI (v4.9.3.3) - only current step is expanded ---
_has_discovered = bool(st.session_state.get("discovered"))
_has_assessed = bool(st.session_state.get("assessed"))
if _has_discovered and _has_assessed:
    _current_step = "draft"
elif _has_discovered:
    _current_step = "assess"
else:
    _current_step = "discovery"
st.caption(f"Current step: {_current_step.upper()} | Discovery → Assess → Draft. Previous steps are collapsed below.")
_show_discovery = False  # FIX v4.9.3.3: ensure defined
if _current_step != "discovery":
    with st.expander(f"Step 1 - Discovery (done - {len(st.session_state.get('discovered',[]))} posts) - tap to re-run"):
        st.caption("Re-running Discovery replaces the current list. Your search terms are below.")
        _show_discovery = True
else:
    st.header("Step 1 - Discovery")
    _show_discovery = True
# Discovery body is shown when _show_discovery is True (always True for now, but Assess/Draft are gated below)
if _show_discovery:
    st.subheader("Step 1 - Discovery")
    st.caption(f"Search provider: {SEARCH_PROVIDER} - Serper key: {'OK' if SERPER_API_KEY else 'not set'} | 0 Gemini calls for Discovery")
# --- Search terms editor (v4.9.3.3) - edit before Discovery, no config.py edit needed ---
st.subheader("Search terms - edit before Discovery")
st.caption("One term per line. Discovery searches each term. Edit / add / delete here for this run. To make it permanent, also update SEARCH_TERMS in config.py on GitHub.")
try:
    _default_terms = "\n".join(SEARCH_TERMS)
except Exception:
    _default_terms = "corporate upskilling AI\nAI upskilling program\nL&D AI training\nreskilling workforce AI"
if "search_terms_text_v491" not in st.session_state:
    st.session_state.search_terms_text_v491 = _default_terms
search_terms_text = st.text_area("Search terms (one per line)", value=st.session_state.search_terms_text_v491, height=180, key="search_terms_editor_v491")
# Keep session state in sync (text_area with key already does, but save parsed)
_parsed_terms = [l.strip() for l in (search_terms_text or "").splitlines() if l.strip()]
# Dedupe preserving order
_seen_q = set(); _parsed_dedup = []
for _q in _parsed_terms:
    if _q not in _seen_q:
        _seen_q.add(_q); _parsed_dedup.append(_q)
_parsed_terms = _parsed_dedup
st.caption(f"Using {_parsed_terms.__len__()} terms for this Discovery run. {', '.join(_parsed_terms[:3])}{' ...' if len(_parsed_terms) > 3 else ''}")
col_reset, col_info = st.columns([1, 3])
with col_reset:
    if st.button("Reset to defaults", key="reset_terms_btn_v491"):
        st.session_state.search_terms_text_v491 = _default_terms
        st.rerun()
with col_info:
    st.caption("Tip: add site:linkedin.com / site:x.com / site:threads.net to a term to force social results. Remove a term to skip it for this run.")
if not _parsed_terms:
    st.warning("No search terms - add at least 1 term or click Reset to defaults.")
if st.button("Run Discovery", key="run_discovery_btn_v472"):
    _clear_kill("Discovery")
    _disc_status = st.empty()
    _disc_prog = st.progress(0)
    _disc_status.info("Discovery: Step 1 keyword search (0 Gemini calls) - searching 8 terms...")
    # Use real discovery if available, else fallback
    if run_discovery_with_stats is not None:
        try:
            pruned, stats = run_discovery_with_stats(seen_urls=seen_urls, search_terms=_parsed_terms, progress_cb=lambda done, total: (_disc_prog.progress(min(1.0, done/total)) if total else None, _disc_status.info(f'Discovery: Step 2 Deep - checking body {done}/{total} (max 60s total, 6s per page) - weeding out title-matches where body does not fit...')))
            _log(f"Discovery: raw={stats.get('raw','?')} invalid_skipped={stats.get('invalid_skipped',0)} seen_filtered={stats.get('seen_filtered',0)} deduped={stats.get('deduped','?')} social={stats.get('social','?')} web_pruned={stats.get('web_pruned',0)} kept={stats.get('kept_for_assessment', len(pruned))} fallback={stats.get('fallback', False)}")
            st.session_state.discovered = pruned or []
            st.session_state.discovery_raw_links = stats.get("raw_links", [])
            st.session_state.assessed = []
            _disc_prog.progress(1.0)
            _disc_status.success("Discovery done.")
            st.success(f"Discovery Step 1: {stats.get('raw','?')} raw -> {len(pruned) + stats.get('deep_weeded',0)} kept by title. Step 2 Deep: checked {stats.get('deep_checked',0)}, weeded out {stats.get('deep_weeded',0)} (title matched but body did not fit), kept {len(pruned)} for assessment. Seen filtered: {stats.get('seen_filtered',0)}. Invalid skipped: {stats.get('invalid_skipped',0)}. Web articles pruned: {stats.get('web_pruned',0)}. Social threads: {stats.get('social','?')}. Per-source: {stats.get('per_source', {})}")
            # Show weeded titles (Step 2)
            if stats.get('deep_weeded',0):
                with st.expander(f"Deep Step 2 weeded out {stats.get('deep_weeded',0)} (title matched, body did not fit) - tap to see"):
                    for w in stats.get('deep_weeded_posts',[]):
                        st.write(f"- {w.get('title','')} | {w.get('reason','')}")
                        st.caption(w.get('link',''))
        except Exception as e:
        st.warning(f"Real discovery failed ({e}) - using fallback discovery.")
        import traceback as _tb
        with st.expander("Show discovery error (copy this)"):
            st.code(_tb.format_exc()[:3000])
            pruned, stats = _fb_run_discovery(seen_urls=seen_urls, search_terms=_parsed_terms)
            st.session_state.discovered = pruned or []
            st.session_state.assessed = []
            st.success(f"[SAFE FALLBACK USED] Discovery returned {stats.get('raw','?')} raw / pruned to {len(pruned)}. Seen filtered: {stats.get('seen_filtered',0)}.")
    else:
        st.warning("Discovery import failed - using fallback discovery (see sidebar error).")
        pruned, stats = _fb_run_discovery(seen_urls=seen_urls, search_terms=_parsed_terms)
        st.session_state.discovered = pruned or []
        st.session_state.assessed = []
        st.success(f"[SAFE FALLBACK USED] Discovery returned {stats.get('raw','?')} raw / pruned to {len(pruned)}. Seen filtered: {stats.get('seen_filtered',0)}.")

# v4.9.3.3 FIX: _has_discovered / _current_step were computed BEFORE Discovery ran, so on the run where Discovery succeeded
# they were still False / "discovery" and Assess showed "Complete Step 1 first" even though Discovery just finished.
# Recompute them here, after Discovery handler, before Assess gating.
_has_discovered = bool(st.session_state.get("discovered"))
_has_assessed = bool(st.session_state.get("assessed"))
if _has_discovered and _has_assessed:
    _current_step = "draft"
elif _has_discovered:
    _current_step = "assess"
else:
    _current_step = "discovery"
if st.session_state.discovered:
    st.write(f"Discovered: {len(st.session_state.discovered)} ready for Assess. Discovery uses 0 Gemini calls.")

# --- Assess gated (v4.9.3.3 FIX) - _show_assess must be defined in ALL branches ---
_show_assess = False  # FIX v4.9.3.3: was undefined when on Step 1 with no Discovery yet -> NameError line 395
if _current_step == "discovery" and not _has_discovered:
    st.info("Step 2 - Assess: Complete Step 1 Discovery first. Assess is hidden until Discovery is done.")
    _show_assess = False
elif _current_step != "assess" and _has_assessed:
    with st.expander(f"Step 2 - Assess (done - {len(st.session_state.get('assessed',[]))} assessed) - tap to re-assess"):
        st.caption("Re-assessing replaces the current list.")
        _show_assess = True
else:
    st.header("Step 2 - Assess")
    _show_assess = True
if _show_assess and st.button("Assess posts (Gemini: max 12, rest heuristic)", key="assess_btn_v472"):
    _clear_kill("Assess")
    _assess_status = st.empty()
    _assess_prog = st.progress(0)
    _assess_status.info("Assess: starting - max 12 Gemini/Grok calls, rest heuristic. Each call max 30s (Gemini) / 20s (Grok).")
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
        _assess_total = len(posts)
        _assess_done = 0
        # Grok fallback client - ready even if Gemini is out (separate quota)
        grok_client_for_assess = None
        if GrokClient is not None:
            try:
                _gc = GrokClient(api_key=os.getenv("GROK_API_KEY", ""), model=GROK_MODEL)
                if _gc.is_ready():
                    grok_client_for_assess = _gc
            except Exception:
                grok_client_for_assess = None
        for p in posts:
            # v4.9.3.3: Kill check + progress - checked between posts
            try:
                _check_kill()
            except InterruptedError:
                _assess_status.warning("Assess stopped by user. Keeping posts assessed so far.")
                st.session_state.assessed = assessed
                break
            _assess_done += 1
            _assess_prog.progress(min(1.0, _assess_done / max(1, _assess_total)))
            _assess_status.info(f"Assess: { _assess_done}/{_assess_total} - {str(p.get('title',''))[:60]}... (max 30s per call)")
            if id(p) in gemini_ids and gclient is not None and not quota_hit:
                try:
                    data = gclient.generate(f"Assess this post for Leadership+AI digest. Return ONLY valid JSON: {{\"relevance\":0-100,\"conversation\":0-100,\"recency\":0-100,\"theme\":\"book theme or other\",\"sensitive\":true/false,\"is_breaking\":true/false,\"reason\":\"short\"}}. Title: {p.get('title','')[:500]} Snippet: {p.get('snippet','')[:800]} Deep body (first 2500 chars): {p.get('_deep_text','')[:2500]} Platform: {p.get('platform','')}")
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
            # --- GROK FALLBACK FOR ASSESS (v4.9.3.3) ---
            # If Gemini did not assess this post (quota out / 503 / no budget), try Grok before heuristic.
            # Grok has its own quota, so it works when Gemini is out.
            _grok_done = False
            if grok_client_for_assess is not None and (quota_hit or id(p) not in gemini_ids or gclient is None):
                try:
                    _gdata = grok_client_for_assess.generate(f"Assess this post for Leadership+AI digest. Return ONLY valid JSON: {{\"relevance\":0-100,\"conversation\":0-100,\"recency\":0-100,\"theme\":\"book theme or other\",\"sensitive\":true/false,\"is_breaking\":true/false,\"reason\":\"short\"}}. Title: {p.get('title','')[:500]} Snippet: {p.get('snippet','')[:800]} Deep body (first 2500 chars): {p.get('_deep_text','')[:2500]} Platform: {p.get('platform','')}")
                    import json as _json2
                    _t2 = re.sub(r"^```(?:json)?\s*", "", _gdata.strip()); _t2 = re.sub(r"\s*```$", "", _t2)
                    try:
                        _d2 = _json2.loads(_t2)
                    except Exception:
                        _m2 = re.search(r"\{.*\}", _gdata, re.S)
                        _d2 = _json2.loads(_m2.group(0)) if _m2 else {}
                    _rel = int(_d2.get("relevance", 50)); _conv = int(_d2.get("conversation", 50)); _rec = int(_d2.get("recency", 70))
                    _promo = round(_rel*0.30 + _conv*0.35 + _rec*0.15 + 20)
                    _opp = round((_rel*0.40 + _conv*0.35 + _rec*0.25)/10, 1)
                    _theme = _d2.get("theme", "other") or "other"
                    if _d2.get("sensitive"): _dec = "D_SENSITIVE"
                    elif _d2.get("is_breaking"): _dec = "C_WAIT"
                    elif _promo >= 80: _dec = "A_PROMOTE"
                    elif _promo >= 60: _dec = "B_ENGAGE"
                    else: _dec = "D_SKIP"
                    assessed.append({**p, "decision": _dec, "promo": _promo, "opp": _opp, "theme": _theme, "reason": f"Grok Assess (Gemini out) - {str(_d2.get('reason','Grok'))[:150]}"})
                    _grok_done = True
                    continue
                except Exception as _ge:
                    # Grok failed too - fall through to heuristic, do not crash Assess
                    pass
            if _grok_done:
                continue
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

# --- Draft gated (v4.9.3.3) - only main when Assess is done ---
if not _has_assessed:
    st.info("Step 3 - Review drafts: Complete Assess first. Drafts are hidden until Assess is done.")
else:
    st.header("Step 3 - Review drafts (was Step 2)")
if not st.session_state.assessed:
    st.info("Run Discovery, then Assess posts.")
else:
    view = st.radio("Show", ["Promote only", "Recommended only (Promote + Engage)", "All", "Skipped / Wait only"], horizontal=True, key="view_radio_v472")
    filtered = st.session_state.assessed
    if view == "Promote only":
        filtered = [x for x in filtered if x.get("decision") == "A_PROMOTE"]
    elif view == "Recommended only (Promote + Engage)":
        filtered = [x for x in filtered if x.get("decision") in ("A_PROMOTE","B_ENGAGE")]
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
            if post.get("_deep_reason"):
                st.caption(f"Deep check: {post.get('_deep_reason')} | Source: {post.get('_deep_source')} | Body length: {post.get('_deep_len',0)} chars")
            if post.get("decision") == "D_SENSITIVE":
                st.warning("Sensitive - drafting blocked.")
            else:
                key = f"draft_{idx}_{str(post.get('link',''))[:30]}_v472"
                # Template-only instant button (v4.9.3.3) - no AI call, never hangs
                if st.button("Generate template draft only (no AI, instant)", key=f"{key}_template"):
                    _tmpl = format_draft(template_draft(post))
                    st.subheader("Template draft (no AI)")
                    st.caption("Instant - no Gemini / Grok call, so it never hangs.")
                    st.write(_tmpl)
                if st.button("Generate draft anyway for this post", key=key):
                    _clear_kill("Draft")
                    _draft_status = st.empty()
                    _draft_status.info("Draft: trying Gemini (max 30s) - if quota out, Grok (max 20s) - if both fail, template instantly.")
                    usage2 = get_usage(GEMINI_MODEL)
                    if usage2["remaining"] <= 0:
                        st.warning(f"Gemini quota out ({usage2['used']}/{usage2['limit']} used). Trying Grok directly as fallback generator (separate quota).")
                        # --- GROK FALLBACK FOR DRAFT (v4.9.3.3) ---
                        draft_a = None
                        try:
                            if GrokClient is not None:
                                _gdk = GrokClient(api_key=os.getenv("GROK_API_KEY", ""), model=GROK_MODEL)
                                if _gdk.is_ready():
                                    _gd = _gdk.generate(f"You are drafting a comment grounded ONLY in this book grounding - do not invent new data, paraphrase, do not copy verbatim. Grounding: {_build_grounding_prompt(post, _load_grounding())[0]} | Grounding category used: {_build_grounding_prompt(post, _load_grounding())[1]}. Write ONE comment in CEA structure: Compliment (1 sentence) - Expand (1-2 sentences, use ONE data point from grounding if it fits) - Ask (1 open question). Max 70 words. Plain text. Post: {post.get('title','')} {post.get('snippet','')[:1200]} Deep body: {post.get('_deep_text','')[:800]}")
                                    if _gd:
                                        draft_a = format_draft(_gd)
                                        st.info("Option A - Grok fallback (Gemini quota out, single-engine - no dual review)")
                                else:
                                    raise Exception(_gdk.init_error)
                            else:
                                raise Exception("GrokClient not available")
                        except Exception as _gde:
                            st.warning(f"Grok fallback also failed ({_gde}) - using template draft.")
                            draft_a = None
                        if not draft_a:
                            draft_a = format_draft(template_draft(post))
                    else:
                        st.info(f"Draft needs 1 Gemini call. You have {usage2['remaining']} left.")
                        draft_a = None
                        try:
                            if GeminiClient is not None:
                                g = GeminiClient(api_key=os.getenv("GEMINI_API_KEY",""), model=GEMINI_MODEL)
                                if g.is_ready():
                                    draft_a = g.generate(f"You are drafting a comment grounded ONLY in this book grounding - do not invent new data, paraphrase, do not copy verbatim. Grounding: {_build_grounding_prompt(post, _load_grounding())[0]} | Grounding category used: {_build_grounding_prompt(post, _load_grounding())[1]}. Write ONE comment in CEA structure: Compliment (1 sentence) - Expand (1-2 sentences, use ONE data point from grounding if it fits) - Ask (1 open question). Max 70 words. Plain text. Post: {post.get('title','')} {post.get('snippet','')[:1200]} Deep body: {post.get('_deep_text','')[:800]}")
                                else: raise GeminiInitError(g.init_error)
                            else: raise GeminiInitError("GeminiClient not available")
                        except GeminiQuotaExceeded as qe:
                            st.warning(f"{qe} Trying Grok fallback.")
                            # --- GROK FALLBACK AFTER GEMINI FAIL (v4.9.3.3) ---
                            try:
                                if GrokClient is not None:
                                    _gdk2 = GrokClient(api_key=os.getenv("GROK_API_KEY", ""), model=GROK_MODEL)
                                    if _gdk2.is_ready():
                                        _gd2 = _gdk2.generate(f"You are drafting a comment grounded ONLY in this book grounding - do not invent new data, paraphrase, do not copy verbatim. Grounding: {_build_grounding_prompt(post, _load_grounding())[0]} | Grounding category used: {_build_grounding_prompt(post, _load_grounding())[1]}. Write ONE comment in CEA structure: Compliment (1 sentence) - Expand (1-2 sentences, use ONE data point from grounding if it fits) - Ask (1 open question). Max 70 words. Plain text. Post: {post.get('title','')} {post.get('snippet','')[:1200]} Deep body: {post.get('_deep_text','')[:800]}")
                                        draft_a = _gd2 if _gd2 else template_draft(post)
                                        st.info("Option A - Grok fallback (Gemini quota out)")
                                    else:
                                        draft_a = template_draft(post)
                                else:
                                    draft_a = template_draft(post)
                            except Exception:
                                draft_a = template_draft(post)
                        except Exception as e:
                            st.warning(f"Gemini failed ({e}) - using template draft."); draft_a = template_draft(post)
                        if not draft_a: draft_a = template_draft(post)
                        draft_a = format_draft(draft_a)
                    st.caption(f"Grounding used: {_build_grounding_prompt(post, _load_grounding())[1]} | Files: grounding/00_book_core.txt + selected category + 04_voice.txt")
                    st.subheader("Option A - Grounded draft (Gemini / Grok / Template)")
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

