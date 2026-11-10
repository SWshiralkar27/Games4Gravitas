"""discovery/__init__.py — v4.2 PRUNING (Fix for Q1)
Root cause of '85 assessed: 85 skip':
Discovery returned 85 raw items, almost all Medium / Web articles.
Web articles have no thread to join -> correctly Skip, but app showed
a huge Skip list and burned Gemini calls trying to assess them.

Fix:
- Dedupe by URL + idea (normalised title).
- Classify social vs web. If >=8 social posts, drop ALL web articles.
  If some social, keep max 5 web. If only web, keep max 15 best web.
- Sort social / question / recent first.
- Cap assessment list to MAX_POSTS_TO_ASSESS (30).
- Web articles are marked _auto_skip=True so app.py does NOT call Gemini
  for them (0 API calls). They get reason, not a Gemini assessment.
- run_discovery() still returns a list (back-compat).
  run_discovery_with_stats() returns (list, stats) for the UI banner.
"""
import re

from config import (
    MAX_POSTS_TO_ASSESS,
    MAX_WEB_ARTICLES_IF_ONLY_WEB,
    MAX_WEB_ARTICLES_IF_SOCIAL_EXISTS,
    MAX_WEB_ARTICLES_IF_SOME_SOCIAL,
    MIN_SOCIAL_TO_DROP_WEB,
    SOCIAL_PLATFORMS,
)


def _norm_text(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _is_social(post):
    return (post.get("platform") or "") in SOCIAL_PLATFORMS


def _is_web(post):
    p = (post.get("platform") or "")
    return p.startswith("Web -") or p in ("Medium", "YouTube")


def _heuristic_sort_key(post):
    title = (post.get("title", "") + " " + post.get("snippet", "")).lower()
    score = 0
    if _is_social(post):
        score += 50
    if "?" in post.get("title", "") or "?" in post.get("snippet", ""):
        score += 20  # question post = conversation opportunity
    if any(w in title for w in ["how", "should", "what", "why", "ai", "leadership", "team", "upskill"]):
        score += 10
    comments = post.get("comments", 0) or 0
    if 5 <= comments <= 30:
        score += 15
    elif comments > 80:
        score -= 10
    if _is_web(post):
        score -= 30
    return -score


def prune_discovery(posts):
    """Input: raw list. Output: (pruned_list, stats)."""
    raw = len(posts or [])
    # Dedupe by URL, then by idea (normalised title)
    seen_url, seen_idea, deduped = set(), set(), []
    for p in posts or []:
        url = (p.get("link") or "").strip().lower().rstrip("/")
        idea = _norm_text(p.get("title", ""))[:120]
        if url and url in seen_url:
            continue
        if idea and idea in seen_idea:
            continue
        if url:
            seen_url.add(url)
        if idea:
            seen_idea.add(idea)
        deduped.append(dict(p))

    social = [p for p in deduped if _is_social(p)]
    web = [p for p in deduped if _is_web(p)]
    other = [p for p in deduped if not _is_social(p) and not _is_web(p)]

    if len(social) >= MIN_SOCIAL_TO_DROP_WEB:
        web_keep_limit = MAX_WEB_ARTICLES_IF_SOCIAL_EXISTS  # 0
    elif len(social) > 0:
        web_keep_limit = MAX_WEB_ARTICLES_IF_SOME_SOCIAL  # 5
    else:
        web_keep_limit = MAX_WEB_ARTICLES_IF_ONLY_WEB  # 15

    social_sorted = sorted(social, key=_heuristic_sort_key)
    web_sorted = sorted(web, key=_heuristic_sort_key)
    other_sorted = sorted(other, key=_heuristic_sort_key)

    web_kept = web_sorted[:web_keep_limit]
    web_pruned = len(web_sorted) - len(web_kept)

    # Mark kept web articles as auto-skip: no Gemini call, no thread to join.
    for p in web_kept:
        p["_auto_skip"] = True
        p["_skip_reason"] = "Web article - no thread to join. Pruned to social threads first."
    for p in social_sorted:
        p["_auto_skip"] = False
    for p in other_sorted:
        p["_auto_skip"] = False

    combined = social_sorted + other_sorted + web_kept
    combined = sorted(combined, key=_heuristic_sort_key)
    pruned = combined[:MAX_POSTS_TO_ASSESS]

    stats = {
        "raw": raw,
        "deduped": len(deduped),
        "social": len(social),
        "web_total": len(web),
        "web_kept": len(web_kept),
        "web_pruned": web_pruned,
        "kept_for_assessment": len(pruned),
        "pruned_total": raw - len(pruned),
    }
    return pruned, stats


def run_discovery_with_stats(search_terms=None, book_themes=None, **kwargs):
    # Accept any param name (older app.py passed different names)
    terms = search_terms or kwargs.get("terms") or kwargs.get("search") or []
    all_posts = []
    per_source = {}
    try:
        from discovery.web_search import search_web
        web_posts, web_counts = search_web(terms)
        all_posts.extend(web_posts)
        per_source["web_search"] = len(web_posts)
        per_source["web_queries"] = web_counts
    except Exception as e:
        per_source["web_search_error"] = str(e)
    try:
        from discovery.medium import fetch_medium
        m = fetch_medium() or []
        all_posts.extend(m)
        per_source["medium"] = len(m)
    except Exception as e:
        per_source["medium_error"] = str(e)
    try:
        from discovery.youtube import fetch_youtube
        y = fetch_youtube(terms) or []
        all_posts.extend(y)
        per_source["youtube"] = len(y)
    except Exception as e:
        per_source["youtube_error"] = str(e)

    pruned, stats = prune_discovery(all_posts)
    stats["per_source"] = per_source
    return pruned, stats


def run_discovery(search_terms=None, **kwargs):
    pruned, _ = run_discovery_with_stats(search_terms=search_terms, **kwargs)
    return pruned
