from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
import requests
from config import YOUTUBE_API_KEY, SEARCH_TERMS, MAX_RESULTS_PER_SOURCE, DAYS_BACK
from models import ContentItem, clean_text, truncate_at_boundary
log = logging.getLogger("digest")

def _hours_since(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    except Exception:
        return 9999.0

def fetch_youtube():
    if not YOUTUBE_API_KEY:
        return []
    items = []
    published_after = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for term in SEARCH_TERMS[:4]:
        try:
            resp = requests.get("https://www.googleapis.com/youtube/v3/search", params={"part": "snippet", "q": term, "type": "video", "order": "date", "publishedAfter": published_after, "maxResults": MAX_RESULTS_PER_SOURCE, "key": YOUTUBE_API_KEY}, timeout=15)
            resp.raise_for_status()
            for it in resp.json().get("items", []):
                sn = it.get("snippet", {})
                vid = it.get("id", {}).get("videoId", "")
                is_short = "#shorts" in sn.get("title", "").lower() or "#shorts" in sn.get("description", "").lower()
                platform = "YouTube Shorts" if is_short else "YouTube"
                link = f"https://www.youtube.com/shorts/{vid}" if is_short else f"https://www.youtube.com/watch?v={vid}"
                desc = clean_text(sn.get("description", ""))
                title = sn.get("title", "")
                items.append(ContentItem(platform, title, link, sn.get("channelTitle", ""), sn.get("publishedAt", ""), truncate_at_boundary(desc, 300), full_content=desc, hours_since_post=_hours_since(sn.get("publishedAt", "")), is_question=("?" in title or "?" in desc)))
        except Exception as ex:
            log.error("YouTube failed: %s", ex)
    return items
