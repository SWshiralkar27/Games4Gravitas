"""Web search - FIXED: uses simple Serper queries like the fallback, not parenthesised OR which returns 0."""
from __future__ import annotations
import logging
import aiohttp
from config import SEARCH_PROVIDER, SERPER_API_KEY, BRAVE_API_KEY, GOOGLE_CSE_API_KEY, GOOGLE_CSE_ID, SEARCH_TERMS, MAX_RESULTS_PER_SOURCE
from models import ContentItem, clean_text

log = logging.getLogger("digest")

def detect_platform(link: str) -> str:
    l = (link or "").lower()
    if "threads" in l:
        return "Threads"
    if "facebook.com" in l:
        return "Facebook"
    if "instagram.com" in l:
        return "Instagram"
    if "linkedin.com" in l:
        return "LinkedIn"
    if "x.com" in l or "twitter.com" in l:
        return "X"
    if "medium.com" in l:
        return "Medium"
    if "youtube.com" in l or "youtu.be" in l:
        return "YouTube"
    # Do NOT default to X - that mislabels generic web articles as X posts
    try:
        from urllib.parse import urlparse as _up
        _dom = _up(link).netloc.replace("www.", "")
        return f"Web - {_dom}" if _dom else "Web"
    except Exception:
        return "Web"

def _is_question(text: str) -> bool:
    return "?" in (text or "")

async def fetch_web_search(session: aiohttp.ClientSession, search_terms=None):
    items = []
    terms = list(search_terms) if search_terms else list(SEARCH_TERMS)
    if not terms:
        log.warning("fetch_web_search: no SEARCH_TERMS")
        return []
    if SEARCH_PROVIDER == "serper" and not SERPER_API_KEY:
        log.warning("fetch_web_search: SERPER_API_KEY missing")
        return []
    if SEARCH_PROVIDER == "brave" and not BRAVE_API_KEY:
        return []
    if SEARCH_PROVIDER == "cse" and not (GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID):
        return []
    # Use the SAME queries as the fallback that works: plain + site: filters, each num=5
    # Old code used: "term (site:linkedin.com/posts OR site:x.com ...)" - Serper returns 0 for that syntax.
    queries = []
    for term in terms[:3]:
        queries.append(term)
        queries.append(f"{term} site:linkedin.com")
        queries.append(f"{term} site:youtube.com")
        queries.append(f"{term} site:medium.com")
    for term in terms[3:5]:
        queries.append(term)
    queries = queries[:8]
    for query in queries:
        try:
            if SEARCH_PROVIDER == "serper":
                headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
                async with session.post("https://google.serper.dev/search", json={"q": query, "num": MAX_RESULTS_PER_SOURCE}, headers=headers, timeout=15) as r:
                    if r.status != 200:
                        log.error("Serper %s -> HTTP %s", query, r.status)
                        continue
                    data = await r.json()
                    for row in data.get("organic", []):
                        link = row.get("link", "")
                        snip = clean_text(row.get("snippet", ""))
                        title = row.get("title", "")
                        if not link or not title:
                            continue
                        plat = detect_platform(link)
                        items.append(ContentItem(plat, title, link, "Serper Search", "", snip, full_content=snip, is_question=_is_question(title + " " + snip)))
            elif SEARCH_PROVIDER == "brave":
                headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}
                async with session.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": MAX_RESULTS_PER_SOURCE}, headers=headers, timeout=15) as r:
                    data = await r.json()
                    for row in data.get("web", {}).get("results", []):
                        link = row.get("url", "")
                        snip = clean_text(row.get("description", ""))
                        title = row.get("title", "")
                        if not link or not title:
                            continue
                        plat = detect_platform(link)
                        items.append(ContentItem(plat, title, link, "Brave Search", "", snip, full_content=snip, is_question=_is_question(title + " " + snip)))
            elif SEARCH_PROVIDER == "cse":
                async with session.get("https://www.googleapis.com/customsearch/v1", params={"key": GOOGLE_CSE_API_KEY, "cx": GOOGLE_CSE_ID, "q": query, "num": MAX_RESULTS_PER_SOURCE}, timeout=15) as r:
                    data = await r.json()
                    for row in data.get("items", []):
                        link = row.get("link", "")
                        snip = clean_text(row.get("snippet", ""))
                        title = row.get("title", "")
                        if not link or not title:
                            continue
                        plat = detect_platform(link)
                        items.append(ContentItem(plat, title, link, "Google CSE", "", snip, full_content=snip, is_question=_is_question(title + " " + snip)))
        except Exception as ex:
            log.error("Web Search query '%s' failed: %s", query, ex)
    log.info("fetch_web_search returned %d items from %d queries", len(items), len(queries))
    return items
