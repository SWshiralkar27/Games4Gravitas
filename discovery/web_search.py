"""#14 Wider discovery — LinkedIn, X, Threads, Facebook, Instagram via same SEARCH_PROVIDER."""
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
    return "X"

def _is_question(text: str) -> bool:
    return "?" in (text or "")

async def fetch_web_search(session: aiohttp.ClientSession):
    items = []
    if SEARCH_PROVIDER == "serper" and not SERPER_API_KEY:
        return []
    if SEARCH_PROVIDER == "brave" and not BRAVE_API_KEY:
        return []
    if SEARCH_PROVIDER == "cse" and not (GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID):
        return []
    for term in SEARCH_TERMS[:6]:
        query = f"{term} (site:linkedin.com/posts OR site:x.com OR site:twitter.com OR site:threads.net OR site:threads.com OR site:facebook.com OR site:instagram.com)"
        try:
            if SEARCH_PROVIDER == "serper":
                headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
                async with session.post("https://google.serper.dev/search", json={"q": query, "num": MAX_RESULTS_PER_SOURCE}, headers=headers, timeout=15) as r:
                    data = await r.json()
                    for row in data.get("organic", []):
                        link = row.get("link", "")
                        snip = clean_text(row.get("snippet", ""))
                        title = row.get("title", "")
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
                        plat = detect_platform(link)
                        items.append(ContentItem(plat, title, link, "Brave Search", "", snip, full_content=snip, is_question=_is_question(title + " " + snip)))
            elif SEARCH_PROVIDER == "cse":
                async with session.get("https://www.googleapis.com/customsearch/v1", params={"key": GOOGLE_CSE_API_KEY, "cx": GOOGLE_CSE_ID, "q": query, "num": MAX_RESULTS_PER_SOURCE}, timeout=15) as r:
                    data = await r.json()
                    for row in data.get("items", []):
                        link = row.get("link", "")
                        snip = clean_text(row.get("snippet", ""))
                        title = row.get("title", "")
                        plat = detect_platform(link)
                        items.append(ContentItem(plat, title, link, "Google CSE", "", snip, full_content=snip, is_question=_is_question(title + " " + snip)))
        except Exception as ex:
            log.error("Web Search failed: %s", ex)
    return items
