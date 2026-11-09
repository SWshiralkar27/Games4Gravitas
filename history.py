"""History + dedupe. Backward compatible with seen_posts.txt: url<TAB>iso-timestamp."""
from __future__ import annotations
import hashlib, re
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from config import HISTORY_FILE, HISTORY_DAYS, IGNORE_HISTORY

_TRACKING_PARAMS = {"utm_source","utm_medium","utm_campaign","utm_term","utm_content","fbclid","gclid","ref","ref_src","src","si","s","share"}

def normalize_url(url: str) -> str:
    p = urlparse(url)
    q = [(k,v) for k,v in parse_qsl(p.query) if k not in _TRACKING_PARAMS]
    path = p.path.rstrip("/")
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", urlencode(sorted(q)), ""))

def normalize_title(title: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    return re.sub(r"\s+", " ", t)

def title_hash(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode()).hexdigest()[:16]

def load_history() -> set[str]:
    if IGNORE_HISTORY or not HISTORY_FILE.exists():
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    urls = set()
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        url, _, ts = line.strip().partition("\t")
        if ts:
            try:
                when = datetime.fromisoformat(ts)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if when < cutoff:
                    continue
            except ValueError:
                pass
        urls.add(url)
    return urls

def save_history(urls: Iterable[str]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = {}
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            url, _, ts = line.partition("\t")
            if url:
                existing[url] = ts
    for u in urls:
        existing[normalize_url(u)] = now
    try:
        HISTORY_FILE.write_text("\n".join(f"{u}\t{ts}" for u, ts in sorted(existing.items())), encoding="utf-8")
    except OSError:
        pass

def dedupe_and_filter(items, history: set[str]):
    seen_urls, seen_titles, out = set(), set(), []
    for it in items:
        key = normalize_url(it.url)
        th = title_hash(it.title)
        if key in seen_urls or key in history:
            continue
        if th and th in seen_titles:
            continue
        seen_urls.add(key)
        seen_titles.add(th)
        out.append(it)
    return out
