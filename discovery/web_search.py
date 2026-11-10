"""discovery/web_search.py — v4.2
FIXES:
- Simple queries only. NO parenthesised OR like
  "term (site:linkedin.com/posts OR site:x.com ...)".
  Serper returns 0 for those. Each query is one plain term or
  one term + one site: filter.
- detect_platform never defaults unknown to X. Unknown -> "Web - domain".
"""
import json
import os
from urllib.parse import urlparse

from config import MAX_RESULTS_PER_SOURCE, SEARCH_PROVIDER, SERPER_API_KEY, BRAVE_API_KEY


def detect_platform(url, title=""):
    u = (url or "").lower()
    if "linkedin.com" in u:
        return "LinkedIn"
    if "x.com" in u or "twitter.com" in u:
        return "X"
    if "threads.net" in u or "threads.com" in u:
        return "Threads"
    if "facebook.com" in u or "fb.com" in u:
        return "Facebook"
    if "instagram.com" in u:
        return "Instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "medium.com" in u:
        return "Medium"
    # Never default to X. Show real source so pruning can drop it.
    try:
        domain = urlparse(url).netloc.replace("www.", "") or "web"
    except Exception:
        domain = "web"
    return f"Web - {domain}"


def build_simple_queries(search_terms):
    """Max 8 queries per run. Simple, Serper-friendly."""
    queries = []
    terms = list(search_terms or [])[:4]
    for term in terms:
        queries.append(term)
    # One site-filtered query per term, rotating sites so we get social first.
    sites = ["site:linkedin.com", "site:x.com", "site:threads.net", "site:linkedin.com"]
    for term, site in zip(terms, sites):
        queries.append(f"{term} {site}")
    return queries[:8]


def _serper_search(query, num=5):
    try:
        import requests
    except Exception:
        return []
    if not SERPER_API_KEY:
        return []
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": num},
            timeout=20,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        out = []
        for item in data.get("organic", [])[:num]:
            link = item.get("link", "")
            out.append({
                "title": item.get("title", ""),
                "link": link,
                "snippet": item.get("snippet", ""),
                "platform": detect_platform(link, item.get("title", "")),
                "source": "serper",
                "query": query,
                "comments": 0,
            })
        return out
    except Exception:
        return []


def _brave_search(query, num=5):
    try:
        import requests
    except Exception:
        return []
    if not BRAVE_API_KEY:
        return []
    try:
        r = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": BRAVE_API_KEY, "Accept": "application/json"},
            params={"q": query, "count": num},
            timeout=20,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        out = []
        for item in (data.get("web", {}).get("results", []) or [])[:num]:
            link = item.get("url", "")
            out.append({
                "title": item.get("title", ""),
                "link": link,
                "snippet": item.get("description", ""),
                "platform": detect_platform(link, item.get("title", "")),
                "source": "brave",
                "query": query,
                "comments": 0,
            })
        return out
    except Exception:
        return []


def search_web(search_terms):
    """Returns (posts, per_source_counts)."""
    queries = build_simple_queries(search_terms)
    posts = []
    counts = {}
    for q in queries:
        if SEARCH_PROVIDER == "brave":
            batch = _brave_search(q, num=MAX_RESULTS_PER_SOURCE)
        else:
            batch = _serper_search(q, num=MAX_RESULTS_PER_SOURCE)
        counts[q] = len(batch)
        posts.extend(batch)
    return posts, counts
