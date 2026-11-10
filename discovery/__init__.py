"""discovery/__init__.py — v4.4
__VERSION__ = "4.4" — if you do NOT see this line on GitHub, you are still on the OLD file.
FIXES for 2026-11-10 Run crash:
  AttributeError at prune_discovery line 68:
    url = (p.get("link") or "").strip()...
  Cause: not every source returns a dict. Medium / YouTube can return
  a str, None, a list/tuple, or a feedparser entry / object with
  attributes instead of .get(). Calling p.get() on those crashes
  the whole Run.

  Fix: _normalize_post() coerces EVERY raw item to a dict (or drops it)
  BEFORE prune touches .get(). prune_discovery never calls .get()
  on an un-normalised item. _safe_str() coerces link/title/snippet
  that are list/dict/int/None to "" / str, so .strip() never crashes.

Also: seen_posts filtering (seen_urls / seen_links) — app.py passes the
uploaded seen_posts.txt set, and discovery drops those URLs/titles
before pruning, with stats seen_filtered.
"""
import re

__VERSION__ = "4.4"

from config import (
    MAX_POSTS_TO_ASSESS,
    MAX_WEB_ARTICLES_IF_ONLY_WEB,
    MAX_WEB_ARTICLES_IF_SOCIAL_EXISTS,
    MAX_WEB_ARTICLES_IF_SOME_SOCIAL,
    MIN_SOCIAL_TO_DROP_WEB,
    SOCIAL_PLATFORMS,
)


def _safe_str(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        # e.g. link stored as [url] — take first string element
        for item in v:
            if isinstance(item, str) and item.strip():
                return item
        return ""
    if isinstance(v, dict):
        # e.g. {'href': 'https://...'} or {'url': '...'}
        for k in ("href", "url", "link", "value", "text"):
            if k in v and isinstance(v[k], str):
                return v[k]
        return ""
    # feedparser / object / anything else
    try:
        return str(v)
    except Exception:
        return ""


def _norm_text(s):
    return re.sub(r"[^a-z0-9]+", " ", _safe_str(s).lower()).strip()


def _normalize_post(raw):
    """Coerce any raw source item -> dict or None (drop). Never raises."""
    if raw is None:
        return None
    # Plain string: treat as title/snippet, no link
    if isinstance(raw, str):
        t = raw.strip()
        if not t:
            return None
        return {"title": t[:500], "link": "", "snippet": t[:1500],
                "platform": "Web - unknown", "source": "string", "comments": 0}
    # list / tuple: (title, link) or (link, title) or [dict]
    if isinstance(raw, (list, tuple)):
        if len(raw) == 0:
            return None
        # [dict] case
        if len(raw) == 1 and isinstance(raw[0], dict):
            return _normalize_post(raw[0])
        parts = [_safe_str(x) for x in raw]
        title, link = "", ""
        for part in parts:
            if part.startswith("http"):
                link = part
            elif part and not title:
                title = part
        if not title and not link:
            return None
        return {"title": title[:500], "link": link, "snippet": " ".join(parts)[:1500],
                "platform": "Web - unknown", "source": "list", "comments": 0}
    # dict: normal case
    if isinstance(raw, dict):
        link = _safe_str(raw.get("link") or raw.get("url") or raw.get("href") or "")
        title = _safe_str(raw.get("title") or raw.get("name") or raw.get("headline") or "")
        snippet = _safe_str(raw.get("snippet") or raw.get("description") or raw.get("summary") or raw.get("text") or "")
        platform = _safe_str(raw.get("platform") or raw.get("source_platform") or "")
        if not platform:
            platform = "Web - unknown"
        try:
            comments = int(raw.get("comments") or raw.get("comment_count") or 0)
        except Exception:
            comments = 0
        out = dict(raw)
        out.update({"title": title, "link": link, "snippet": snippet,
                    "platform": platform, "comments": comments})
        # Keep any extra keys, but ensure the 3 critical ones are strings
        return out
    # Object with attributes (feedparser entry, YouTube resource, etc.)
    try:
        link = _safe_str(getattr(raw, "link", "") or getattr(raw, "url", "") or getattr(raw, "href", ""))
        title = _safe_str(getattr(raw, "title", "") or getattr(raw, "name", ""))
        snippet = _safe_str(getattr(raw, "summary", "") or getattr(raw, "description", "") or getattr(raw, "snippet", ""))
        platform = _safe_str(getattr(raw, "platform", "") or "")
        if not title and not link and not snippet:
            return None
        return {"title": title[:500], "link": link, "snippet": snippet[:1500],
                "platform": platform or "Web - unknown", "source": "object", "comments": 0}
    except Exception:
        return None


def _is_social(post):
    return (post.get("platform") or "") in SOCIAL_PLATFORMS


def _is_web(post):
    p = (post.get("platform") or "")
    return p.startswith("Web -") or p in ("Medium", "YouTube")


def _heuristic_sort_key(post):
    title = ((post.get("title", "") or "") + " " + (post.get("snippet", "") or "")).lower()
    score = 0
    if _is_social(post):
        score += 50
    if "?" in (post.get("title", "") or "") or "?" in (post.get("snippet", "") or ""):
        score += 20
    if any(w in title for w in ["how", "should", "what", "why", "ai", "leadership", "team", "upskill"]):
        score += 10
    try:
        comments = int(post.get("comments", 0) or 0)
    except Exception:
        comments = 0
    if 5 <= comments <= 30:
        score += 15
    elif comments > 80:
        score -= 10
    if _is_web(post):
        score -= 30
    return -score


def _extract_seen_keys(seen_urls):
    """seen_urls may be set/list of URLs, titles, or 'title | url' lines."""
    keys_url, keys_title = set(), set()
    for item in (seen_urls or []):
        s = _safe_str(item).strip().lower()
        if not s:
            continue
        m = re.search(r"https?://[^\s|]+", s)
        if m:
            keys_url.add(m.group(0).rstrip("/"))
        # Also store normalised title part (before |, or whole line if no URL)
        title_part = s.split("|")[0].strip()
        if title_part and not title_part.startswith("http"):
            keys_title.add(_norm_text(title_part)[:120])
        elif not m:
            keys_title.add(_norm_text(s)[:120])
    return keys_url, keys_title


def prune_discovery(posts, seen_urls=None):
    """Input: raw list (any types). Output: (pruned_list, stats). Never crashes on bad items."""
    raw_in = len(posts or [])
    # 1. Normalise EVERYTHING first — this is the crash fix
    normalised = []
    invalid = 0
    for p in (posts or []):
        try:
            n = _normalize_post(p)
        except Exception:
            n = None
        if n is None:
            invalid += 1
        else:
            normalised.append(n)

    # 2. Drop seen posts (from seen_posts.txt)
    seen_url_keys, seen_title_keys = _extract_seen_keys(seen_urls)
    kept, seen_filtered = [], 0
    for p in normalised:
        url_key = _safe_str(p.get("link", "")).strip().lower().rstrip("/")
        title_key = _norm_text(p.get("title", ""))[:120]
        if (url_key and url_key in seen_url_keys) or (title_key and title_key in seen_title_keys):
            seen_filtered += 1
            continue
        kept.append(p)
    normalised = kept

    # 3. Dedupe by URL, then by idea (normalised title) — all .get() are safe now
    seen_url, seen_idea, deduped = set(), set(), []
    for p in normalised:
        url = _safe_str(p.get("link", "")).strip().lower().rstrip("/")
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
        web_keep_limit = MAX_WEB_ARTICLES_IF_SOCIAL_EXISTS
    elif len(social) > 0:
        web_keep_limit = MAX_WEB_ARTICLES_IF_SOME_SOCIAL
    else:
        web_keep_limit = MAX_WEB_ARTICLES_IF_ONLY_WEB

    social_sorted = sorted(social, key=_heuristic_sort_key)
    web_sorted = sorted(web, key=_heuristic_sort_key)
    other_sorted = sorted(other, key=_heuristic_sort_key)

    web_kept = web_sorted[:web_keep_limit]
    web_pruned = len(web_sorted) - len(web_kept)

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
        "raw": raw_in,
        "invalid_skipped": invalid,
        "seen_filtered": seen_filtered,
        "deduped": len(deduped),
        "social": len(social),
        "web_total": len(web),
        "web_kept": len(web_kept),
        "web_pruned": web_pruned,
        "kept_for_assessment": len(pruned),
        "pruned_total": raw_in - len(pruned),
    }
    return pruned, stats


def _as_list(v):
    """Coerce a source return value to a list. Handles list/dict/single/str."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, tuple):
        return list(v)
    if isinstance(v, dict):
        # {'posts': [...]} or single post dict
        for k in ("posts", "items", "results", "data"):
            if k in v and isinstance(v[k], list):
                return v[k]
        return [v]
    return [v]


def run_discovery_with_stats(search_terms=None, book_themes=None, seen_urls=None, seen_links=None, **kwargs):
    terms = search_terms or kwargs.get("terms") or kwargs.get("search") or []
    # Accept both names for seen
    seen = seen_urls if seen_urls is not None else seen_links
    if seen is None:
        seen = kwargs.get("seen_posts") or kwargs.get("seen") or []
    all_posts = []
    per_source = {}
    try:
        from discovery.web_search import search_web
        web_posts, web_counts = search_web(terms)
        web_posts = _as_list(web_posts)
        all_posts.extend(web_posts)
        per_source["web_search"] = len(web_posts)
        per_source["web_queries"] = web_counts
    except Exception as e:
        per_source["web_search_error"] = str(e)
    try:
        from discovery.medium import fetch_medium
        m = _as_list(fetch_medium())
        all_posts.extend(m)
        per_source["medium"] = len(m)
    except Exception as e:
        per_source["medium_error"] = str(e)
    try:
        from discovery.youtube import fetch_youtube
        y = _as_list(fetch_youtube(terms))
        all_posts.extend(y)
        per_source["youtube"] = len(y)
    except Exception as e:
        per_source["youtube_error"] = str(e)

    pruned, stats = prune_discovery(all_posts, seen_urls=seen)
    stats["per_source"] = per_source
    return pruned, stats


def run_discovery(search_terms=None, **kwargs):
    pruned, _ = run_discovery_with_stats(search_terms=search_terms, **kwargs)
    return pruned
