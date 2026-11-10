"""app.py — Leadership AI Digest v4.6 (UI only)
FIXES in v4.3:
- RESTORED: seen_posts.txt upload in left sidebar (dropped in v4.2 by mistake).
  Sidebar shows uploader + count. Streamlit forgets uploads on reboot,
  so re-upload after each reboot. Seen URLs/titles are filtered in discovery.
- Crash fix: app passes seen_urls to run_discovery_with_stats. Discovery
  now normalises every item, so a str/None/object from Medium/YouTube
  cannot crash prune_discovery with AttributeError on p.get().

Kept from v4.2:
- Pruning banner, max 12 Gemini calls, heuristic fallback, Recommended-only default.
- Formatting: bold book, italics keywords, line break after every full stop.
- Gemini: never 2.0-flash, never old SDK. Widgets: never value= + key= together.
"""
import os
import re
import time

import streamlit as st

from config import (
    BOOK_THEMES, GEMINI_MODEL, GROK_MODEL,
    MAX_GEMINI_CALLS_PER_RUN, SEARCH_PROVIDER, SEARCH_TERMS,
)

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


def _parse_seen_file_text(text):
    """Parse seen_posts.txt: one URL per line, or 'title | url', or JSON lines."""
    seen = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # JSON line: {"link": "...", "title": "..."}
        if line.startswith("{"):
            try:
                import json as _json
                obj = _json.loads(line)
                if isinstance(obj, dict):
                    for k in ("link", "url", "href"):
                        if obj.get(k):
                            seen.add(str(obj[k]).strip())
                    if obj.get("title"):
                        seen.add(str(obj["title"]).strip())
                    continue
            except Exception:
                pass
        m = re.search(r"https?://[^\s|]+", line)
        if m:
            seen.add(m.group(0).strip().rstrip(","))
        else:
            # Title-only line
            seen.add(line)
        # Also keep title part before | for matching
        if "|" in line and not line.startswith("http"):
            seen.add(line.split("|")[0].strip())
    return seen



# ---------- v4.5: discovery version check + in-app safe fallback ----------
# Your last traceback proved discovery/__init__.py on Streamlit was still OLD
# (line 68 = crashing p.get line, line 152 = prune without seen_urls),
# while app.py was already new. This fallback makes Run work even if you
# forget to update discovery/__init__.py again. It does NOT replace updating it.
try:
    import discovery as _disc_mod
    DISCOVERY_VERSION = getattr(_disc_mod, "__VERSION__", "OLD - no _normalize_post")
    DISCOVERY_IS_NEW = hasattr(_disc_mod, "_normalize_post") and str(DISCOVERY_VERSION) in ("4.4", "4.5", "4.6")
except Exception:
    DISCOVERY_VERSION = "OLD - import failed"
    DISCOVERY_IS_NEW = False

def _fb_safe_str(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        for x in v:
            if isinstance(x, str) and x.strip():
                return x
        return ""
    if isinstance(v, dict):
        for k in ("href", "url", "link", "value", "text"):
            if k in v and isinstance(v[k], str):
                return v[k]
        return ""
    try:
        return str(v)
    except Exception:
        return ""

def _fb_normalize(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return {"title": s[:500], "link": "", "snippet": s[:1500], "platform": "Web - unknown", "source": "string", "comments": 0} if s else None
    if isinstance(raw, (list, tuple)):
        if len(raw) == 1 and isinstance(raw[0], dict):
            return _fb_normalize(raw[0])
        parts = [_fb_safe_str(x) for x in raw]
        title = next((x for x in parts if x and not x.startswith("http")), "")
        link = next((x for x in parts if x.startswith("http")), "")
        return {"title": title[:500], "link": link, "snippet": " ".join(parts)[:1500], "platform": "Web - unknown", "source": "list", "comments": 0} if (title or link) else None
    if isinstance(raw, dict):
        return {"title": _fb_safe_str(raw.get("title") or raw.get("name") or ""), "link": _fb_safe_str(raw.get("link") or raw.get("url") or raw.get("href") or ""), "snippet": _fb_safe_str(raw.get("snippet") or raw.get("description") or raw.get("summary") or ""), "platform": _fb_safe_str(raw.get("platform") or "") or "Web - unknown", "comments": 0}
    try:
        title = _fb_safe_str(getattr(raw, "title", "") or "")
        link = _fb_safe_str(getattr(raw, "link", "") or getattr(raw, "url", "") or "")
        snip = _fb_safe_str(getattr(raw, "summary", "") or getattr(raw, "description", "") or "")
        if not title and not link and not snip:
            return None
        return {"title": title[:500], "link": link, "snippet": snip[:1500], "platform": "Web - unknown", "comments": 0}
    except Exception:
        return None

def _fb_run_discovery(search_terms, seen_urls):
    """In-app fallback: same pruning, never calls buggy discovery prune. Returns (pruned, stats)."""
    import re as _re
    all_posts, per_source = [], {}
    try:
        from discovery.web_search import search_web
        wp, wc = search_web(search_terms)
        all_posts.extend(wp if isinstance(wp, list) else [wp])
        per_source["web_search"] = len(all_posts)
        per_source["web_queries"] = wc
    except Exception as e:
        per_source["web_search_error"] = str(e)
    try:
        from discovery.medium import fetch_medium
        m = fetch_medium() or []
        m = m if isinstance(m, list) else [m]
        all_posts.extend(m)
        per_source["medium"] = len(m)
    except Exception as e:
        per_source["medium_error"] = str(e)
    try:
        from discovery.youtube import fetch_youtube
        y = fetch_youtube(search_terms) or []
        y = y if isinstance(y, list) else [y]
        all_posts.extend(y)
        per_source["youtube"] = len(y)
    except Exception as e:
        per_source["youtube_error"] = str(e)
    # Normalise + seen filter + dedupe + prune (web capped, social first, max 30)
    norm, invalid = [], 0
    for raw in all_posts:
        n = _fb_normalize(raw)
        if n is None:
            invalid += 1
        else:
            norm.append(n)
    seen_lower = {_fb_safe_str(s).strip().lower().rstrip("/") for s in (seen_urls or [])}
    kept, seen_f = [], 0
    for n in norm:
        if _fb_safe_str(n.get("link")).strip().lower().rstrip("/") in seen_lower and n.get("link"):
            seen_f += 1
            continue
        kept.append(n)
    seen_u, seen_i, dedup = set(), set(), []
    for n in kept:
        u = _fb_safe_str(n.get("link")).strip().lower().rstrip("/")
        idea = _re.sub(r"[^a-z0-9]+", " ", _fb_safe_str(n.get("title")).lower()).strip()[:120]
        if u and u in seen_u:
            continue
        if idea and idea in seen_i:
            continue
        if u:
            seen_u.add(u)
        if idea:
            seen_i.add(idea)
        dedup.append(n)
    social = [x for x in dedup if x.get("platform") in ("LinkedIn", "X", "Threads", "Facebook", "Instagram")]
    web = [x for x in dedup if (x.get("platform") or "").startswith("Web -") or x.get("platform") in ("Medium", "YouTube")]
    other = [x for x in dedup if x not in social and x not in web]
    web_limit = 0 if len(social) >= 8 else (5 if social else 15)
    web_kept = web[:web_limit]
    for x in web_kept:
        x["_auto_skip"] = True
        x["_skip_reason"] = "Web article - no thread to join."
    for x in social + other:
        x["_auto_skip"] = False
    combined = sorted(social + other + web_kept, key=lambda x: (0 if x.get("platform") in ("LinkedIn", "X", "Threads", "Facebook", "Instagram") else 1))
    pruned = combined[:30]
    stats = {"raw": len(all_posts), "invalid_skipped": invalid, "seen_filtered": seen_f, "deduped": len(dedup), "social": len(social), "web_total": len(web), "web_kept": len(web_kept), "web_pruned": len(web) - len(web_kept), "kept_for_assessment": len(pruned), "per_source": per_source, "fallback_used": True}
    return pruned, stats

st.set_page_config(page_title="Leadership AI Digest", layout="wide")
st.title("Leadership AI Daily Digest Generator")

# ---------- Session state: init once, then key= only ----------
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
if "seen_urls" not in st.session_state:
    st.session_state.seen_urls = set()

def _reset_search():
    st.session_state.edited_search_terms = "\n".join(SEARCH_TERMS)
    st.session_state.edited_book_themes = "\n".join(BOOK_THEMES)

def _log(msg):
    st.session_state.last_run_log.append(msg)

# ---------- Sidebar: status + RESTORED seen_posts.txt upload ----------
with st.sidebar:
    st.header("Status")
    st.write(f"Gemini Key {'✅' if os.getenv('GEMINI_API_KEY') else '❌'}")
    st.write(f"Grok Key {'✅' if os.getenv('GROK_API_KEY') else '❌'} {GROK_MODEL}")
    st.write(f"Search Provider {SEARCH_PROVIDER.upper()}")
    st.write(f"YouTube Key {'✅' if os.getenv('YOUTUBE_API_KEY') else '—'}")
    st.write(f"Gemini Model {GEMINI_MODEL}")
    st.write(f"Discovery file: {DISCOVERY_VERSION}")
    if not DISCOVERY_IS_NEW:
        st.error("Discovery file is OLD. Re-upload discovery/__init__.py v4.6 to discovery/ folder (not root). Using in-app fallback for this run.")
    st.checkbox("Dual-engine (Gemini + Grok review)", value=True, key="dual_engine")
    if GEMINI_MODEL != "gemini-3.8-flash":
        st.error("GEMINI_MODEL must be gemini-3.8-flash in Secrets. Fix + reboot.")
    if "quota_until" in st.session_state:
        st.warning(f"Gemini quota hit. Retry after: {st.session_state.get('quota_retry_text','~4h')}")

    st.divider()
    st.subheader("Seen posts")
    st.caption("Upload your saved file before first run. Streamlit forgets uploads on reboot, so re-upload after each reboot.")
    seen_file = st.file_uploader("Upload seen_posts.txt", type=["txt"], key="seen_posts_uploader")
    if seen_file is not None:
        try:
            content = seen_file.read().decode("utf-8", errors="ignore")
            parsed = _parse_seen_file_text(content)
            # Only overwrite if file actually has content, so a re-render does not wipe it
            if parsed:
                st.session_state.seen_urls = parsed
            st.success(f"Loaded {len(st.session_state.seen_urls)} seen posts. They will be filtered from Discovery.")
        except Exception as e:
            st.error(f"Could not read seen_posts.txt: {e}")
    st.write(f"Seen loaded: {len(st.session_state.seen_urls)}")
    if len(st.session_state.seen_urls) == 0:
        st.info("No seen_posts.txt loaded yet. Upload it to avoid re-suggesting old posts.")
    # Optional effectiveness file, kept for Sunday Snapshot workflow
    eff_file = st.file_uploader("Upload effectiveness.txt (optional)", type=["txt"], key="effectiveness_uploader")
    if eff_file is not None:
        try:
            eff_text = eff_file.read().decode("utf-8", errors="ignore")
            st.session_state.effectiveness_text = eff_text
            st.write(f"effectiveness.txt loaded ({len(eff_text.splitlines())} lines)")
        except Exception:
            pass

# ---------- Step 1: Review search ----------
st.header("Step 1 — Review search")
st.text_area("Search keywords (one per line, this run only)", key="edited_search_terms")
st.text_area("Book themes (one per line, this run only)", key="edited_book_themes")
st.button("Reset search / themes", on_click=_reset_search)

search_terms = [l.strip() for l in st.session_state.edited_search_terms.splitlines() if l.strip()]
book_themes = [l.strip() for l in st.session_state.edited_book_themes.splitlines() if l.strip()]

if st.button("Run Discovery"):
    if run_discovery_with_stats is None and not DISCOVERY_IS_NEW:
        st.error(f"Discovery import failed: {_DISCOVERY_ERR}")
    else:
        pruned, stats = None, {}
        used_fallback = False
        try:
            with st.spinner("Discovering…"):
                if DISCOVERY_IS_NEW:
                    pruned, stats = run_discovery_with_stats(
                        search_terms=search_terms,
                        book_themes=book_themes,
                        seen_urls=st.session_state.seen_urls,
                    )
                else:
                    raise AttributeError("OLD discovery file detected - using fallback")
        except AttributeError as ae:
            st.warning(f"Old discovery file caused AttributeError ({ae}). Using in-app safe fallback, so Run will not crash. Still re-upload discovery/__init__.py v4.6.")
            with st.spinner("Discovering via safe fallback…"):
                pruned, stats = _fb_run_discovery(search_terms, st.session_state.seen_urls)
            used_fallback = True
        except Exception as e:
            st.warning(f"Discovery failed ({e}). Trying safe fallback.")
            with st.spinner("Discovering via safe fallback…"):
                pruned, stats = _fb_run_discovery(search_terms, st.session_state.seen_urls)
            used_fallback = True
        st.session_state.posts = pruned or []
        st.session_state.assessed = []
        _log(f"Discovery: raw={stats.get('raw')} invalid_skipped={stats.get('invalid_skipped')} seen_filtered={stats.get('seen_filtered')} deduped={stats.get('deduped')} social={stats.get('social')} web_pruned={stats.get('web_pruned')} kept={stats.get('kept_for_assessment')} fallback={used_fallback}")
        st.success(
            f"Discovery returned {stats.get('raw', 0)} raw posts before dedupe / pruned to "
            f"{stats.get('kept_for_assessment', 0)} for assessment. "
            f"Seen filtered: {stats.get('seen_filtered', 0)}. "
            f"Invalid skipped: {stats.get('invalid_skipped', 0)}. "
            f"Web articles pruned: {stats.get('web_pruned', 0)}. "
            f"Social threads: {stats.get('social', 0)}. Per-source: {stats.get('per_source', {})}"
            + (" [SAFE FALLBACK USED - update discovery file]" if used_fallback else "")
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
        if not isinstance(p, dict):
            # Defensive: should not happen after v4.3 normalisation, but never crash
            continue
        if p.get("_auto_skip"):
            h = heuristic_assess(p)
            assessed.append({**p, **h})
            progress.progress((i + 1) / max(1, len(posts)))
            continue
        if id(p) in to_gemini_ids and gemini is not None and not quota_hit and not st.session_state.quota_hit:
            try:
                a = gemini.analyse_post(p)
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
                _log(f"Gemini analyse failed for {str(p.get('title',''))[:60]}: {e}")
                h = heuristic_assess(p)
                assessed.append({**p, **h})
        else:
            h = heuristic_assess(p)
            assessed.append({**p, **h})
        progress.progress((i + 1) / max(1, len(posts)))
    st.session_state.assessed = assessed
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
        filtered = [x for x in filtered if q in (str(x.get("title", "")) + str(x.get("platform", "")) + str(x.get("link", ""))).lower()]
    st.write(f"Showing {len(filtered)} of {len(st.session_state.assessed)} after filter")

    for idx, post in enumerate(filtered):
        if not isinstance(post, dict):
            continue
        title = str(post.get("title", "Untitled"))[:120]
        with st.expander(f"{post.get('platform','Web')} - {title} | Suggested: {post.get('decision')} | Promo: {post.get('promo')} | Opp: {post.get('opp')} | Why: {str(post.get('reason',''))[:120]}"):
            st.markdown(f"Link: [{str(post.get('link',''))[:80]}]({post.get('link','')})")
            st.write(f"**Platform label:** {post.get('platform')}")
            st.write(f"**Why suggested {post.get('decision')}:** {post.get('reason')}")
            st.write(f"**Snippet:** {str(post.get('snippet',''))[:400]}")
            if post.get("decision") == "D_SENSITIVE":
                st.warning("Sensitive — drafting blocked.")
            else:
                key = f"draft_{idx}_{str(post.get('link',''))[:30]}"
                if st.button("Generate draft anyway for this post", key=key):
                    st.info("generate_drafts: trying Gemini…")
                    draft_a = None
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
                    draft_a = format_draft(draft_a)
                    st.subheader("Option A — Gemini / Template (formatted)")
                    st.markdown(draft_a)
                    st.code(draft_a, language="markdown")
                    st.text_area("Copy Option A", value=draft_a, key=f"copy_a_{idx}", height=150)
                    st.download_button("Download draft as .txt", data=draft_a, file_name="draft.txt", mime="text/plain", key=f"dl_{idx}")
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
                            st.info(f"Grok review failed (real error): {e}. Option A above is still usable.")
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
