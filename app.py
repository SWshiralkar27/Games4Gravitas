"""app.py — Leadership AI Digest v4.2 (UI only)
FIXES in v4.2:
1. Pruning: shows "Discovery X raw -> Y for assessment (Z web pruned)",
   Step 2 defaults to Recommended only, Skip list collapsed.
2. Quota: max 12 Gemini calls/run, rest heuristic (0 calls). On 429,
   banner with retry time, stop hammering, template drafts still copyable.
3. Gemini: never 2.0-flash, never old SDK (see gemini_client.py).
4. Formatting: every draft via drafting.formatting.format_draft
   (bold book, italics keywords, line break after every full stop).
5. Widgets: never value= + key= together. Init session_state once.
"""
import os
import time

import streamlit as st

from config import (
    BOOK_THEMES, GEMINI_MODEL, GROK_MODEL, MAX_GEMINI_CALLS_PER_RUN,
    SEARCH_PROVIDER, SEARCH_TERMS,
)

# --- Defensive imports: app must not crash if one helper is missing ---
try:
    from discovery import run_discovery_with_stats
except Exception as e:
    run_discovery_with_stats = None
    _DISCOVERY_ERR = e
else:
    _DISCOVERY_ERR = None

try:
    from gemini_client import GeminiClient, GeminiUnavailable, QuotaExceeded
except Exception as e:
    GeminiClient = None
    GeminiUnavailable = Exception
    QuotaExceeded = Exception
    _GEMINI_ERR = e
else:
    _GEMINI_ERR = None

try:
    from grok_client import GrokClient
except Exception:
    GrokClient = None

try:
    from drafting.formatting import format_draft
except Exception:
    def format_draft(x):
        return x or ""

try:
    from scoring.selection import heuristic_assess, select_for_gemini, template_draft
except Exception:
    def heuristic_assess(p):
        return {"decision": "D_SKIP", "promo": 0, "opp": 0.0, "theme": "other", "reason": "Heuristic unavailable."}
    def select_for_gemini(posts):
        return (posts or [])[:12]
    def template_draft(p, a=None):
        return format_draft("Template draft unavailable.")

st.set_page_config(page_title="Leadership AI Digest", layout="wide")
st.title("Leadership AI Daily Digest Generator")

# ---------- Sidebar: secrets status (no values) ----------
with st.sidebar:
    st.header("Status")
    st.write(f"Gemini Key {'✅' if os.getenv('GEMINI_API_KEY') else '❌'}")
    st.write(f"Grok Key {'✅' if os.getenv('GROK_API_KEY') else '❌'} {GROK_MODEL}")
    st.write(f"Search Provider {SEARCH_PROVIDER.upper()}")
    st.write(f"YouTube Key {'✅' if os.getenv('YOUTUBE_API_KEY') else '—'}")
    st.write(f"Gemini Model {GEMINI_MODEL}")
    st.checkbox("Dual-engine (Gemini + Grok review)", value=True, key="dual_engine")
    if GEMINI_MODEL != "gemini-3.8-flash":
        st.error("GEMINI_MODEL must be gemini-3.8-flash in Secrets. Fix + reboot.")
    if "quota_until" in st.session_state:
        st.warning(f"Gemini quota hit. Retry after: {st.session_state.get('quota_retry_text','~4h')}")

# ---------- Session state: init once, then key= only (no value= + key=) ----------
if "edited_search_terms" not in st.session_state:
    st.session_state.edited_search_terms = "\n".join(SEARCH_TERMS)
if "edited_book_themes" not in st.session_state:
    st.session_state.edited_book_themes = "\n".join(BOOK_THEMES)
if "posts" not in st.session_state:
    st.session_state.posts = []
if "assessed" not in st.session_state:
    st.session_state.assessed = []
if "last_run_log" not in st.session_state:
    st.session_state.last_run_log = []
if "quota_hit" not in st.session_state:
    st.session_state.quota_hit = False

def _reset_search():
    st.session_state.edited_search_terms = "\n".join(SEARCH_TERMS)
    st.session_state.edited_book_themes = "\n".join(BOOK_THEMES)

def _log(msg):
    st.session_state.last_run_log.append(msg)

# ---------- Step 1: Review search ----------
st.header("Step 1 — Review search")
st.text_area("Search keywords (one per line, this run only)", key="edited_search_terms")
st.text_area("Book themes (one per line, this run only)", key="edited_book_themes")
st.button("Reset search / themes", on_click=_reset_search)

search_terms = [l.strip() for l in st.session_state.edited_search_terms.splitlines() if l.strip()]
book_themes = [l.strip() for l in st.session_state.edited_book_themes.splitlines() if l.strip()]

if st.button("Run Discovery"):
    if run_discovery_with_stats is None:
        st.error(f"Discovery import failed: {_DISCOVERY_ERR}")
    else:
        with st.spinner("Discovering…"):
            pruned, stats = run_discovery_with_stats(search_terms=search_terms, book_themes=book_themes)
        st.session_state.posts = pruned
        st.session_state.assessed = []
        _log(f"Discovery: raw={stats.get('raw')} deduped={stats.get('deduped')} social={stats.get('social')} web_pruned={stats.get('web_pruned')} kept={stats.get('kept_for_assessment')}")
        # v4.2 banner — this is the pruning proof
        st.success(
            f"Discovery returned {stats.get('raw', 0)} raw posts before dedupe / pruned to "
            f"{stats.get('kept_for_assessment', 0)} for assessment. "
            f"Web articles pruned: {stats.get('web_pruned', 0)}. "
            f"Social threads: {stats.get('social', 0)}. Per-source: {stats.get('per_source', {})}"
        )
        if stats.get("social", 0) == 0:
            st.warning("No social threads found — only web articles. Broaden search terms (try 'AI leadership', 'leading teams with AI') or check Serper key. Web articles are auto-skipped, not assessed by Gemini.")

# ---------- Assess ----------
if st.session_state.posts and st.button("Assess posts (Gemini: max 12, rest heuristic)"):
    posts = st.session_state.posts
    to_gemini = select_for_gemini(posts)
    to_gemini_ids = {id(p) for p in to_gemini}
    _log(f"Assess: {len(posts)} posts, Gemini for {len(to_gemini)} (max {MAX_GEMINI_CALLS_PER_RUN}), rest heuristic.")
    gemini = None
    quota_hit = False
    if GeminiClient is not None and os.getenv("GEMINI_API_KEY"):
        try:
            gemini = GeminiClient()
        except Exception as e:
            _log(f"Gemini init failed: {e}")
            st.warning(f"Gemini init failed, using heuristic: {e}")
    assessed = []
    progress = st.progress(0)
    for i, p in enumerate(posts):
        # Auto-skip web: 0 API calls
        if p.get("_auto_skip"):
            h = heuristic_assess(p)
            assessed.append({**p, **h})
            progress.progress((i + 1) / max(1, len(posts)))
            continue
        # Gemini only for top N, and stop on quota
        if id(p) in to_gemini_ids and gemini is not None and not quota_hit and not st.session_state.quota_hit:
            try:
                a = gemini.analyse_post(p)
                # Map Gemini JSON -> decision (same thresholds as heuristic)
                promo = int(a.get("relevance", 50) * 0.30 + a.get("conversation", 50) * 0.35 + 20)
                if a.get("sensitive"):
                    dec, promo2 = "D_SENSITIVE", 0
                elif a.get("is_breaking"):
                    dec, promo2 = "C_WAIT", promo
                elif promo >= 80:
                    dec, promo2 = "A_PROMOTE", promo
                elif promo >= 60:
                    dec, promo2 = "B_ENGAGE", promo
                else:
                    dec, promo2 = "D_SKIP", promo
                assessed.append({**p, "decision": dec, "promo": promo2, "opp": round((a.get("relevance", 50) * 0.4 + a.get("conversation", 50) * 0.35 + a.get("recency", 70) * 0.25) / 10, 1), "theme": a.get("theme", "other"), "reason": a.get("reason", "Gemini assessment.")})
                time.sleep(3.0)
            except QuotaExceeded as qe:
                quota_hit = True
                st.session_state.quota_hit = True
                secs = getattr(qe, "retry_after_seconds", None)
                if secs:
                    hrs, rem = divmod(int(secs), 3600)
                    mins = rem // 60
                    st.session_state.quota_retry_text = f"{hrs}h{mins:02d}m"
                _log(f"QuotaExceeded: {qe}")
                st.error(f"Gemini quota exhausted (Free Tier 20/day). {qe} — Switching remaining posts to heuristic. Do NOT keep clicking Generate — use template drafts below or wait.")
                h = heuristic_assess(p)
                assessed.append({**p, **h})
            except Exception as e:
                _log(f"Gemini analyse failed for {p.get('title','')[:60]}: {e}")
                h = heuristic_assess(p)
                assessed.append({**p, **h})
        else:
            h = heuristic_assess(p)
            assessed.append({**p, **h})
        progress.progress((i + 1) / max(1, len(posts)))
    st.session_state.assessed = assessed
    # Theme cap: max 2 Promote per theme
    counts_theme = {}
    for a in assessed:
        if a.get("decision") == "A_PROMOTE":
            counts_theme[a.get("theme", "other")] = counts_theme.get(a.get("theme", "other"), 0) + 1
            if counts_theme[a.get("theme", "other")] > 2:
                a["decision"] = "B_ENGAGE"
                a["reason"] += " Theme cap: downgraded Promote -> Engage (max 2/theme)."
    _log(f"Assessed: {len(assessed)}")

# ---------- Counts ----------
if st.session_state.assessed:
    a_list = st.session_state.assessed
    def _c(d):
        return sum(1 for x in a_list if x.get("decision") == d)
    st.subheader(f"{len(a_list)} assessed: {_c('A_PROMOTE')} promote · {_c('B_ENGAGE')} engage · {_c('D_SENSITIVE')} sensitive · {_c('C_WAIT')} wait · {_c('D_SKIP')} skip")
    themes = sorted({x.get("theme", "other") for x in a_list})
    st.write(f"Themes: {len(themes)} | {', '.join(themes)}")

# ---------- Step 2: Review drafts ----------
st.header("Step 2 — Review drafts")
if not st.session_state.assessed:
    st.info("Run Discovery, then Assess posts.")
else:
    # Filter: default Recommended only — hides the huge Skip list (Q1)
    view = st.radio("Show", ["Recommended only (Promote + Engage)", "All", "Skipped / Wait only"], horizontal=True)
    platform_filter = st.selectbox("Platform", ["All"] + sorted({x.get("platform", "Web") for x in st.session_state.assessed}))
    text_filter = st.text_input("Filter by title / platform / link (e.g. type Medium)", "")
    filtered = st.session_state.assessed
    if view == "Recommended only (Promote + Engage)":
        filtered = [x for x in filtered if x.get("decision") in ("A_PROMOTE", "B_ENGAGE")]
    elif view == "Skipped / Wait only":
        filtered = [x for x in filtered if x.get("decision") in ("D_SKIP", "C_WAIT", "D_SENSITIVE")]
    if platform_filter != "All":
        filtered = [x for x in filtered if x.get("platform") == platform_filter]
    if text_filter.strip():
        q = text_filter.strip().lower()
        filtered = [x for x in filtered if q in (x.get("title", "") + x.get("platform", "") + x.get("link", "")).lower()]
    st.write(f"Showing {len(filtered)} of {len(st.session_state.assessed)} after filter")

    for idx, post in enumerate(filtered):
        title = post.get("title", "Untitled")[:120]
        with st.expander(f"{post.get('platform','Web')} - {title} | Suggested: {post.get('decision')} | Promo: {post.get('promo')} | Opp: {post.get('opp')} | Why: {post.get('reason','')[:120]}"):
            st.markdown(f"Link: [{post.get('link','')[:80]}]({post.get('link','')})")
            st.write(f"**Platform label:** {post.get('platform')}")
            st.write(f"**Why suggested {post.get('decision')}:** {post.get('reason')}")
            st.write(f"**Snippet:** {post.get('snippet','')[:400]}")
            # Generate draft anyway: allowed for Skip + Wait, blocked for Sensitive
            if post.get("decision") == "D_SENSITIVE":
                st.warning("Sensitive — drafting blocked.")
            else:
                key = f"draft_{idx}_{post.get('link','')[:30]}"
                if st.button("Generate draft anyway for this post", key=key):
                    st.info("generate_drafts: trying Gemini…")
                    draft_a = None
                    grok_err = ""
                    try:
                        if GeminiClient is not None and not st.session_state.quota_hit:
                            g = GeminiClient()
                            draft_a = g.generate_draft(post)
                        else:
                            raise QuotaExceeded("Quota hit — using template draft.", None)
                    except QuotaExceeded as qe:
                        st.warning(f"Gemini quota hit — using template draft (still copyable, formatted). {qe}")
                        draft_a = template_draft(post)
                    except Exception as e:
                        st.warning(f"Gemini failed ({e}) — using template draft.")
                        draft_a = template_draft(post)
                    if not draft_a:
                        draft_a = template_draft(post)
                    # v4.2 formatting applied to every draft
                    draft_a = format_draft(draft_a)
                    st.subheader("Option A — Gemini / Template (formatted)")
                    st.markdown(draft_a)
                    st.code(draft_a, language="markdown")
                    st.text_area("Copy Option A", value=draft_a, key=f"copy_a_{idx}", height=150)
                    st.download_button("Download draft as .txt", data=draft_a, file_name="draft.txt", mime="text/plain", key=f"dl_{idx}")
                    # Grok review only the recommended draft
                    if st.session_state.get("dual_engine") and GrokClient is not None and os.getenv("GROK_API_KEY"):
                        try:
                            grok = GrokClient()
                            draft_b = grok.review_draft(post, draft_a)
                            draft_b = format_draft(draft_b)
                            st.subheader("Option B — Grok reviewed (formatted)")
                            st.markdown(draft_b)
                            st.code(draft_b, language="markdown")
                            st.text_area("Copy Option B", value=draft_b, key=f"copy_b_{idx}", height=150)
                        except Exception as e:
                            grok_err = str(e)
                            st.info(f"Grok review failed (real error): {grok_err}. Option A above is still usable.")
                    elif st.session_state.get("dual_engine"):
                        st.info("Grok key missing — Option A only.")

# ---------- Debug / Last Run ----------
with st.expander("Debug"):
    if st.button("Test Gemini now"):
        try:
            if GeminiClient is None:
                st.error(f"Gemini import failed: {_GEMINI_ERR}")
            else:
                c = GeminiClient()
                st.success(f"Gemini OK ({c.model}): {c.test_connection()}")
        except QuotaExceeded as qe:
            st.error(f"QuotaExceeded: {qe} Retry in {getattr(qe, 'retry_after_seconds', '?')}s")
        except Exception as e:
            st.error(f"Gemini failed (real error): {e}")
    st.write(f"GEMINI_MODEL in use: {GEMINI_MODEL} (must be gemini-3.8-flash)")
    st.write("If Secrets still say gemini-2.0-flash, change it to gemini-3.8-flash and reboot Streamlit.")

st.subheader("Last Run log")
st.code("\n".join(st.session_state.last_run_log) if st.session_state.last_run_log else "No runs yet.")
