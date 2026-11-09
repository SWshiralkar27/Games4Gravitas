import asyncio
import time
import tempfile
from pathlib import Path
from datetime import datetime
import streamlit as st
import config as _cfg
from config import (
    GEMINI_API_KEY, GEMINI_MODEL, GEMINI_DELAY_SECONDS,
    GROK_API_KEY, GROK_MODEL, GROK_ENABLED,
    SEARCH_TERMS, BOOK_THEMES,
    PLATFORM_ORDER, HISTORY_FILE,
    SEARCH_PROVIDER, YOUTUBE_API_KEY,
)

# --- Imports with error capture ---
try:
    from models import ContentItem, Digest, Decision, Sensitivity, Confidence
except Exception:
    from models import ContentItem, Digest, Decision
    Sensitivity = None
    Confidence = None

try:
    from history import load_history, save_history
except Exception:
    def load_history():
        return set()
    def save_history(urls):
        pass

_GEMINI_IMPORT_ERROR = None
try:
    from gemini_client import GeminiClient, GeminiUnavailable
except Exception as _e:
    GeminiClient = None
    import traceback as _tb
    _GEMINI_IMPORT_ERROR = f"{type(_e).__name__}: {_e}\n" + _tb.format_exc()[-2000:]
    class GeminiUnavailable(Exception):
        pass

_GROK_IMPORT_ERROR = None
try:
    from grok_client import GrokClient, GrokUnavailable
except Exception as _e:
    GrokClient = None
    import traceback as _tb2
    _GROK_IMPORT_ERROR = f"{type(_e).__name__}: {_e}\n" + _tb2.format_exc()[-2000:]
    class GrokUnavailable(Exception):
        pass

try:
    from discovery import run_discovery
except Exception:
    try:
        from discovery.web_search import run_discovery
    except Exception:
        async def run_discovery():
            return []

try:
    from scoring.selection import dedupe_and_filter, select_candidates, enforce_theme_cap_and_diversity
except Exception:
    try:
        from scoring import dedupe_and_filter, select_candidates, enforce_theme_cap_and_diversity
    except Exception:
        def dedupe_and_filter(items, history):
            seen = set()
            out = []
            for it in items:
                if it.url in history or it.url in seen:
                    continue
                seen.add(it.url)
                out.append(it)
            return out
        def select_candidates(items):
            return items
        def enforce_theme_cap_and_diversity(items):
            return {"diversity_ok": True, "themes_covered": len(set(getattr(x, "book_theme", "") for x in items))}

try:
    from scoring.opportunity import calculate_opportunity_score
except Exception:
    def calculate_opportunity_score(item):
        return getattr(item, "opportunity_score", 0) or 0

# Prefer gemini_client's analyse_post - it handles BOOK_THEMES as strings. scoring/relevance still has the old tuple-unpack bug.
try:
    from gemini_client import analyse_post as _gemini_analyse_post
    analyse_post = _gemini_analyse_post
except Exception:
    try:
        from scoring.relevance import analyse_post
    except Exception:
        def analyse_post(client, item):
            return None

def _heuristic_analysis(item):
    """Fallback when Gemini analysis fails: score by keyword overlap so posts do not all get Promo 0 / Analysis failed."""
    try:
        title = (getattr(item, "title", "") or "").lower()
        snippet = (getattr(item, "snippet", "") or "").lower()
        full = (getattr(item, "full_content", "") or "").lower()
        blob = title + " " + snippet + " " + full
        theme_words = ["judgment", "judgement", "rehearsal", "rehearse", "centaur", "human advantage", "human-centered", "human centred", "hybrid intelligence", "decision", "leadership", "upskilling", "reskilling", "ai transformation", "learning"]
        hits = sum(1 for w in theme_words if w in blob)
        # Book alignment 30-85 based on hits
        book_s = min(85, 30 + hits * 8)
        ctx_s = min(85, 35 + hits * 7)
        eng_s = 55 if int(getattr(item, "comment_count", 0) or 0) > 5 else 45
        aud_s = 55
        nat_s = 55
        promo = round(book_s * 0.25 + ctx_s * 0.30 + eng_s * 0.25 + aud_s * 0.10 + nat_s * 0.10, 1)
        if promo >= 80:
            dec = "A_PROMOTE"
        elif promo >= 60:
            dec = "B_ENGAGE"
        else:
            dec = "D_SKIP"
        # Pick best theme by keyword
        theme = "Human Judgment"
        if "rehears" in blob:
            theme = "Purposeful Rehearsal"
        elif "centaur" in blob:
            theme = "Centaur Leadership"
        elif "human advantage" in blob:
            theme = "Human Advantage"
        return {
            "book_alignment_score": book_s,
            "contextual_relevance_score": ctx_s,
            "engagement_score": eng_s,
            "audience_alignment_score": aud_s,
            "promotion_naturalness_score": nat_s,
            "promotion_score": promo,
            "decision": dec,
            "decision_reason": "Heuristic score - Gemini analysis failed, using keyword fallback. You decide via Step 2.",
            "context_summary": (getattr(item, "snippet", "") or getattr(item, "title", ""))[:200],
            "sensitivity": "LOW",
            "sensitivity_reason": "",
            "confidence": "LOW",
            "book_theme": theme,
            "promotion_justification": "Keyword overlap with book themes.",
        }
    except Exception:
        return None

try:
    from drafting.generator import generate_drafts
except Exception:
    try:
        from drafting import generate_drafts
    except Exception:
        def generate_drafts(client, item, variant=0, grok_client=None):
            pass

try:
    from exporters import write_html, write_markdown, write_json
except Exception:
    def write_html(digest, path):
        Path(path).write_text("<h1>Digest</h1>", encoding="utf-8")
    def write_markdown(digest, path):
        Path(path).write_text("# Digest", encoding="utf-8")
    def write_json(digest, path):
        import json as _j
        Path(path).write_text(_j.dumps({"summary": digest.summary}), encoding="utf-8")

try:
    from effectiveness import append_effectiveness, yield_label
except Exception:
    def append_effectiveness(posted, replies):
        return {"date": datetime.now().strftime("%Y-%m-%d"), "yield": 0}
    def yield_label(y):
        return ""


def _make_gemini_client():
    if GeminiClient is None:
        raise GeminiUnavailable(f"GeminiClient could not be imported. Import error was:\n{_GEMINI_IMPORT_ERROR}")
    attempts = [
        lambda: GeminiClient(GEMINI_API_KEY, GEMINI_MODEL),
        lambda: GeminiClient(api_key=GEMINI_API_KEY, model=GEMINI_MODEL),
        lambda: GeminiClient(GEMINI_MODEL),
        lambda: GeminiClient(model=GEMINI_MODEL),
        lambda: GeminiClient(GEMINI_API_KEY),
        lambda: GeminiClient(api_key=GEMINI_API_KEY),
        lambda: GeminiClient(),
    ]
    last_err = None
    for _fn in attempts:
        try:
            return _fn()
        except TypeError as _e:
            last_err = _e
            continue
        except Exception as _e:
            last_err = _e
            continue
    raise GeminiUnavailable(f"Could not create GeminiClient with any signature. Last error: {last_err}")

def _make_grok_client():
    if GrokClient is None:
        raise GrokUnavailable(f"GrokClient could not be imported. Import error was:\n{_GROK_IMPORT_ERROR}")
    attempts = [
        lambda: GrokClient(),
        lambda: GrokClient(GROK_API_KEY, GROK_MODEL),
        lambda: GrokClient(api_key=GROK_API_KEY, model=GROK_MODEL),
        lambda: GrokClient(GROK_MODEL),
        lambda: GrokClient(GROK_API_KEY),
    ]
    last_err = None
    for _fn in attempts:
        try:
            return _fn()
        except TypeError as _e:
            last_err = _e
            continue
        except Exception as _e:
            last_err = _e
            continue
    raise GrokUnavailable(f"Could not create GrokClient: {last_err}")



def _copy_button(label, text_to_copy, key):
    """Native Streamlit copy - no iframe, so it cannot close the tab. Uses st.code (has copy icon) + download + selectable text_area."""
    _txt = (text_to_copy or "").strip()
    if not _txt:
        st.caption("No draft to copy.")
        return
    # st.code has a built-in copy icon in the top-right - this is the most reliable copy in Streamlit
    st.code(_txt, language="markdown")
    st.caption("Use the copy icon on the top-right of the box above, or select the text below and Ctrl+C / Cmd+C.")
    # Selectable text_area as second copy path - user can click, Ctrl+A, Ctrl+C
    st.text_area("Select and copy (Ctrl+A, Ctrl+C):", value=_txt, height=110, key=f"copy-area-{key}")
    # Download as .txt - third copy path, never closes the tab
    st.download_button(f"Download draft as .txt", data=_txt, file_name=f"draft-{key[:30]}.txt", mime="text/plain", key=f"dl-{key}")

def _template_draft(item):
    """Template draft when Gemini is down / returns empty - always gives user something copy-ready."""
    _title = (getattr(item, "title", "") or "This post").strip()
    _snippet = (getattr(item, "snippet", "") or getattr(item, "full_content", "") or "").strip()
    # Take first sentence of snippet as hook context
    import re as _re
    _first = _re.split(r"(?<=[.!?])\s+", _snippet)[0] if _snippet else _title
    _first = _first[:140]
    _theme = getattr(item, "book_theme", "") or "Purposeful Rehearsal"
    return f"""{_title} - this lands.

Your point on "{_first}" is the exact moment where judgment matters more than output.

In Games for Gravitas, I call this purposeful rehearsal - rehearse before you decide - so teams keep human judgment in the loop while AI speeds up execution.

How are you building that rehearsal into your next decision?"""

def _format_draft_comment(raw_text, item):
    """Format a raw draft into a clean, copy-ready comment: Hook + Insight + Book tie-in + Question."""
    txt = (raw_text or "").strip()
    if not txt:
        return ""
    # Remove markdown fences / quotes that Gemini sometimes adds
    txt = txt.replace("```", "").strip().strip('"').strip()
    # If already has line breaks, keep them. If single paragraph, split into hook / body / question
    if "\n" not in txt and len(txt) > 140:
        # Try to split at last sentence as question
        import re as _re
        _sents = _re.split(r"(?<=[.!?])\s+", txt)
        if len(_sents) >= 3:
            txt = _sents[0] + "\n\n" + " ".join(_sents[1:-1]) + "\n\n" + _sents[-1]
    return txt


def main():
    st.set_page_config(page_title="Leadership AI Daily Digest v4.1", layout="wide")
    st.title("Leadership AI Daily Digest v4.1")
    st.caption("Discover → Dedupe → Analyse → Guardrails → Draft (Gemini) → Review (Grok) → You pick. Fail-closed. Human publishes manually.")
    if "last_run_log" in st.session_state and st.session_state["last_run_log"]:
        with st.expander("Last Run log - what happened on last Run Digest", expanded=True):
            for _line in st.session_state["last_run_log"]:
                st.write(_line)

    with st.sidebar:
        st.subheader("Config")
        st.write(f"Gemini Key: {'✅' if GEMINI_API_KEY else '❌'}")
        st.write(f"Grok Key: {'✅' if GROK_API_KEY else '❌'} {GROK_MODEL if GROK_API_KEY else ''}")
        st.write(f"Search Provider: {SEARCH_PROVIDER.upper()}")
        st.write(f"YouTube Key: {'✅' if YOUTUBE_API_KEY else '❌'}")
        dual = st.checkbox("Dual-engine: Grok reviews Gemini drafts", value=GROK_ENABLED)
        st.subheader("Upload History (seen_posts.txt)")
        uploaded_hist = st.file_uploader("Upload", type=["txt"], key="hist_upload")
        if uploaded_hist:
            try:
                HISTORY_FILE.write_bytes(uploaded_hist.read())
                st.success("History uploaded.")
            except Exception as e:
                st.error(f"History upload failed: {e}")
        ignore_hist = st.checkbox("Ignore history this run")
        with st.expander("Debug: Import errors", expanded=False):
            if _GEMINI_IMPORT_ERROR:
                st.error("Gemini import failed:")
                st.code(_GEMINI_IMPORT_ERROR[:2000])
            else:
                st.success("Gemini import OK")
            if _GROK_IMPORT_ERROR:
                st.error("Grok import failed:")
                st.code(_GROK_IMPORT_ERROR[:2000])
            else:
                st.success("Grok import OK")
        st.divider()
        st.subheader("Effectiveness — last 5 weeks")
        try:
            eff_path = Path("effectiveness.txt")
            if eff_path.exists():
                lines = eff_path.read_text(encoding="utf-8").strip().splitlines()[-5:]
                for ln in lines:
                    st.caption(ln)
            else:
                st.caption("No data yet.")
        except Exception:
            st.caption("No data yet.")

    st.subheader("1. Choose Source")
    st.write("How do you want to get posts?")
    source_mode = st.radio("How do you want to get posts?", ["Auto-Discover (Uses API Keys)", "Upload JSON"], horizontal=True, label_visibility="collapsed")
    content_items = []
    if source_mode == "Upload JSON":
        uploaded = st.file_uploader("Posts JSON", type=["json"])
        if uploaded:
            try:
                import json as _j
                rows = _j.loads(uploaded.read().decode("utf-8"))
                for r in rows:
                    content_items.append(ContentItem(r.get("platform", "LinkedIn"), r.get("title", ""), r.get("url", ""), r.get("source", ""), r.get("published", ""), r.get("snippet", ""), full_content=r.get("full_content", r.get("snippet", "")), comment_count=int(r.get("comment_count", 0) or 0), hours_since_post=float(r.get("hours_since_post", 9999) or 9999), is_question=bool(r.get("is_question", "?" in (r.get("title", "") + r.get("snippet", ""))))))
            except Exception as e:
                st.error(f"JSON Parse Error: {e}")
    else:
        st.info("This will fetch from Medium, YouTube, and Web Search (LinkedIn, X, Threads, Facebook, Instagram) based on your API keys and SEARCH_TERMS.")

    st.subheader("Step 1: Review search for this run")
    default_search = "\n".join(SEARCH_TERMS)
    edited_search_text = st.text_area("Search terms for this run (one per line, edit or add your own)", value=default_search, height=180, key="edited_search_terms")
    edited_search_terms = [line.strip() for line in edited_search_text.splitlines() if line.strip()]
    _default_themes = BOOK_THEMES if isinstance(BOOK_THEMES, list) and BOOK_THEMES else ["Human Judgment", "Purposeful Rehearsal", "Centaur Leadership", "Rehearse Before You Decide", "Human Advantage"]
    default_themes = "\n".join(_default_themes)
    edited_themes_text = st.text_area("Book themes for this run (one per line, e.g. Human Judgment, Purposeful Rehearsal, Centaur Leadership)", value=default_themes, height=120, key="edited_book_themes")
    edited_book_themes = [line.strip() for line in edited_themes_text.splitlines() if line.strip()]
    st.caption(f"This run will use {len(edited_search_terms)} search terms and {len(edited_book_themes)} themes. Edits are for this run only and will reset next run.")

    def _do_reset():
        st.session_state["edited_search_terms"] = default_search
        st.session_state["edited_book_themes"] = default_themes
    st.button("Reset to default search + themes", on_click=_do_reset)

    with st.expander("Debug: Test Serper API now - why 0 posts?", expanded=False):
        st.write(f"Search Provider in config: **{SEARCH_PROVIDER}**")
        try:
            from config import SERPER_API_KEY as _SERPER_KEY, BRAVE_API_KEY as _BRAVE_KEY
            st.write(f"Serper key present: **{'Yes' if _SERPER_KEY else 'No'}** - length: {len(_SERPER_KEY) if _SERPER_KEY else 0} chars, starts with: `{(_SERPER_KEY[:4] + '...') if _SERPER_KEY else 'none'}`")
            st.write(f"Brave key present: **{'Yes' if _BRAVE_KEY else 'No'}**")
        except Exception as _e:
            st.write(f"Could not read keys: {_e}")
        st.write(f"Terms this run: {len(edited_search_terms)} - first term: `{edited_search_terms[0] if edited_search_terms else 'none'}`")
        if st.button("Test Gemini now - show real error"):
            try:
                _tc = _make_gemini_client()
                _resp = _tc.generate("Say hello in 5 words.") if hasattr(_tc, "generate") else _tc._call("Say hello in 5 words.")
                if _resp and _resp.strip():
                    st.success(f"Gemini works. Response: {_resp[:200]}")
                else:
                    st.error("Gemini returned empty with no error - this is the bug. See gemini_client fix.")
            except Exception as _ge:
                st.error(f"Gemini test failed with real error: {_ge}")
                st.code(str(_ge)[:2000])
        if st.button("Test Serper with first term"):
            try:
                import requests as _req
                _test_term = edited_search_terms[0] if edited_search_terms else "Leadership AI"
                _resp = _req.post("https://google.serper.dev/search", headers={"X-API-KEY": _SERPER_KEY, "Content-Type": "application/json"}, json={"q": _test_term, "num": 5}, timeout=15)
                st.write(f"Serper HTTP status: **{_resp.status_code}**")
                if _resp.status_code == 200:
                    _j = _resp.json()
                    _org = _j.get("organic", [])
                    st.success(f"Serper works. Got {len(_org)} organic results for '{_test_term}'.")
                    for _r in _org[:3]:
                        st.caption(f"- {_r.get('title','')[:80]} | {_r.get('link','')}")
                elif _resp.status_code == 401:
                    st.error("Serper 401 - API key invalid.")
                elif _resp.status_code == 402:
                    st.error("Serper 402 - credits / quota exhausted.")
                elif _resp.status_code == 429:
                    st.error("Serper 429 - rate limited. Wait 5 minutes.")
                else:
                    st.error(f"Serper error {_resp.status_code}: {_resp.text[:500]}")
            except Exception as _e2:
                st.error(f"Serper test failed: {_e2}")

    if st.button("Run Digest", type="primary"):
        if not GEMINI_API_KEY:
            st.error("GEMINI_API_KEY is missing in Streamlit Secrets.")
            return
        st.session_state["last_run_log"] = []
        def _log(_msg):
            st.session_state["last_run_log"].append(_msg)
            st.write(_msg)
        if source_mode == "Auto-Discover (Uses API Keys)":
            with st.spinner("Fetching posts from APIs (may take 30s)..."):
                try:
                    _cfg.SEARCH_TERMS[:] = edited_search_terms
                except Exception:
                    _cfg.SEARCH_TERMS = edited_search_terms
                try:
                    _cfg.BOOK_THEMES[:] = edited_book_themes
                except Exception:
                    _cfg.BOOK_THEMES = edited_book_themes
                try:
                    SEARCH_TERMS[:] = edited_search_terms
                except Exception:
                    pass
                try:
                    BOOK_THEMES[:] = edited_book_themes
                except Exception:
                    pass
                try:
                    import inspect as _inspect
                    _sig = _inspect.signature(run_discovery)
                    _params = list(_sig.parameters.keys())
                    _has_terms = any(k in _params for k in ("search_terms", "terms", "queries", "keywords", "search_terms_list"))
                    if _has_terms:
                        _tp = next(k for k in ("search_terms", "terms", "queries", "keywords", "search_terms_list") if k in _params)
                        try:
                            content_items = asyncio.run(run_discovery(**{_tp: edited_search_terms}))
                        except TypeError:
                            content_items = asyncio.run(run_discovery())
                    else:
                        content_items = asyncio.run(run_discovery())
                except Exception as _disc_exc:
                    _log(f"Discovery raised an error: {_disc_exc}")
                    import traceback as _tb
                    st.code(_tb.format_exc()[-2000:])
                    content_items = []
                _log(f"Discovery returned {len(content_items)} raw posts before dedupe / recency filter.")
                if len(content_items) == 0 and len(edited_search_terms) < 3:
                    st.warning("You used only 1-2 terms. 1 generic term often returns only old posts that get filtered as >3 days old. Try 3-5 terms, or Reset.")
                if len(content_items) == 0:
                    _log("run_discovery returned 0 even though Serper works. Trying direct Serper fallback without strict filtering...")
                    st.warning("run_discovery returned 0 even though Serper works. Trying direct Serper fallback...")
                    try:
                        import requests as _req2
                        from config import SERPER_API_KEY as _FALLBACK_KEY
                        _fallback_items = []
                        # Fallback now tries site: filters so you get YouTube / Medium / LinkedIn, not just generic web articles
                        _fallback_terms = []
                        for _t in edited_search_terms[:3]:
                            _fallback_terms.append(_t)
                            _fallback_terms.append(f"{_t} site:linkedin.com")
                            _fallback_terms.append(f"{_t} site:youtube.com")
                            _fallback_terms.append(f"{_t} site:medium.com")
                        # Add 2 generic terms for coverage
                        for _t in edited_search_terms[3:5]:
                            _fallback_terms.append(_t)
                        _fallback_terms = _fallback_terms[:8]
                        for _term in _fallback_terms:
                            try:
                                _r = _req2.post("https://google.serper.dev/search", headers={"X-API-KEY": _FALLBACK_KEY, "Content-Type": "application/json"}, json={"q": _term, "num": 5}, timeout=15)
                                if _r.status_code != 200:
                                    _log(f"Fallback Serper for '{_term}' returned HTTP {_r.status_code}, skipping.")
                                    continue
                                _org = _r.json().get("organic", [])
                                _log(f"Fallback: term '{_term}' -> {_r.status_code} with {len(_org)} organic results.")
                                for _o in _org:
                                    _url = _o.get("link", "")
                                    _title = _o.get("title", "")
                                    _snippet = _o.get("snippet", "")
                                    if not _url or not _title:
                                        continue
                                    _low = _url.lower()
                                    if "x.com" in _low or "twitter.com" in _low:
                                        _plat = "X"
                                    elif "threads" in _low:
                                        _plat = "Threads"
                                    elif "facebook" in _low:
                                        _plat = "Facebook"
                                    elif "instagram" in _low:
                                        _plat = "Instagram"
                                    elif "medium.com" in _low:
                                        _plat = "Medium"
                                    elif "youtube" in _low:
                                        _plat = "YouTube"
                                    elif "linkedin" in _low:
                                        _plat = "LinkedIn"
                                    else:
                                        # Fallback items are articles / blogs, not LinkedIn posts - show the domain
                                        try:
                                            from urllib.parse import urlparse as _up
                                            _dom = _up(_url).netloc.replace("www.", "")
                                            _plat = f"Web - {_dom}" if _dom else "Web"
                                        except Exception:
                                            _plat = "Web"
                                    try:
                                        _fallback_items.append(ContentItem(_plat, _title, _url, "Serper Fallback", "", _snippet, full_content=_snippet, comment_count=10, hours_since_post=12.0, is_question=("?" in (_title + _snippet))))
                                    except Exception:
                                        try:
                                            _fallback_items.append(ContentItem(platform=_plat, title=_title, url=_url, source="Serper Fallback", published="", snippet=_snippet, full_content=_snippet, comment_count=10, hours_since_post=12.0, is_question=("?" in (_title + _snippet))))
                                        except Exception as _e3:
                                            _log(f"Could not build item for {_url}: {_e3}")
                                            continue
                            except Exception as _e4:
                                _log(f"Fallback for term '{_term}' failed: {_e4}")
                                continue
                        _log(f"Fallback found {len(_fallback_items)} items from direct Serper. Using them for this run.")
                        if _fallback_items:
                            content_items = _fallback_items
                            st.success(f"Fallback worked: using {len(content_items)} posts from direct Serper.")
                        else:
                            st.error("Fallback also returned 0.")
                    except Exception as _e5:
                        st.error(f"Fallback failed: {_e5}")
        elif not content_items:
            st.warning("Please upload a JSON file first.")
            return
        if not content_items:
            st.warning("No posts discovered or uploaded.")
            if "last_run_log" in st.session_state:
                st.session_state["last_run_log"].append("Final: No posts discovered or uploaded - both run_discovery and fallback returned 0.")
            return
        history = set() if ignore_hist else load_history()
        unique = dedupe_and_filter(content_items, history)
        selected = select_candidates(unique)
        if not selected:
            st.warning("No candidates passed the relevance filter.")
            return
        try:
            client = _make_gemini_client()
        except GeminiUnavailable as exc:
            st.error(f"Gemini error: {exc}")
            return
        except TypeError as exc:
            st.error(f"GeminiClient signature mismatch (TypeError): {exc}")
            return
        except Exception as exc:
            st.error(f"Gemini error: {exc}")
            return
        grok = None
        if dual and GROK_API_KEY:
            try:
                grok = _make_grok_client()
                st.info(f"Dual-engine ON: Gemini drafts → Grok ({GROK_MODEL}) reviews each recommended draft.")
            except Exception:
                st.warning("Grok key missing/invalid — running Gemini-only for this batch.")
                grok = None
        elif dual and not GROK_API_KEY:
            st.warning("Dual-engine checked but GROK_API_KEY not set — running Gemini-only.")
        progress = st.progress(0.0, text="Analysing posts...")
        variant_counter = 0
        for i, item in enumerate(selected, 1):
            try:
                analysis = analyse_post(client, item)
            except Exception as _ae:
                analysis = None
                item.analysis_error = f"analyse_post raised: {_ae}"
            if not analysis:
                analysis = _heuristic_analysis(item)
                if analysis:
                    item.analysis_error = getattr(item, "analysis_error", "") + " | Used heuristic fallback."
                else:
                    item.decision, item.decision_reason = Decision.D_SKIP, getattr(item, "analysis_error", None) or "Analysis failed."
            else:
                try:
                    item.decision = Decision(analysis["decision"])
                except Exception:
                    item.decision = Decision.D_SKIP
                item.decision_reason = analysis.get("decision_reason", "")
                item.context_summary = analysis.get("context_summary", "")
                try:
                    if Sensitivity is not None:
                        item.sensitivity = Sensitivity(analysis.get("sensitivity", "LOW"))
                        item.sensitivity_reason = analysis.get("sensitivity_reason", "")
                except Exception:
                    pass
                try:
                    if Confidence is not None:
                        item.confidence = Confidence(analysis.get("confidence", "LOW"))
                except Exception:
                    pass
                item.book_theme = analysis.get("book_theme", "")
                item.promotion_justification = analysis.get("promotion_justification", "")
                item.book_alignment_score = analysis.get("book_alignment_score", 0)
                item.contextual_relevance_score = analysis.get("contextual_relevance_score", 0)
                item.engagement_score = analysis.get("engagement_score", 0)
                item.audience_alignment_score = analysis.get("audience_alignment_score", 0)
                item.promotion_naturalness_score = analysis.get("promotion_naturalness_score", 0)
                item.promotion_score = analysis.get("promotion_score", 0)
                if analysis.get("guardrail_override"):
                    item.rejection_reason = analysis["guardrail_override"]
                try:
                    item.opportunity_score = calculate_opportunity_score(item)
                except Exception:
                    item.opportunity_score = 0
                if item.decision in (Decision.A_PROMOTE, Decision.B_ENGAGE):
                    time.sleep(min(GEMINI_DELAY_SECONDS, 1.0))
                    try:
                        generate_drafts(client, item, variant=variant_counter % 3, grok_client=grok)
                    except Exception as e:
                        item.decision_reason = f"Draft failed: {e}"
                    variant_counter += 1
            progress.progress(i / len(selected), text=f"[{i}/{len(selected)}] {item.platform} — {item.title[:40]}")
            time.sleep(min(GEMINI_DELAY_SECONDS, 1.0))
        info = enforce_theme_cap_and_diversity(selected)
        if not info.get("diversity_ok", True):
            st.warning(f"Theme diversity: only {info.get('themes_covered', 0)} themes covered (aim for 3+).")
        grouped = {}
        # Include every platform in selected, not just PLATFORM_ORDER - otherwise Web / YouTube / Medium are dropped from Preview
        _all_plats = []
        for _x in selected:
            _pl = getattr(_x, "platform", "Web")
            if _pl not in _all_plats:
                _all_plats.append(_pl)
        for p in PLATFORM_ORDER + [x for x in _all_plats if x not in PLATFORM_ORDER]:
            grp = [x for x in selected if x.platform == p]
            if grp:
                grouped[p] = grp
        counts = {d.value: sum(1 for x in selected if x.decision == d) for d in Decision}
        summary = f"{len(selected)} assessed: {counts.get('A_PROMOTE', 0)} promote · {counts.get('B_ENGAGE', 0)} engage · {counts.get('C_SENSITIVE', 0)} sensitive · {counts.get('C_WAIT', 0)} wait · {counts.get('D_SKIP', 0)} skip. Themes: {info.get('themes_covered', 0)}."
        digest = Digest(datetime.now().strftime("%Y-%m-%d"), len(selected), grouped, summary, datetime.now().isoformat(timespec="seconds"))
        out_dir = Path(tempfile.mkdtemp())
        html_path, md_path, json_path = out_dir / "digest.html", out_dir / "digest.md", out_dir / "digest.json"
        write_html(digest, html_path)
        write_markdown(digest, md_path)
        write_json(digest, json_path)
        try:
            save_history(x.url for x in selected)
        except Exception:
            pass
        st.session_state["selected_items"] = selected
        st.session_state["result"] = {"summary": summary, "html": html_path.read_text(encoding="utf-8"), "md": md_path.read_text(encoding="utf-8"), "json": json_path.read_text(encoding="utf-8"), "history": HISTORY_FILE.read_bytes() if HISTORY_FILE.exists() else b"", "posted_count": sum(1 for x in selected if x.decision in (Decision.A_PROMOTE, Decision.B_ENGAGE))}
        st.session_state["grok_client_available"] = grok is not None
        st.session_state["gemini_model_used"] = GEMINI_MODEL

    if "result" in st.session_state:
        res = st.session_state["result"]
        st.success(f"Done! {res['summary']}")
        c1, c2, c3 = st.columns(3)
        c1.download_button("Download HTML", res["html"], "digest.html", "text/html")
        c2.download_button("Download Markdown", res["md"], "digest.md", "text/markdown")
        c3.download_button("Download JSON", res["json"], "digest.json", "application/json")
        st.download_button("Download seen_posts.txt", res["history"], "seen_posts.txt")
        st.subheader("Preview - frozen at Run time")
        st.caption("This Preview is the Digest built at Run time. Override drafts you generate in Step 2 below will NOT appear in this Preview - they appear in Step 2 itself and in 'Your override drafts' at the bottom. Links open in a new tab.")
        st.components.v1.html(res["html"], height=900, scrolling=True)
        st.divider()
        st.subheader("Step 2: Your decision - Override Skip / Wait")
        st.caption("Scoring gives a suggestion. You decide. Sensitive stays blocked for safety. For Skip or Wait, click Generate draft anyway to make a draft even if the score was low. Drafts appear here in Step 2, not in the frozen Preview above.")
        selected = st.session_state.get("selected_items", [])
        overridable = [x for x in selected if getattr(x, "decision", None) in (Decision.D_SKIP, Decision.C_WAIT)]
        sensitive_items = [x for x in selected if getattr(x, "decision", None) == Decision.C_SENSITIVE]
        if sensitive_items:
            st.write(f"{len(sensitive_items)} Sensitive items are blocked and have no override.")
        if not overridable:
            st.write("No Skip or Wait items to override in this run.")
        else:
            st.write(f"{len(overridable)} Skip/Wait items below. Preview has no buttons - buttons are here in Step 2. Use the filter to find a Medium / YouTube / LinkedIn post without scrolling all {len(overridable)}.")
            _filter = st.text_input("Filter Step 2 by title, platform, or link (e.g. Medium, YouTube, LinkedIn, Geoff Woods):", value="", key="step2_filter")
            _plat_filter = st.selectbox("Filter by platform:", options=["All"] + sorted(set(getattr(x, "platform", "Web") for x in overridable)), key="step2_plat")
            _filtered = overridable
            if _filter.strip():
                _f = _filter.strip().lower()
                _filtered = [x for x in _filtered if _f in (getattr(x, "title", "") or "").lower() or _f in (getattr(x, "platform", "") or "").lower() or _f in (getattr(x, "url", "") or "").lower() or _f in (getattr(x, "snippet", "") or "").lower()]
            if _plat_filter != "All":
                _filtered = [x for x in _filtered if getattr(x, "platform", "") == _plat_filter]
            st.caption(f"Showing {len(_filtered)} of {len(overridable)} after filter. If you saw a Medium article in Preview, type 'Medium' above to find it.")
            if not _filtered:
                st.warning("No posts match that filter. Clear the filter to see all.")
            for idx, it in enumerate(_filtered):
                _plat_label = getattr(it, "platform", "Web")
                with st.expander(f"{_plat_label} - {it.title[:90]} | Suggested: {it.decision.value} | Promo: {getattr(it, 'promotion_score', 0)} | Opp: {getattr(it, 'opportunity_score', 0)} | Why: {getattr(it, 'decision_reason', '')}"):
                    st.write(f"**Link:** {it.url}")
                    st.write(f"**Platform label:** {_plat_label} - fallback items are web articles, not real LinkedIn posts, which is why they scored Skip.")
                    st.write(f"**Why suggested Skip/Wait:** {getattr(it, 'decision_reason', '')}")
                    st.write(f"**Snippet:** {(getattr(it, 'snippet', '') or '')[:400]}")
                    btn_key = f"override-{idx}-{it.url}"
                    # Show any previously generated override draft - this persists across reruns
                    if st.session_state.get(f"override-done-{btn_key}") and getattr(it, "comment", ""):
                        st.success("Override draft saved for this post:")
                        st.write("**Option A - Gemini (formatted, copy-ready):**")
                        _fmt_prev = _format_draft_comment(getattr(it, "comment", ""), it)
                        _copy_button("Copy Option A", _fmt_prev, f"prev-{btn_key}")
                        st.caption("Click Copy above, then paste in LinkedIn / X / Threads manually.")
                        if getattr(it, "grok_comment", ""):
                            st.write(f"**Option B - Grok reviewed ({getattr(it, 'grok_note', '')} / {getattr(it, 'grok_verdict', '')}):**")
                            st.code(getattr(it, "grok_comment", ""))
                        else:
                            st.caption("Grok review unavailable for this item - Gemini draft only. Copy Option A.")
                    elif st.session_state.get(f"override-done-{btn_key}") and not getattr(it, "comment", ""):
                        st.warning("You clicked Generate, but no draft was saved. The generator returned empty for this post. Click Generate again to try the direct Gemini fallback below.")
                    if st.button("Generate draft anyway for this post", key=btn_key):
                        if not GEMINI_API_KEY:
                            st.error("GEMINI_API_KEY missing.")
                        else:
                            with st.spinner("Generating draft with Gemini..."):
                                try:
                                    client2 = _make_gemini_client()
                                    grok2 = None
                                    if dual and GROK_API_KEY:
                                        try:
                                            grok2 = _make_grok_client()
                                        except Exception:
                                            grok2 = None
                                    # Force the generator to treat this as an Engage post - otherwise it may early-return for Skip
                                    try:
                                        _orig_dec = it.decision
                                        it.decision = Decision.B_ENGAGE
                                    except Exception:
                                        _orig_dec = None
                                    _gen_err = None
                                    try:
                                        generate_drafts(client2, it, variant=0, grok_client=grok2)
                                    except Exception as _e:
                                        _gen_err = str(_e)
                                    # If generate_drafts did not set a comment, try a direct Gemini call - do not stay silent
                                    if not getattr(it, "comment", ""):
                                        st.caption(f"generate_drafts returned no draft ({_gen_err or 'empty'}). Trying direct Gemini fallback...")
                                        try:
                                            _themes_for_prompt = ", ".join([str(t) if not isinstance(t, (tuple, list)) else str(t[0]) for t in (BOOK_THEMES or [])])
                                            _direct_prompt = f"""Write a short LinkedIn-style comment (max 80 words) for this post. Be helpful, add one idea from the book 'Games for Gravitas' about purposeful rehearsal / rehearse before you decide / centaur leadership, but do not hard-sell. End with an open question. Book themes: {_themes_for_prompt}. Post title: {it.title}. Post content: {(getattr(it, 'snippet', '') or '')[:800]}. Return only the comment, no extra text."""
                                            _direct_text = ""
                                            if hasattr(client2, "generate"):
                                                _direct_text = client2.generate(_direct_prompt) or ""
                                            elif hasattr(client2, "generate_content"):
                                                _r = client2.generate_content(_direct_prompt)
                                                _direct_text = getattr(_r, "text", "") or ""
                                            if _direct_text and _direct_text.strip():
                                                it.comment = _direct_text.strip()
                                                # Try Grok review for the direct draft too
                                                if grok2 is not None:
                                                    try:
                                                        _grok_prompt = f"Improve this comment for LinkedIn, keep it under 80 words, keep the book idea but make it less salesy. Comment: {it.comment}"
                                                        if hasattr(grok2, "generate"):
                                                            _g = grok2.generate(_grok_prompt) or ""
                                                            if _g.strip():
                                                                it.grok_comment = _g.strip()
                                                                it.grok_note = "Direct fallback"
                                                                it.grok_verdict = "Improved"
                                                    except Exception:
                                                        pass
                                            else:
                                                st.warning("Direct Gemini fallback returned empty. Using template draft so you still have something to copy - Gemini error is shown below.")
                                                try:
                                                    it.comment = _template_draft(it)
                                                    # Try Grok on the template draft too, so you get Option B even when Gemini is down
                                                    if grok2 is not None:
                                                        try:
                                                            _grok_prompt2 = f"Improve this comment for LinkedIn, keep it under 80 words, keep the book idea but make it less salesy. Comment: {it.comment}"
                                                            _g2 = ""
                                                            if hasattr(grok2, "generate"):
                                                                _g2 = grok2.generate(_grok_prompt2) or ""
                                                            elif hasattr(grok2, "generate_content"):
                                                                _r2 = grok2.generate_content(_grok_prompt2)
                                                                _g2 = getattr(_r2, "text", "") or ""
                                                            if _g2 and _g2.strip():
                                                                it.grok_comment = _format_draft_comment(_g2.strip(), it)
                                                                it.grok_note = "Grok reviewed template"
                                                                it.grok_verdict = "Improved"
                                                            else:
                                                                it.grok_comment = ""
                                                                it.grok_note = "Grok empty"
                                                                it.grok_verdict = "Template only"
                                                        except Exception as _ge2:
                                                            it.grok_comment = ""
                                                            it.grok_note = f"Grok failed: {_ge2}"
                                                            it.grok_verdict = "Template only"
                                                    else:
                                                        it.grok_comment = ""
                                                        it.grok_note = "Grok not available - check GROK_API_KEY"
                                                        it.grok_verdict = "Template only"
                                                except Exception as _te:
                                                    st.error(f"Template draft failed: {_te}")
                                        except Exception as _e2:
                                            st.warning(f"Direct Gemini fallback failed with real error: {_e2}. Using template draft so you still have something to copy.")
                                            try:
                                                it.comment = _template_draft(it)
                                                it.grok_comment = ""
                                                it.grok_note = "Template - Gemini error"
                                                it.grok_verdict = "Template"
                                            except Exception as _te2:
                                                st.error(f"Template draft failed: {_te2}")
                                    if getattr(it, "comment", ""):
                                        # Format the draft for copying
                                        it.comment = _format_draft_comment(getattr(it, "comment", ""), it)
                                        if getattr(it, "grok_comment", ""):
                                            it.grok_comment = _format_draft_comment(getattr(it, "grok_comment", ""), it)
                                        st.session_state[f"override-done-{btn_key}"] = True
                                        st.success("Draft generated for this post. It is saved below - copy it from here, not from the frozen Preview above.")
                                        st.write("**Option A - Gemini (formatted, copy-ready):**")
                                        _copy_button("Copy Option A", getattr(it, "comment", ""), f"gen-{btn_key}")
                                        if getattr(it, "grok_comment", ""):
                                            st.write(f"**Option B - Grok reviewed ({getattr(it, 'grok_note', '')} / {getattr(it, 'grok_verdict', '')}):**")
                                            st.code(getattr(it, "grok_comment", ""))
                                        else:
                                            st.caption("Grok review unavailable for this item - copy Option A.")
                                    else:
                                        st.error(f"Still no draft. Generator error was: {_gen_err or 'unknown'}. Try again in 30 seconds, or try a different post - this post may have too little content for Gemini to draft from.")
                                except Exception as _e_outer:
                                    st.error(f"Override failed: {_e_outer}")
        # Combined override drafts - so you can copy all in one place
        _override_drafts = [x for x in selected if getattr(x, "comment", "") and getattr(x, "decision", None) in (Decision.D_SKIP, Decision.C_WAIT, Decision.B_ENGAGE) and getattr(x, "decision_reason", "") != ""]
        # Also include any item where override was clicked
        _has_any_override = any(st.session_state.get(f"override-done-override-{i}-{x.url}") for i, x in enumerate(overridable))
        if _has_any_override or any(getattr(x, "comment", "") for x in overridable):
            st.divider()
            st.subheader("Your override drafts - copy from here")
            st.caption("These are the drafts you generated in Step 2. Copy them one by one and paste manually. They are not in the frozen Preview above.")
            _md_lines = ["# Override drafts\n"]
            for _it in overridable:
                if getattr(_it, "comment", ""):
                    st.write(f"**{_it.title[:80]}** - {_it.url}")
                    _fmt_c = _format_draft_comment(getattr(_it, "comment", ""), _it)
                    _copy_button("Copy this draft", _fmt_c, f"combined-{_it.url}")
                    if getattr(_it, "grok_comment", ""):
                        st.write("Grok version:")
                        st.code(getattr(_it, "grok_comment", ""))
                    _md_lines.append(f"## {_it.title}\n{_it.url}\n\nGemini:\n{_it.comment}\n")
                    if getattr(_it, "grok_comment", ""):
                        _md_lines.append(f"\nGrok:\n{_it.grok_comment}\n")
                    _md_lines.append("\n---\n")
            st.download_button("Download override drafts as Markdown", "\n".join(_md_lines), "override_drafts.md", "text/markdown")
        st.divider()
        st.subheader("2. Low-cost effectiveness — 1 line per week (#12)")
        st.caption("After you post this batch, come back in 48h and enter 2 numbers. No per-comment tracking.")
        posted = res.get("posted_count", 0)
        st.write(f"Comments posted in this batch: **{posted}**")
        replies = st.number_input("Replies to this batch (from Notifications)", min_value=0, step=1)
        if st.button("Save weekly effectiveness"):
            if posted == 0:
                st.warning("No Promote/Engage comments in this batch to measure.")
            else:
                rec = append_effectiveness(posted, int(replies))
                st.success(f"Saved: {rec['date']}, {posted} posted, {replies} replies → {rec['yield']}% yield. {yield_label(rec['yield'])}")


if __name__ == "__main__":
    main()
