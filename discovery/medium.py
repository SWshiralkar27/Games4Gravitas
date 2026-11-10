"""discovery/medium.py — v4.6
FIX for: RuntimeWarning: coroutine 'fetch_medium' was never awaited

Root cause: the medium.py on GitHub was `async def fetch_medium(...)`,
but discovery/__init__.py calls it as a sync function `fetch_medium()`.
An async function returns a coroutine, not a list. That coroutine was
counted as `medium: 1` and then dropped as `invalid_skipped: 1`.
So Medium returned 0 real posts.

Fix: this file is SYNC — `def fetch_medium`, NOT `async def`.
Do NOT change it back to `async def`. If you see `async def fetch_medium`
in your file, that is the bug.

Accepts: fetch_medium(), fetch_medium(None), fetch_medium(session),
fetch_medium(session=...). Never raises, returns [] on failure.
"""
import re

try:
    from config import MEDIUM_TAGS
except Exception:
    MEDIUM_TAGS = "leadership,artificial-intelligence,ai,future-of-work"


def _clean(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:800]


def fetch_medium(session=None, search_terms=None, terms=None, **kwargs):
    # If caller passed a list as first arg, treat it as terms, not session
    if isinstance(session, (list, tuple)):
        search_terms = list(session)
        session = None
    tags = [t.strip() for t in str(MEDIUM_TAGS).split(",") if t.strip()]
    urls = [f"https://medium.com/feed/tag/{tag}" for tag in tags[:3]]
    posts = []
    try:
        import feedparser
        has_feedparser = True
    except Exception:
        has_feedparser = False
    http_get = None
    if session is not None and hasattr(session, "get"):
        http_get = session.get
    for feed_url in urls:
        try:
            if has_feedparser:
                feed = feedparser.parse(feed_url)
                entries = getattr(feed, "entries", []) or []
                for e in entries[:5]:
                    title = _clean(getattr(e, "title", "") or "")
                    link = getattr(e, "link", "") or ""
                    snippet = _clean(getattr(e, "summary", "") or getattr(e, "description", "") or "")
                    if not title or not link:
                        continue
                    posts.append({"title": title, "link": link, "snippet": snippet, "platform": "Medium", "source": "medium", "comments": 0})
            else:
                import requests
                if http_get is not None:
                    r = http_get(feed_url, timeout=15)
                else:
                    r = requests.get(feed_url, timeout=15)
                if getattr(r, "status_code", 200) != 200:
                    continue
                text = getattr(r, "text", "") or ""
                for m in re.finditer(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?(?:<description>(.*?)</description>)?", text, re.S)[:5]:
                    title = _clean(m.group(1))
                    link = (m.group(2) or "").strip()
                    snippet = _clean(m.group(3) or "")
                    if title and link:
                        posts.append({"title": title, "link": link, "snippet": snippet, "platform": "Medium", "source": "medium", "comments": 0})
        except Exception:
            continue
        if len(posts) >= 15:
            break
    return posts[:15]
