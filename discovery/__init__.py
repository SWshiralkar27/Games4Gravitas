"""Discovery orchestrator — #14 wider discovery via web search, no extra keys needed."""
from __future__ import annotations
import asyncio, logging
import aiohttp
from .medium import fetch_medium
from .youtube import fetch_youtube
from .web_search import fetch_web_search
log = logging.getLogger("digest")

async def run_discovery():
    async with aiohttp.ClientSession() as session:
        res = await asyncio.gather(fetch_medium(session), asyncio.to_thread(fetch_youtube), fetch_web_search(session), return_exceptions=True)
    items = []
    for r in res:
        if isinstance(r, list):
            items.extend(r)
        else:
            log.error("Discovery error: %s", r)
    return items
