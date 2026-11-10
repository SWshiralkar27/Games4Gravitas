"""YouTube - FIXED: if no YOUTUBE_API_KEY, return [] cleanly. Web search covers YouTube via Serper site:youtube.com."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
import requests
from config import YOUTUBE_API_KEY, SEARCH_TERMS, MAX_RESULTS_PER_SOURCE, DAYS_BACK
from models import clean_text, truncate_at_boundary

log = logging.getLogger("digest")

def _hours_since(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    except Exception:
        return 9999.0

def fetch_youtube(search_terms=None):
    if not YOUTUBE_API_KEY:
        log.info("YouTube: no YOUTUBE_API_KEY, skipping - web_search covers YouTube via Serper")
        return []
    terms = list(search_terms) if search_terms else list(SEARCH_TERMS)
    items = []
    published_after = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for term in terms[:4]:
        try:
            resp = requests.get("https://www.googleapis.com/youtube/v3/search", params={"part": "snippet", "q": term, "type": "video", "order": "date", "publishedAfter": published_after, "maxResults": MAX_RESULTS_PER_SOURCE, "key": YOUTUBE_API_KEY}, timeout=15)
            resp.raise_for_status()
            for it in resp.json().get("items", []):
                sn = it.get("snippet", {})
                vid = it.get("id", {}).get("videoId", "")
                if not vid:
                    continue
                is_short = "#shorts" in sn.get("title", "").lower() or "#shorts" in sn.get("description", "").lower()
                platform = "YouTube Shorts" if is_short else "YouTube"
                link = f"https://www.youtube.com/shorts/{vid}" if is_short else f"https://www.youtube.com/watch?v={vid}"
                desc = clean_text(sn.get("description", ""))
                title = sn.get("title", "")
                items.append({"title": title, "link": link, "snippet": truncate_at_boundary(desc, 300), "platform": platform, "source": "youtube", "comments": 0})
        except Exception as ex:
            log.error("YouTube term '%s' failed: %s", term, ex)
    return items
