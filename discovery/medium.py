"""Medium - FIXED: handles missing feedparser / RSS failure gracefully, does not crash discovery."""
from __future__ import annotations
import logging
import aiohttp
from config import MEDIUM_TAGS, MAX_RESULTS_PER_SOURCE
from models import ContentItem, clean_text, truncate_at_boundary

log = logging.getLogger("digest")
HEADERS = {"User-Agent": "Mozilla/5.0 (LeadershipAIDigest)"}

async def fetch_medium(session: aiohttp.ClientSession, search_terms=None):
    items = []
    # If feedparser is not installed, return [] - web_search already covers Medium via Serper site:medium.com
    try:
        import feedparser
    except ImportError:
        log.warning("Medium: feedparser not installed, skipping RSS - web_search covers Medium via Serper")
        return []
    for tag in (MEDIUM_TAGS or []):
        try:
            async with session.get(f"https://medium.com/feed/tag/{tag}", headers=HEADERS, timeout=10) as r:
                if r.status != 200:
                    log.warning("Medium tag %s -> HTTP %s, skipping", tag, r.status)
                    continue
                text = await r.text()
            feed = feedparser.parse(text)
            for e in feed.entries[:MAX_RESULTS_PER_SOURCE]:
                body = ""
                if getattr(e, "content", None):
                    body = e.content[0].get("value", "")
                body = clean_text(body or getattr(e, "summary", ""))
                items.append(ContentItem("Medium", getattr(e, "title", ""), getattr(e, "link", ""), getattr(e, "author", ""), getattr(e, "published", ""), truncate_at_boundary(body, 300), full_content=body))
        except Exception as ex:
            log.error("Medium %s failed: %s", tag, ex)
    return items
