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

# --- Imports from your existing modules. Fallbacks keep app running if a name moved ---
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

try:
    from gemini_client import GeminiClient, GeminiUnavailable
except Exception:
    GeminiClient = None
    class GeminiUnavailable(Exception):
        pass

try:
    from grok_client import GrokClient, GrokUnavailable
except Exception:
    GrokClient = None
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

try:
    from scoring.relevance import analyse_post
except Exception:
    try:
        from gemini_client import analyse_post
    except Exception:
        def analyse_post(client, item):
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


def main():
    st.set_page_config(page_title="Leadership AI Daily Digest v4.1", layout="wide")
    st.title("Leadership AI Daily Digest v4.1")
    st.caption("Discover → Dedupe → Analyse → Guardrails → Draft (Gemini) → Review (Grok) → You pick. Fail-closed. Human publishes manually.")

    # --- Sidebar: Config ---
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
        st.divider()
        st.subheader("Effectiveness — last 5 weeks")
        try:
            from pathlib import Path as _P
            eff_path = _P("effectiveness.txt")
            if eff_path.exists():
                lines = eff_path.read_text(encoding="utf-8").strip().splitlines()[-5:]
                for ln in lines:
                    st.caption(ln)
            else:
                st.caption("No data yet.")
        except Exception:
            st.caption("No data yet.")

    # --- 1. Choose Source ---
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

    # --- Step 1: Editable search for this run only, not saved ---
    st.subheader("Step 1: Review search for this run")
    default_search = "\n".join(SEARCH_TERMS)
    edited_search_text = st.text_area(
        "Search terms for this run (one per line, edit or add your own)",
        value=default_search,
        height=180,
        key="edited_search_terms"
    )
    edited_search_terms = [line.strip() for line in edited_search_text.splitlines() if line.strip()]

    # BOOK_THEMES is defined in config.py, with fallback here so it never crashes
    _default_themes = BOOK_THEMES if isinstance(BOOK_THEMES, list) and BOOK_THEMES else ["Human Judgment", "Purposeful Rehearsal", "Centaur Leadership", "Rehearse Before You Decide", "Human Advantage"]
    default_themes = "\n".join(_default_themes)
    edited_themes_text = st.text_area(
        "Book themes for this run (one per line, e.g. Human Judgment, Purposeful Rehearsal, Centaur Leadership)",
        value=default_themes,
        height=120,
        key="edited_book_themes"
    )
    edited_book_themes = [line.strip() for line in edited_themes_text.splitlines() if line.strip()]
    st.caption(f"This run will use {len(edited_search_terms)} search terms and {len(edited_book_themes)} themes. Edits are for this run only and will reset next run.")

    # --- Run Digest: single button only ---
    if st.button("Run Digest", type="primary"):
        if not GEMINI_API_KEY:
            st.error("GEMINI_API_KEY is missing in Streamlit Secrets.")
            return
        if source_mode == "Auto-Discover (Uses API Keys)":
            with st.spinner("Fetching posts from APIs (may take 30s)..."):
                # Use edited terms for this run only
                _cfg.SEARCH_TERMS = edited_search_terms
                _cfg.BOOK_THEMES = edited_book_themes
                content_items = asyncio.run(run_discovery())
        elif not content_items:
            st.warning("Please upload a JSON file first.")
            return
        if not content_items:
            st.warning("No posts discovered or uploaded.")
            return
        history = set() if ignore_hist else load_history()
        unique = dedupe_and_filter(content_items, history)
        selected = select_candidates(unique)
        if not selected:
            st.warning("No candidates passed the relevance filter.")
            return
        try:
            client = GeminiClient(GEMINI_API_KEY, GEMINI_MODEL)
        except GeminiUnavailable as exc:
            st.error(f"Gemini error: {exc}")
            return
        grok = None
        if dual and GROK_API_KEY:
            try:
                grok = GrokClient()
                st.info(f"Dual-engine ON: Gemini drafts → Grok ({GROK_MODEL}) reviews each recommended draft.")
            except GrokUnavailable:
                st.warning("Grok key missing/invalid — running Gemini-only for this batch.")
                grok = None
        elif dual and not GROK_API_KEY:
            st.warning("Dual-engine checked but GROK_API_KEY not set — running Gemini-only.")
        progress = st.progress(0.0, text="Analysing posts...")
        variant_counter = 0
        for i, item in enumerate(selected, 1):
            analysis = analyse_post(client, item)
            if not analysis:
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
            st.warning(f"Theme diversity: only {info.get('themes_covered', 0)} themes covered (aim for 3+). Consider wider search terms next run.")
        grouped = {}
        for p in PLATFORM_ORDER:
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
        # Store selected items for Step 2 override (Skip / Wait)
        st.session_state["selected_items"] = selected
        st.session_state["result"] = {"summary": summary, "html": html_path.read_text(encoding="utf-8"), "md": md_path.read_text(encoding="utf-8"), "json": json_path.read_text(encoding="utf-8"), "history": HISTORY_FILE.read_bytes() if HISTORY_FILE.exists() else b"", "posted_count": sum(1 for x in selected if x.decision in (Decision.A_PROMOTE, Decision.B_ENGAGE))}
        st.session_state["grok_client_available"] = grok is not None
        st.session_state["gemini_model_used"] = GEMINI_MODEL

    # --- Preview: outside the Run button so it stays after rerun ---
    if "result" in st.session_state:
        res = st.session_state["result"]
        st.success(f"Done! {res['summary']}")
        c1, c2, c3 = st.columns(3)
        c1.download_button("Download HTML", res["html"], "digest.html", "text/html")
        c2.download_button("Download Markdown", res["md"], "digest.md", "text/markdown")
        c3.download_button("Download JSON", res["json"], "digest.json", "application/json")
        st.download_button("Download seen_posts.txt", res["history"], "seen_posts.txt")
        st.subheader("Preview")
        st.caption("Links in Preview open in a new tab. Your Digest tab stays open.")
        st.components.v1.html(res["html"], height=900, scrolling=True)
        st.divider()
        # --- Step 2: Your decision - Override Skip / Wait ---
        st.subheader("Step 2: Your decision - Override Skip / Wait")
        st.caption("Scoring gives a suggestion. You decide. Sensitive stays blocked for safety. For Skip or Wait, click Generate draft anyway to make a draft even if the score was low.")
        selected = st.session_state.get("selected_items", [])
        overridable = [x for x in selected if getattr(x, "decision", None) in (Decision.D_SKIP, Decision.C_WAIT)]
        sensitive_items = [x for x in selected if getattr(x, "decision", None) == Decision.C_SENSITIVE]
        if sensitive_items:
            st.write(f"{len(sensitive_items)} Sensitive items are blocked and have no override.")
        if not overridable:
            st.write("No Skip or Wait items to override in this run.")
        else:
            for idx, it in enumerate(overridable):
                with st.expander(f"{it.platform} - {it.title[:90]} | Suggested: {it.decision.value} | Promo: {getattr(it, 'promotion_score', 0)} | Opp: {getattr(it, 'opportunity_score', 0)} | Why: {getattr(it, 'decision_reason', '')}"):
                    st.write(f"**Link:** {it.url}")
                    st.write(f"**Why suggested Skip/Wait:** {getattr(it, 'decision_reason', '')}")
                    btn_key = f"override-{idx}-{it.url}"
                    if st.button("Generate draft anyway for this post", key=btn_key):
                        if not GEMINI_API_KEY:
                            st.error("GEMINI_API_KEY missing.")
                        else:
                            try:
                                client2 = GeminiClient(GEMINI_API_KEY, GEMINI_MODEL)
                                grok2 = None
                                if dual and GROK_API_KEY:
                                    try:
                                        grok2 = GrokClient()
                                    except Exception:
                                        grok2 = None
                                # Generate draft using existing generator
                                generate_drafts(client2, it, variant=0, grok_client=grok2)
                                st.session_state[f"override-done-{btn_key}"] = True
                                st.success("Draft generated. See below and in Preview after re-download.")
                                if getattr(it, "comment", ""):
                                    st.write("**Option A - Gemini:**")
                                    st.code(it.comment)
                                if getattr(it, "grok_comment", ""):
                                    st.write(f"**Option B - Grok reviewed ({getattr(it, 'grok_note', '')} / {getattr(it, 'grok_verdict', '')}):**")
                                    st.code(it.grok_comment)
                                elif getattr(it, "comment", ""):
                                    st.caption("Grok review unavailable for this item - Gemini draft only.")
                            except Exception as e:
                                st.error(f"Override draft failed: {e}")
                    # Show already generated override draft if present
                    if st.session_state.get(f"override-done-{btn_key}") and getattr(it, "comment", ""):
                        st.write("**Saved override draft:**")
                        st.code(it.comment)
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
