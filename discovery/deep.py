# discovery/deep.py - v4.9.4 - Step 2 Deep Discovery with Blog & Commentability Guardrails
# Path: discovery/deep.py - upload to discovery/ folder
# Step 1 (discovery/__init__.py) finds title-matches. Step 2 (this file) fetches the BODY
# and checks commentability for kept candidates only (max ~23) and weeds out static blogs,
# closed comments, and locked threads.
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

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadershipDigest/4.9; +https://github.com)"}

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
            main = soup.find("article") or soup.find("main") or soup.find("div", class_=re.compile(r"article|content|post|story", re.I))
            if main:
                txt = main.get_text(separator=" ", strip=True)
            else:
                txt = soup.get_text(separator=" ", strip=True)
            return _clean_text(txt)
        except Exception:
            pass
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

def classify_platform_from_url(url: str, declared_platform: str) -> str:
    """Detects static corporate blogs and vendor articles mislabeled as social networks."""
    u = (url or "").lower()
    if any(b in u for b in ["/blog/", ".com/blog/", "whatfix.com", "hubspot.com", "wordpress.com", "medium.com/@"]):
        return "Web - Blog"
    if "x.com" in u or "twitter.com" in u:
        return "X"
    if "linkedin.com" in u:
        return "LinkedIn"
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    return declared_platform

def _fetch_url_data(url, max_chars=6000):
    """Fetches both raw HTML and extracted clean text for validation."""
    if not url or requests is None:
        return "", "", "no-requests-or-no-url"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=6)
        if r.status_code != 200:
            return "", "", f"http-{r.status_code}"
        raw_html = r.text
        txt = _extract_main_text(raw_html)
        return raw_html, txt[:max_chars], f"fetched-{len(txt)}-chars"
    except Exception as e:
        return "", "", f"fetch-failed: {str(e)[:80]}"

def _fetch_youtube_transcript(url, max_chars=6000):
    vid = _get_video_id(url)
    if not vid:
        return "", "no-video-id"
    if not _HAS_YT_API:
        return "", "no-transcript-api"
    try:
        try:
            ytt = YouTubeTranscriptApi()
            fetched = ytt.fetch(vid)
            parts = [s.text for s in fetched.snippets] if hasattr(fetched, "snippets") else [s["text"] for s in fetched]
        except Exception:
            parts = [s["text"] for s in YouTubeTranscriptApi.get_transcript(vid)]
        txt = _clean_text(" ".join(parts))
        return txt[:max_chars], f"transcript-{len(txt)}-chars"
    except Exception as e:
        return "", f"transcript-failed: {str(e)[:80]}"

def _is_commentable(url, html_text, platform):
    """Checks if a page or video allows commenting based on text indicators and DOM structure."""
    u = (url or "").lower()
    html_low = (html_text or "").lower()

    # 0. Static Blog / Website Check (Blogs do not have interactive comment threads for social marketing)
    if platform == "web - blog" or "/blog/" in u or "whatfix.com" in u:
        return False, "WEED OUT - Static corporate blog / non-interactive web page"

    # 1. YouTube check
    if "youtube" in platform or "youtube.com" in u or "youtu.be" in u:
        if "comments are turned off" in html_low or "comments have been turned off" in html_low:
            return False, "WEED OUT - YouTube comments are disabled"
        return True, "YouTube commentable"

    # 2. Reddit check
    if "reddit.com" in u:
        if "archived" in html_low or '"locked": true' in html_low:
            return False, "WEED OUT - Reddit thread is locked or archived"
        return True, "Reddit commentable"

    # 3. General Blog / Web comment check
    closed_phrases = [
        "comments are closed", 
        "commenting has been closed", 
        "comments are turned off", 
        "closed to comments",
        "thread is archived"
    ]
    if any(phrase in html_low for phrase in closed_phrases):
        return False, "WEED OUT - Comments are explicitly closed on this page"

    return True, "Passed comment check"

def deep_fetch(post):
    """Fetch body and raw html for one post. Returns (deep_text, raw_html, deep_source, deep_status). Never raises."""
    try:
        url = (post.get("link") or "").strip()
        platform = (post.get("platform") or "").lower()
        
        # Reclassify URL if it's a hidden blog
        platform = classify_platform_from_url(url, platform)
        post["platform"] = platform
        
        # YouTube: transcript first
        if "youtube" in platform or "youtube.com" in url or "youtu.be" in url:
            txt, status = _fetch_youtube_transcript(url)
            raw_html, txt2, status2 = _fetch_url_data(url)
            if txt and len(txt) >= 200:
                return txt, raw_html, "youtube-transcript", status
            if txt2:
                return txt2, raw_html, "youtube-page", f"{status} + {status2}"
            return (post.get("snippet") or ""), "", "snippet-fallback", "transcript+page-failed"
            
        # Medium / Web / Social: fetch page
        if url.startswith("http"):
            raw_html, txt, status = _fetch_url_data(url)
            if txt:
                return txt, raw_html, "page", status
            return (post.get("snippet") or ""), "", "snippet-fallback", status
            
        return (post.get("snippet") or ""), "", "snippet-only", "no-url"
    except Exception as e:
        return (post.get("snippet") or ""), "", "snippet-fallback", f"deep-error: {str(e)[:80]}"

def deep_filter(post, deep_text, raw_html=""):
    """Decide keep vs weed out based on commentability and BODY text.
    Returns (keep_bool, reason).
    """
    url = post.get("link", "")
    platform = post.get("platform", "")

    # 1. Commentability & Platform Filter (Blocks blogs and locked threads)
    commentable, comment_reason = _is_commentable(url, raw_html, platform)
    if not commentable:
        return False, comment_reason

    # 2. Keyword Content Filter
    txt = (deep_text or "").strip()
    if len(txt) < 200:
        return True, "deep short (<200 chars) - kept on title"
    low = " " + txt.lower() + " "
    found = []
    for kw in DEEP_KEYWORDS:
        if kw.lower() in low:
            found.append(kw)
    if not found:
        return False, "WEED OUT - title matched but body has no AI/leadership/book-theme keywords"
    
    return True, f"deep confirms - found: {', '.join(found[:3])}"

def run_deep_discovery(kept_posts, max_posts=23, progress_cb=None):
    """Step 2: for each kept post, fetch body + check commentability + filter. Returns (kept_after_deep, deep_stats, weeded)."""
    kept = kept_posts or []
    to_check = kept[:max_posts]
    rest = kept[max_posts:] if len(kept) > max_posts else []
    kept_after = []
    weeded = []
    checked = 0
    failed = 0
    import time as _time2
    _deep_start = _time2.time()
    
    for p in to_check:
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
            deep_text, raw_html, deep_source, deep_status = deep_fetch(p)
            keep, reason = deep_filter(p, deep_text, raw_html)
            
            p["_deep_source"] = deep_source
            p["_deep_status"] = deep_status
            p["_deep_reason"] = reason
            p["_deep_len"] = len(deep_text or "")
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
            
        try:
            time.sleep(0.2)
        except Exception:
            pass
            
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
