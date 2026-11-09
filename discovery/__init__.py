"""Discovery orchestrator - fixed: accepts search_terms, logs per-source counts, no silent [] on import error."""
from __future__ import annotations
import asyncio, logging
import aiohttp

log = logging.getLogger("digest")

async def run_discovery(search_terms=None, terms=None, queries=None, keywords=None, search_terms_list=None):
    """Run all discovery sources. Accepts edited terms from app.py (any param name)."""
    # app.py passes edited terms under different names - accept any of them
    _terms = search_terms or terms or queries or keywords or search_terms_list or None
    if _terms:
        # Temporarily override config SEARCH_TERMS so sub-fetchers use edited terms
        try:
            import config as _cfg
            _orig = list(getattr(_cfg, "SEARCH_TERMS", []))
            _cfg.SEARCH_TERMS[:] = list(_terms)
        except Exception:
            _orig = None
    else:
        _orig = None
    try:
        from .medium import fetch_medium
        from .youtube import fetch_youtube
        from .web_search import fetch_web_search
    except Exception as e:
        log.error("Discovery import failed: %s", e)
        # Re-raise so app.py can show the real error instead of silently returning []
        raise
    try:
        async with aiohttp.ClientSession() as session:
            # fetch_youtube is sync (requests), run it in a thread
            res = await asyncio.gather(
                fetch_medium(session),
                asyncio.to_thread(fetch_youtube),
                fetch_web_search(session),
                return_exceptions=True,
            )
        items = []
        for _name, r in zip(["Medium", "YouTube", "WebSearch"], res):
            if isinstance(r, list):
                log.info("Discovery %s returned %d items", _name, len(r))
                items.extend(r)
            else:
                log.error("Discovery %s failed: %s", _name, r)
        return items
    finally:
        # Restore original SEARCH_TERMS
        if _orig is not None:
            try:
                import config as _cfg2
                _cfg2.SEARCH_TERMS[:] = _orig
            except Exception:
                pass
