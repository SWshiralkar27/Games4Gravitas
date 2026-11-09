"""Streamlit app — UI only. All logic lives in modules. GitHub → Streamlit Cloud ready."""
from __future__ import annotations
import argparse, asyncio, sys, time, tempfile, logging
from datetime import datetime
from pathlib import Path
import streamlit as st
from config import VERSION, GEMINI_API_KEY, GEMINI_MODEL, SEARCH_PROVIDER, YOUTUBE_API_KEY, GEMINI_DELAY_SECONDS, HISTORY_FILE, PLATFORM_ORDER, GROK_API_KEY, GROK_MODEL, GROK_ENABLED
from models import ContentItem, Digest, Decision, Sensitivity, Confidence
from history import load_history, save_history, dedupe_and_filter
from discovery import run_discovery
from scoring.selection import select_candidates, enforce_theme_cap_and_diversity
from scoring.opportunity import calculate_opportunity_score
from gemini_client import GeminiClient, GeminiUnavailable, analyse_post
from grok_client import GrokClient, GrokUnavailable
from drafting.generator import generate_drafts
from exporters import write_html, write_markdown, write_json
from effectiveness import append_effectiveness, load_effectiveness, yield_label
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("digest")

def main_streamlit():
    st.set_page_config(page_title=f"Leadership AI Digest v{VERSION}", layout="wide")
    st.title(f"Leadership AI Daily Digest v{VERSION}")
    st.caption("Discover → Dedupe → Analyse → Guardrails → Draft (Gemini) → Review (Grok) → You pick. Fail-closed. Human publishes manually.")
    with st.sidebar:
        st.subheader("Config")
        st.write(f"**Gemini Key:** {'✅' if GEMINI_API_KEY else '❌'}")
        st.write(f"**Grok Key:** {'✅ ' + GROK_MODEL if (GROK_API_KEY and GROK_ENABLED) else '❌ / Off — Gemini-only'}")
        st.write(f"**Search Provider:** `{SEARCH_PROVIDER.upper()}`")
        st.write(f"**YouTube Key:** {'✅' if YOUTUBE_API_KEY else '❌'}")
        dual = st.checkbox("Dual-engine: Grok reviews Gemini drafts", value=bool(GROK_API_KEY and GROK_ENABLED))
        up = st.file_uploader("Upload History (seen_posts.txt)", type=["txt"])
        ignore_hist = st.checkbox("Ignore history this run")
        st.divider()
        st.subheader("Effectiveness — last 5 weeks")
        for row in load_effectiveness()[-5:]:
            st.write(f"{row['date']}: {row['comments_posted']} posted, {row['replies']} replies → {row['yield']}% yield")
    if up:
        try:
            HISTORY_FILE.write_text(up.read().decode("utf-8"))
        except Exception:
            pass
    st.subheader("1. Choose Source")
    source_mode = st.radio("How do you want to get posts?", ["Auto-Discover (Uses API Keys)", "Upload JSON"], horizontal=True)
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
        st.info("This will fetch from 【entity-Medium¦canonical_name=Medium】, YouTube, and Web Search (LinkedIn, X, Threads, 【entity-Facebook¦canonical_name=Facebook】, 【entity-Instagram¦canonical_name=Instagram】) based on your API keys and SEARCH_TERMS.")

    # Step 1: Editable search for this run only, not saved
    st.subheader("Step 1: Review search for this run")
    default_search = "\n".join(SEARCH_TERMS)
    edited_search_text = st.text_area(
        "Search terms for this run (one per line, edit or add your own)",
        value=default_search,
        height=180,
        key="edited_search_terms"
    )
    edited_search_terms = [line.strip() for line in edited_search_text.splitlines() if line.strip()]
    default_themes = "\n".join(BOOK_THEMES)
    edited_themes_text = st.text_area(
        "Book themes for this run (one per line, e.g. Human Judgment, Purposeful Rehearsal, Centaur Leadership)",
        value=default_themes,
        height=120,
        key="edited_book_themes"
    )
    edited_book_themes = [line.strip() for line in edited_themes_text.splitlines() if line.strip()]
    st.caption(f"This run will use {len(edited_search_terms)} search terms and {len(edited_book_themes)} themes. Edits are for this run only and will reset next run.")

    if st.button("Run Digest", type="primary"):
        if not GEMINI_API_KEY:
            st.error("GEMINI_API_KEY is missing in Streamlit Secrets.")
            return
        if source_mode == "Auto-Discover (Uses API Keys)":
            with st.spinner("Fetching posts from APIs (may take 30s)..."):
                # Use edited terms for this run only
                import config as _cfg
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
                item.decision, item.decision_reason = Decision.D_SKIP, item.analysis_error or "Analysis failed."
            else:
                item.decision = Decision(analysis["decision"])
                item.decision_reason = analysis["decision_reason"]
                item.context_summary = analysis["context_summary"]
                item.sensitivity = Sensitivity(analysis["sensitivity"])
                item.sensitivity_reason = analysis["sensitivity_reason"]
                item.confidence = Confidence(analysis["confidence"])
                item.book_theme = analysis["book_theme"]
                item.promotion_justification = analysis["promotion_justification"]
                item.book_alignment_score = analysis["book_alignment_score"]
                item.contextual_relevance_score = analysis["contextual_relevance_score"]
                item.engagement_score = analysis["engagement_score"]
                item.audience_alignment_score = analysis["audience_alignment_score"]
                item.promotion_naturalness_score = analysis["promotion_naturalness_score"]
                item.promotion_score = analysis["promotion_score"]
                if analysis.get("guardrail_override"):
                    item.rejection_reason = analysis["guardrail_override"]
                item.opportunity_score = calculate_opportunity_score(item)
                if item.decision in (Decision.A_PROMOTE, Decision.B_ENGAGE):
                    time.sleep(min(GEMINI_DELAY_SECONDS, 1.0))
                    generate_drafts(client, item, variant=variant_counter % 3, grok_client=grok)
                    variant_counter += 1
            progress.progress(i / len(selected), text=f"[{i}/{len(selected)}] {item.platform} — {item.title[:40]}")
            time.sleep(min(GEMINI_DELAY_SECONDS, 1.0))
        info = enforce_theme_cap_and_diversity(selected)
        if not info["diversity_ok"]:
            st.warning(f"Theme diversity: only {info['themes_covered']} themes covered (aim for 3+). Consider wider search terms next run.")
        grouped = {}
        for p in PLATFORM_ORDER:
            grp = [x for x in selected if x.platform == p]
            if grp:
                grouped[p] = grp
        counts = {d.value: sum(1 for x in selected if x.decision == d) for d in Decision}
        summary = f"{len(selected)} assessed: {counts['A_PROMOTE']} promote · {counts['B_ENGAGE']} engage · {counts['C_SENSITIVE']} sensitive · {counts['C_WAIT']} wait · {counts['D_SKIP']} skip. Themes: {info['themes_covered']}."
        digest = Digest(datetime.now().strftime("%Y-%m-%d"), len(selected), grouped, summary, datetime.now().isoformat(timespec="seconds"))
        out_dir = Path(tempfile.mkdtemp())
        html_path, md_path, json_path = out_dir / "digest.html", out_dir / "digest.md", out_dir / "digest.json"
        write_html(digest, html_path)
        write_markdown(digest, md_path)
        write_json(digest, json_path)
        save_history(x.url for x in selected)
        st.session_state["result"] = {"summary": summary, "html": html_path.read_text(encoding="utf-8"), "md": md_path.read_text(encoding="utf-8"), "json": json_path.read_text(encoding="utf-8"), "history": HISTORY_FILE.read_bytes() if HISTORY_FILE.exists() else b"", "posted_count": sum(1 for x in selected if x.decision in (Decision.A_PROMOTE, Decision.B_ENGAGE))}

    if "result" in st.session_state:
        res = st.session_state["result"]
        st.success(f"Done! {res['summary']}")
        c1, c2, c3 = st.columns(3)
        c1.download_button("Download HTML", res["html"], "digest.html", "text/html")
        c2.download_button("Download Markdown", res["md"], "digest.md", "text/markdown")
        c3.download_button("Download JSON", res["json"], "digest.json", "application/json")
        st.download_button("Download seen_posts.txt", res["history"], "seen_posts.txt")
        st.subheader("Preview")
        st.components.v1.html(res["html"], height=900, scrolling=True)
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
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnose", action="store_true")
    args = ap.parse_args()
    if args.diagnose:
        print(f"version={VERSION} | model={GEMINI_MODEL} | provider={SEARCH_PROVIDER}")
        return
    print("Run this app via: streamlit run app.py")

try:
    if st.runtime.exists():
        main_streamlit()
except Exception:
    pass
if __name__ == "__main__" and "streamlit" not in sys.modules:
    main()
