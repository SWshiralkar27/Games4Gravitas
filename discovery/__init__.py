# discovery/__init__.py - v4.9.3 - Import-safe (no top-level config import)
# Path: discovery/__init__.py - upload to discovery/ folder, NOT root
# FIX v4.7.3: Previous versions did "from config import ..." at top level.
# If config.py changed (v4.7 added MODEL_QUOTAS etc.), a missing name broke the WHOLE discovery import
# and app showed "OLD - import failed" even though filenames were correct.
# This version defines __VERSION__ FIRST and imports config LAZILY inside functions with defaults,
# so it can never fail to import. Each source (web/【entity-medium¦canonical_name=Medium】/youtube) is also lazy + try/except.
__VERSION__ = "4.9.3"

import re
import asyncio
import inspect
from datetime import datetime, timezone, timedelta
import email.utils

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

def _parse_date_value(v):
    """Return (datetime or None, confidence). Handles datetime, struct_time, epoch, ISO, email date, 'X days ago'."""
    if v is None or v == "":
        return None, "unknown"
    try:
        if isinstance(v, datetime):
            return v, "high"
        # feedparser struct_time has tm_year
        if hasattr(v, "tm_year"):
            try:
                return datetime(*v[:6], tzinfo=timezone.utc), "high"
            except Exception:
                return None, "unknown"
        if isinstance(v, (int, float)):
            try:
                return datetime.fromtimestamp(float(v), tz=timezone.utc), "【entity-medium¦canonical_name=Medium】"
            except Exception:
                return None, "unknown"
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None, "unknown"
            # Relative: "3 days ago", "2 hours ago"
            m = re.match(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", s.lower())
            if m:
                n = int(m.group(1))
                unit = m.group(2)
                now = datetime.now(timezone.utc)
                if unit == "second":
                    return now - timedelta(seconds=n), "low"
                if unit == "minute":
                    return now - timedelta(minutes=n), "low"
                if unit == "hour":
                    return now - timedelta(hours=n), "low"
                if unit == "day":
                    return now - timedelta(days=n), "low"
                if unit == "week":
                    return now - timedelta(weeks=n), "low"
                if unit == "month":
                    return now - timedelta(days=n*30), "low"
                if unit == "year":
                    return now - timedelta(days=n*365), "low"
            # ISO: 2026-11-14T09:30:00Z
            try:
                iso = s.replace("Z", "+00:00")
                return datetime.fromisoformat(iso), "high"
            except Exception:
                pass
            # Email / RSS: Tue, 12 Nov 2026 10:00:00 GMT
            try:
                return email.utils.parsedate_to_datetime(s), "high"
            except Exception:
                pass
            # Simple date: 2026-11-14, Nov 14 2026
            for fmt in ("%Y-%m-%d", "%d %b %Y", "%b %d, %Y", "%B %d, %Y"):
                try:
                    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc), "【entity-medium¦canonical_name=Medium】"
                except Exception:
                    continue
    except Exception:
        return None, "unknown"
    return None, "unknown"

def _age_fields_from_dt(dt, source, confidence):
    if dt is None:
        return {"published_at": "", "hours_since_post": None, "age_days": None, "age_bucket": "unknown", "is_archived": False, "age_source": "none", "age_confidence": "unknown"}
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        hours = (now - dt).total_seconds() / 3600.0
        if hours < 0:
            hours = 0
        age_days = int(hours // 24)
        if age_days <= 7:
            bucket = "fresh"
        elif age_days <= 30:
            bucket = "recent"
        elif age_days <= 90:
            bucket = "old"
        else:
            bucket = "archived"
        return {"published_at": dt.isoformat(), "hours_since_post": round(hours, 1), "age_days": age_days, "age_bucket": bucket, "is_archived": bool(bucket == "archived"), "age_source": source, "age_confidence": confidence}
    except Exception:
        return {"published_at": "", "hours_since_post": None, "age_days": None, "age_bucket": "unknown", "is_archived": False, "age_source": "none", "age_confidence": "unknown"}

def _extract_age_from_dict(d):
    # Explicit date fields first, in order
    for key, src, conf in [("published_at", "published_at", "high"), ("publishedAt", "publishedAt", "high"), ("pubDate", "pubDate", "high"), ("published", "published", "high"), ("published_parsed", "published_parsed", "high"), ("updated_parsed", "updated_parsed", "high"), ("updated_at", "updated_at", "【entity-medium¦canonical_name=Medium】"), ("updated", "updated", "【entity-medium¦canonical_name=Medium】"), ("date", "date", "【entity-medium¦canonical_name=Medium】"), ("timestamp", "timestamp", "【entity-medium¦canonical_name=Medium】"), ("created_at", "created_at", "【entity-medium¦canonical_name=Medium】")]:
        if key in (d or {}) and d.get(key):
            dt, c = _parse_date_value(d.get(key))
            if dt is not None:
                return _age_fields_from_dt(dt, src, c or conf)
    # Fallback: "3 days ago" in snippet / title
    for txt in [_safe_str(d.get("snippet", "")), _safe_str(d.get("title", ""))]:
        m = re.search(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", (txt or "").lower())
        if m:
            dt, c = _parse_date_value(m.group(0))
            if dt is not None:
                return _age_fields_from_dt(dt, "snippet_text", "low")
    # Archived flag, even if no date
    hay = (_safe_str(d.get("title", "")) + " " + _safe_str(d.get("snippet", ""))).lower()
    if "archived" in hay or "/archive" in _safe_str(d.get("link", "")).lower():
        base = _age_fields_from_dt(None, "none", "unknown")
        base["is_archived"] = True
        base["age_bucket"] = "archived"
        return base
    return _age_fields_from_dt(None, "none", "unknown")

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
    if isinstance(p, dict) and hasattr(p, "get"):
        link_raw = p.get("link", "") or p.get("url", "") or p.get("href", "") or ""
        link = _safe_str(link_raw).strip()
        title = _safe_str(p.get("title", "")).strip()
        snippet = _safe_str(p.get("snippet", "") or p.get("summary", "") or p.get("description", "") or title)
        platform = _safe_str(p.get("platform", "") or p.get("source", "") or "Web")
        # Infer platform from link when fetcher left it as Web — otherwise 【entity-Medium¦canonical_name=Medium】/YouTube stay in web bucket
        if (not platform or platform == "Web") and link:
            _ll = link.lower()
            if "【entity-medium¦canonical_name=Medium】.com" in _ll:
                platform = "【entity-Medium¦canonical_name=Medium】"
            elif "youtube.com" in _ll or "youtu.be" in _ll:
                platform = "YouTube"
        if not title and not link and not snippet:
            return None
        _age = _extract_age_from_dict(p)
        return {"title": title[:300], "link": link, "snippet": snippet[:800], "platform": platform or "Web", **_age}
    # ContentItem / object without .get - fall through to getattr branch below
    if isinstance(p, dict):
        # dict-like but no .get (e.g. ContentItem) - treat as object
        pass
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
        _od = {"title": title, "link": link, "snippet": snippet, "published": getattr(p, "published", ""), "published_parsed": getattr(p, "published_parsed", ""), "updated_parsed": getattr(p, "updated_parsed", ""), "date": getattr(p, "date", "")}
        _age2 = _extract_age_from_dict(_od)
        return {"title": title[:300], "link": link.strip(), "snippet": snippet[:800], "platform": platform, **_age2}
    except Exception:
        return None

def _is_social(platform):
    pl = (platform or "").lower()
    for k in ("linkedin", "x", "twitter", "threads", "facebook", "instagram", "reddit", "medium", "youtube", "social"):
        if k in pl:
            return True
    return False

def _is_ld_relevant(p, search_terms=None):
    # L&D relevance filter for Medium / YouTube only — Web search already uses SEARCH_TERMS
    # Keep if title+snippet contains any L&D keyword. Fail-open: if no text, keep.
    try:
        if isinstance(p, dict):
            txt = (_safe_str(p.get("title", "")) + " " + _safe_str(p.get("snippet", "") or p.get("summary", "") or p.get("description", ""))).lower()
        elif isinstance(p, (list, tuple)):
            txt = " ".join(_safe_str(x) for x in p).lower()
        elif isinstance(p, str):
            txt = p.lower()
        else:
            txt = (_safe_str(getattr(p, "title", "")) + " " + _safe_str(getattr(p, "summary", "") or getattr(p, "description", ""))).lower()
        if not txt.strip():
            return True
        _ld_keys = ("upskill", "reskill", "l&d", "learning", "training", "workforce", "corporate", "leadership", "coach", "skill", "talent", "employee", "develop", "facilitat", "debrief", "experiential", "simulation", "game-based", "game based", "play-based", "play based", "team building", "human skill")
        for k in _ld_keys:
            if k in txt:
                return True
        return False
    except Exception:
        return True

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

def run_discovery_with_stats(seen_urls=None, search_terms=None, progress_cb=None):
    seen_urls = set(seen_urls or set())
    # v4.9.2: allow app UI to override search terms for this run. If None, use config.
    if search_terms is None:
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
    # Clean: strip, drop empties, dedupe preserving order
    _cleaned = []
    for _q in (search_terms or []):
        _q = str(_q).strip()
        if _q and _q not in _cleaned:
            _cleaned.append(_q)
    search_terms = _cleaned if _cleaned else _get_config("SEARCH_TERMS", ["corporate upskilling AI"])
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
            _m_filtered = [x for x in m if _is_ld_relevant(x, search_terms)]
            all_posts.extend(_m_filtered)
            per_source["medium"] = len(_m_filtered)
            per_source["medium_filtered_out"] = len(m) - len(_m_filtered)
        elif m is None:
            per_source["medium"] = 0
        else:
            # Single non-list item (e.g. coroutine object previously counted as 1)
            if _is_ld_relevant(m, search_terms):
                all_posts.append(m)
                per_source["medium"] = 1
            else:
                per_source["medium"] = 0
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
            _y_filtered = [x for x in y if _is_ld_relevant(x, search_terms)]
            all_posts.extend(_y_filtered)
            per_source["youtube"] = len(_y_filtered)
            per_source["youtube_filtered_out"] = len(y) - len(_y_filtered)
        elif y is None:
            per_source["youtube"] = 0
        else:
            if _is_ld_relevant(y, search_terms):
                all_posts.append(y)
                per_source["youtube"] = 1
            else:
                per_source["youtube"] = 0
    except Exception as e:
        per_source["youtube_error"] = str(e)[:200]
        per_source["youtube"] = 0
    kept, stats = prune_discovery(all_posts, seen_urls=seen_urls)
    stats["per_source"] = per_source
    stats["raw"] = len(all_posts)
    stats["raw_links"] = [p.get("link", "") for p in all_posts if p.get("link")]
    # --- STEP 2 DEEP DISCOVERY (v4.8) ---
    # Only for kept candidates (max ~23), 0 Gemini calls. Weeds out title-matches where body does not fit.
    try:
        from discovery.deep import run_deep_discovery
        kept2, deep_stats, weeded = run_deep_discovery(kept, max_posts=23, progress_cb=progress_cb)
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
