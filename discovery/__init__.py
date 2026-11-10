# discovery/__init__.py - v4.7.3 - Import-safe (no top-level config import)
# Path: discovery/__init__.py - upload to discovery/ folder, NOT root
# FIX v4.7.3: Previous versions did "from config import ..." at top level.
# If config.py changed (v4.7 added MODEL_QUOTAS etc.), a missing name broke the WHOLE discovery import
# and app showed "OLD - import failed" even though filenames were correct.
# This version defines __VERSION__ FIRST and imports config LAZILY inside functions with defaults,
# so it can never fail to import. Each source (web/medium/youtube) is also lazy + try/except.
__VERSION__ = "4.8"

import re
import asyncio
import inspect

def _get_config(name, default):
    try:
        import config as _c
        return getattr(_c, name, default)
    except Exception:
        return default

def _safe_str(x):
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, (list, tuple)):
        return " ".join(_safe_str(i) for i in x)
    try:
        return str(x)
    except Exception:
        return ""

def _normalize_post(p):
    # Returns dict or None (drop)
    if p is None:
        return None
    if isinstance(p, str):
        s = p.strip()
        if not s:
            return None
        return {"title": s[:300], "link": "", "snippet": s[:800], "platform": "Web"}
    if isinstance(p, (list, tuple)):
        if len(p) == 0:
            return None
        title = _safe_str(p[0]) if len(p) > 0 else ""
        link = _safe_str(p[1]) if len(p) > 1 else ""
        snippet = _safe_str(p[2]) if len(p) > 2 else title
        return {"title": title[:300], "link": link.strip(), "snippet": snippet[:800], "platform": "Web"}
    if isinstance(p, dict):
        link_raw = p.get("link", "") or p.get("url", "") or p.get("href", "") or ""
        link = _safe_str(link_raw).strip()
        title = _safe_str(p.get("title", "")).strip()
        snippet = _safe_str(p.get("snippet", "") or p.get("summary", "") or p.get("description", "") or title)
        platform = _safe_str(p.get("platform", "") or p.get("source", "") or "Web")
        if not title and not link and not snippet:
            return None
        return {"title": title[:300], "link": link, "snippet": snippet[:800], "platform": platform or "Web"}
    # feedparser object or generic object with .title / .link / .summary
    try:
        title = _safe_str(getattr(p, "title", "")) if hasattr(p, "title") else ""
        link = _safe_str(getattr(p, "link", "")) if hasattr(p, "link") else ""
        snippet = _safe_str(getattr(p, "summary", "") or getattr(p, "description", "") or title)
        platform = "Web"
        if not title and not link:
            return None
        return {"title": title[:300], "link": link.strip(), "snippet": snippet[:800], "platform": platform}
    except Exception:
        return None

def _is_social(platform):
    pl = (platform or "").lower()
    for k in ("linkedin", "x", "twitter", "threads", "facebook", "instagram", "reddit", "social"):
        if k in pl:
            return True
    return False

def prune_discovery(all_posts, seen_urls=None):
    seen_urls = set(seen_urls or set())
    norm = []
    invalid_skipped = 0
    for item in (all_posts or []):
        # Handle coroutine that was never awaited (old async medium.py)
        if inspect.iscoroutine(item):
            try:
                item = asyncio.run(item)
            except Exception:
                invalid_skipped += 1
                continue
        n = _normalize_post(item)
        if n is None:
            invalid_skipped += 1
            continue
        norm.append(n)
    # Seen filter
    seen_filtered = 0
    filtered = []
    for p in norm:
        if p.get("link") and p["link"] in seen_urls:
            seen_filtered += 1
            continue
        filtered.append(p)
    # Dedupe by URL + idea (title lower)
    seen_links = set()
    seen_titles = set()
    deduped = []
    for p in filtered:
        link = (p.get("link") or "").strip()
        title_key = re.sub(r"\W+", " ", (p.get("title") or "").lower()).strip()[:120]
        if link and link in seen_links:
            continue
        if title_key and title_key in seen_titles and link:
            continue
        if link:
            seen_links.add(link)
        if title_key:
            seen_titles.add(title_key)
        deduped.append(p)
    # Split social vs web
    social = [p for p in deduped if _is_social(p.get("platform", ""))]
    web = [p for p in deduped if not _is_social(p.get("platform", ""))]
    # Pruning rules (same as v4.5/v4.6)
    # If >=8 social, drop all web. If some social, keep max 5 web. If only web, keep max 15 best web, mark auto-skip.
    if len(social) >= 8:
        web_pruned = len(web)
        web_kept = []
    elif len(social) > 0:
        web_kept = web[:5]
        web_pruned = max(0, len(web) - len(web_kept))
    else:
        web_kept = web[:15]
        web_pruned = max(0, len(web) - len(web_kept))
        for p in web_kept:
            p["_auto_skip"] = True
    # Sort social / question / recent first - simple: social first, then title with ? first
    def _sort_key(p):
        is_q = 1 if "?" in (p.get("title") or "") else 0
        is_social = 1 if _is_social(p.get("platform", "")) else 0
        return (-is_social, -is_q)
    combined = social + web_kept
    combined = sorted(combined, key=_sort_key)
    max_assess = _get_config("MAX_POSTS_TO_ASSESS", 30)
    try:
        max_assess = int(max_assess)
    except Exception:
        max_assess = 30
    kept = combined[:max_assess]
    stats = {
        "raw": len(all_posts or []),
        "invalid_skipped": invalid_skipped,
        "seen_filtered": seen_filtered,
        "deduped": len(deduped),
        "social": len(social),
        "web_pruned": web_pruned,
        "kept_for_assessment": len(kept),
        "fallback": False,
    }
    return kept, stats

def run_discovery_with_stats(seen_urls=None):
    seen_urls = set(seen_urls or set())
    search_terms = _get_config("SEARCH_TERMS", [
        "corporate upskilling AI",
        "AI upskilling program",
        "L&D AI training",
        "reskilling workforce AI",
        "corporate upskilling AI site:linkedin.com",
        "AI upskilling program site:x.com",
        "L&D AI training site:threads.net",
        "reskilling workforce AI site:linkedin.com",
    ])
    max_per = _get_config("MAX_RESULTS_PER_SOURCE", 5)
    try:
        max_per = int(max_per)
    except Exception:
        max_per = 5
    all_posts = []
    per_source = {}
    # Web search - lazy import
    web_total = 0
    try:
        from discovery.web_search import search_web
        web_queries = {}
        for q in (search_terms or []):
            try:
                res = search_web(q, max_per)
                if inspect.iscoroutine(res):
                    res = asyncio.run(res)
                if isinstance(res, list):
                    all_posts.extend(res)
                    web_total += len(res)
                    web_queries[str(q)] = len(res)
            except Exception as e:
                web_queries[str(q)] = f"err: {str(e)[:60]}"
        per_source["web_search"] = web_total
        per_source["web_queries"] = web_queries
    except Exception as e:
        per_source["web_search_error"] = str(e)[:200]
    # Medium - lazy, handles sync + async
    try:
        from discovery.medium import fetch_medium
        try:
            m = fetch_medium()
        except TypeError:
            try:
                m = fetch_medium(None)
            except TypeError:
                m = fetch_medium(session=None)
        if inspect.iscoroutine(m):
            try:
                m = asyncio.run(m)
            except Exception:
                m = []
        if isinstance(m, list):
            all_posts.extend(m)
            per_source["medium"] = len(m)
        elif m is None:
            per_source["medium"] = 0
        else:
            # Single non-list item (e.g. coroutine object previously counted as 1)
            all_posts.append(m)
            per_source["medium"] = 1
    except Exception as e:
        per_source["medium_error"] = str(e)[:200]
        per_source["medium"] = 0
    # YouTube - lazy
    try:
        from discovery.youtube import fetch_youtube
        try:
            y = fetch_youtube()
        except TypeError:
            try:
                y = fetch_youtube(None)
            except TypeError:
                y = fetch_youtube(session=None)
        if inspect.iscoroutine(y):
            try:
                y = asyncio.run(y)
            except Exception:
                y = []
        if isinstance(y, list):
            all_posts.extend(y)
            per_source["youtube"] = len(y)
        elif y is None:
            per_source["youtube"] = 0
        else:
            all_posts.append(y)
            per_source["youtube"] = 1
    except Exception as e:
        per_source["youtube_error"] = str(e)[:200]
        per_source["youtube"] = 0
    kept, stats = prune_discovery(all_posts, seen_urls=seen_urls)
    stats["per_source"] = per_source
    stats["raw"] = len(all_posts)
    # --- STEP 2 DEEP DISCOVERY (v4.8) ---
    # Only for kept candidates (max ~23), 0 Gemini calls. Weeds out title-matches where body does not fit.
    try:
        from discovery.deep import run_deep_discovery
        kept2, deep_stats, weeded = run_deep_discovery(kept, max_posts=23)
        stats["deep_checked"] = deep_stats.get("deep_checked", 0)
        stats["deep_kept"] = deep_stats.get("deep_kept", len(kept2))
        stats["deep_weeded"] = deep_stats.get("deep_weeded", 0)
        stats["deep_weeded_titles"] = deep_stats.get("deep_weeded_titles", [])
        stats["kept_for_assessment"] = len(kept2)
        # Keep weeded list in stats for app to show
        stats["deep_weeded_posts"] = [{"title": w.get("title","")[:120], "link": w.get("link",""), "reason": w.get("_weed_reason","")} for w in weeded]
        return kept2, stats
    except Exception as e:
        stats["deep_checked"] = 0
        stats["deep_weeded"] = 0
        stats["deep_error"] = str(e)[:200]
        return kept, stats
