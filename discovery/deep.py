# discovery/deep.py - v4.9.2 - Step 2 Deep Discovery (0 Gemini calls)
# Path: discovery/deep.py - upload to discovery/ folder
# Step 1 (discovery/__init__.py) finds title-matches. Step 2 (this file) fetches the BODY
# for the kept candidates only (max ~23) and weeds out ones where title matched but content did not.
# - YouTube: try transcript first, then page description
# - Medium / Web: fetch page, extract main article text
# - Social (LinkedIn/X/Threads): try page fetch, but most block scraping -> keep on title if fetch fails
# Fail-open: if fetch fails or text is too short (<200 chars), KEEP on title, do NOT weed out on lack of evidence.
import re
import time
import html as _html

try:
    import requests
except Exception:
    requests = None

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except Exception:
    _HAS_BS4 = False
    BeautifulSoup = None

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _HAS_YT_API = True
except Exception:
    _HAS_YT_API = False
    YouTubeTranscriptApi = None

# Keywords that prove body is actually about our themes (case-insensitive)
DEEP_KEYWORDS = [
    "purposeful rehearsal", "rehearse before you decide", "centaur leadership",
    "human advantage", "hybrid intelligence", "gravitas",
    "upskilling", "reskilling", "l&d", "learning and development",
    "leadership", "artificial intelligence", " ai ", " ai.", "generative ai",
    "human + ai", "human-ai", "human in the loop", "judgment", "decision",
    "coaching", "rehearsal", "practice", "simulation", "role play",
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadershipDigest/4.8; +https://github.com)"}

def _clean_text(t):
    if not t:
        return ""
    t = _html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _extract_main_text(html_text):
    if not html_text:
        return ""
    if _HAS_BS4:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form", "aside"]):
                tag.decompose()
            # Prefer article / main
            main = soup.find("article") or soup.find("main") or soup.find("div", class_=re.compile(r"article|content|post|story", re.I))
            if main:
                txt = main.get_text(separator=" ", strip=True)
            else:
                txt = soup.get_text(separator=" ", strip=True)
            return _clean_text(txt)
        except Exception:
            pass
    # Fallback: regex strip tags
    try:
        txt = re.sub(r"<script.*?</script>", " ", html_text, flags=re.S | re.I)
        txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        return _clean_text(txt)
    except Exception:
        return ""

def _get_video_id(url):
    if not url:
        return ""
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{6,})", url)
    if m:
        return m.group(1)
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{6,})", url)
    if m:
        return m.group(1)
    m = re.search(r"/embed/([A-Za-z0-9_-]{6,})", url)
    if m:
        return m.group(1)
    m = re.search(r"/shorts/([A-Za-z0-9_-]{6,})", url)
    if m:
        return m.group(1)
    return ""

def _fetch_url_text(url, max_chars=6000):
    if not url or requests is None:
        return "", "no-requests-or-no-url"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=6)
        if r.status_code != 200:
            return "", f"http-{r.status_code}"
        txt = _extract_main_text(r.text)
        return txt[:max_chars], f"fetched-{len(txt)}-chars"
    except Exception as e:
        return "", f"fetch-failed: {str(e)[:80]}"

def _fetch_youtube_transcript(url, max_chars=6000):
    vid = _get_video_id(url)
    if not vid:
        return "", "no-video-id"
    if not _HAS_YT_API:
        return "", "no-transcript-api"
    try:
        # New API: list + fetch, old API: get_transcript
        try:
            ytt = YouTubeTranscriptApi()
            fetched = ytt.fetch(vid)
            parts = [s.text for s in fetched.snippets] if hasattr(fetched, "snippets") else [s["text"] for s in fetched]
        except Exception:
            # Fallback to legacy static method
            parts = [s["text"] for s in YouTubeTranscriptApi.get_transcript(vid)]
        txt = _clean_text(" ".join(parts))
        return txt[:max_chars], f"transcript-{len(txt)}-chars"
    except Exception as e:
        return "", f"transcript-failed: {str(e)[:80]}"

def deep_fetch(post):
    """Fetch body for one post. Returns (deep_text, deep_source, deep_status). Never raises."""
    try:
        url = (post.get("link") or "").strip()
        platform = (post.get("platform") or "").lower()
        title = post.get("title") or ""
        # YouTube: transcript first
        if "youtube" in platform or "youtube.com" in url or "youtu.be" in url:
            txt, status = _fetch_youtube_transcript(url)
            if txt and len(txt) >= 200:
                return txt, "youtube-transcript", status
            # Fallback: page description / main text
            txt2, status2 = _fetch_url_text(url)
            if txt2:
                return txt2, "youtube-page", f"{status} + {status2}"
            # Last fallback: use snippet as deep text (short)
            return (post.get("snippet") or ""), "snippet-fallback", "transcript+page-failed"
        # Medium / Web / Social: fetch page
        if url.startswith("http"):
            txt, status = _fetch_url_text(url)
            if txt:
                return txt, "page", status
            return (post.get("snippet") or ""), "snippet-fallback", status
        return (post.get("snippet") or ""), "snippet-only", "no-url"
    except Exception as e:
        return (post.get("snippet") or ""), "snippet-fallback", f"deep-error: {str(e)[:80]}"

def deep_filter(post, deep_text):
    """Decide keep vs weed out based on BODY, not title.
    Returns (keep_bool, reason).
    - If deep text <200 chars: KEEP (not enough evidence to weed out)
    - If deep text >=200 and contains NONE of DEEP_KEYWORDS: WEED OUT
    - Else: KEEP
    """
    txt = (deep_text or "").strip()
    if len(txt) < 200:
        return True, "deep short (<200 chars) - kept on title"
    low = " " + txt.lower() + " "
    found = []
    for kw in DEEP_KEYWORDS:
        # For short kws like " ai ", we already padded; for others, simple contains
        if kw.lower() in low:
            found.append(kw)
    if not found:
        return False, "WEED OUT - title matched but body has no AI/leadership/book-theme keywords"
    # Show up to 3 found keywords in reason
    return True, f"deep confirms - found: {', '.join(found[:3])}"

def run_deep_discovery(kept_posts, max_posts=23, progress_cb=None):
    """Step 2: for each kept post, fetch body + filter. Returns (kept_after_deep, deep_stats)."""
    kept = kept_posts or []
    # Only deep-check first max_posts (they are already sorted social/question first)
    to_check = kept[:max_posts]
    rest = kept[max_posts:] if len(kept) > max_posts else []
    kept_after = []
    weeded = []
    checked = 0
    failed = 0
    import time as _time2
    _deep_start = _time2.time()
    for p in to_check:
        # v4.9.2: total Deep budget 60s - if exceeded, keep remaining on title, do not hang user
        if _time2.time() - _deep_start > 60:
            for _rp in to_check[checked:]:
                _rp["_deep_source"] = "skipped-budget"
                _rp["_deep_status"] = "Deep budget 60s exceeded - kept on title"
                _rp["_deep_reason"] = "kept - Deep budget exceeded"
                _rp["_deep_len"] = 0
                _rp["_deep_text"] = ""
                kept_after.append(_rp)
            break
        checked += 1
        if progress_cb:
            try:
                progress_cb(checked, len(to_check))
            except Exception:
                pass
        try:
            deep_text, deep_source, deep_status = deep_fetch(p)
            keep, reason = deep_filter(p, deep_text)
            # Attach deep info to post for display in Step 2 expander
            p["_deep_source"] = deep_source
            p["_deep_status"] = deep_status
            p["_deep_reason"] = reason
            p["_deep_len"] = len(deep_text or "")
            # Keep a truncated deep text for Assess to use (Assess will use title+snippet+deep snippet)
            p["_deep_text"] = (deep_text or "")[:2500]
            if keep:
                kept_after.append(p)
            else:
                weeded.append({**p, "_weed_reason": reason})
        except Exception as e:
            failed += 1
            p["_deep_source"] = "error"
            p["_deep_status"] = f"error: {str(e)[:80]}"
            p["_deep_reason"] = "deep error - kept on title"
            p["_deep_len"] = 0
            p["_deep_text"] = ""
            kept_after.append(p)
        # Small delay to avoid hammering
        try:
            time.sleep(0.2)
        except Exception:
            pass
    # Rest beyond max_posts: keep as-is, no deep check
    for p in rest:
        p["_deep_source"] = "skipped"
        p["_deep_status"] = "not-deep-checked (beyond max)"
        p["_deep_reason"] = "kept - beyond deep limit"
        p["_deep_len"] = 0
        p["_deep_text"] = ""
        kept_after.append(p)
    stats = {
        "deep_checked": checked,
        "deep_kept": len(kept_after),
        "deep_weeded": len(weeded),
        "deep_failed": failed,
        "deep_weeded_titles": [w.get("title","")[:80] for w in weeded],
    }
    return kept_after, stats, weeded
