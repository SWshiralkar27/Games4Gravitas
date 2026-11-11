"""drafting/formatting.py — v4.3 with v2.2 Plain-Text & Link Sanitization."""
from __future__ import annotations
import re
from config import ABBREVIATIONS, BOOK_TITLE, BOOK_LINK, BOOK_NAME_YOUTUBE, ITALIC_KEYWORDS, PLAIN_TEXT_PLATFORMS

_URL_RE = re.compile(r"https?://[^\s\)\]]+")

def _protect_urls(text):
    urls = []
    def _repl(m):
        urls.append(m.group(0))
        return f"\x00URL{len(urls)-1}\x00"
    return _URL_RE.sub(_repl, text), urls

def _restore_urls(text, urls):
    for i, u in enumerate(urls):
        text = text.replace(f"\x00URL{i}\x00", u)
    return text

def _protect_abbreviations(text):
    placeholders = {}
    for abbr in ABBREVIATIONS:
        if abbr in text:
            key = f"\x00ABBR{len(placeholders)}\x00"
            placeholders[key] = abbr
            text = text.replace(abbr, key)
    return text, placeholders

def _restore_abbreviations(text, placeholders):
    for k, v in placeholders.items():
        text = text.replace(k, v)
    return text

def _bold_book_title(text):
    parts = re.split(r"(\*\*.*?\*\*)", text)
    out = []
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            out.append(part)
        else:
            out.append(re.sub(
                r"(?<!\*)\bGames for Gravitas\b(?!\*)",
                "**Games for Gravitas**",
                part, flags=re.I,
            ))
    return "".join(out)

def _italicise_keywords(text):
    keywords = sorted(ITALIC_KEYWORDS, key=len, reverse=True)
    parts = re.split(r"(\*\*.*?\*\*|\*[^*]+?\*)", text)
    out = []
    for part in parts:
        if not part:
            continue
        if (part.startswith("**") and part.endswith("**")) or (part.startswith("*") and part.endswith("*") and not part.startswith("**")):
            out.append(part)
            continue
        for kw in keywords:
            part = re.sub(
                r"(?<!\*)\b" + re.escape(kw) + r"\b(?!\*)",
                lambda m: f"*{m.group(0)}*",
                part, flags=re.I,
            )
        out.append(part)
    return "".join(out)

def _break_after_full_stop(text):
    text, abbr_map = _protect_abbreviations(text)
    decimals = {}
    def _dec_repl(m):
        k = f"\x00DEC{len(decimals)}\x00"
        decimals[k] = m.group(0)
        return k
    text = re.sub(r"\d+\.\d+", _dec_repl, text)
    text = re.sub(r"\.\s+", ".\n\n", text)
    text = re.sub(r"\.\n(?!\n)", ".\n\n", text)
    for k, v in decimals.items():
        text = text.replace(k, v)
    text = _restore_abbreviations(text, abbr_map)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def word_range(platform: str) -> tuple[int, int]:
    return (70, 90)

def book_mention_form(platform: str, variant: int = 0) -> str:
    # 2026-11-11: Fix - bold only, no Amazon link. Reason: placeholder YOUR_BOOK_ID leaked into Copy box as raw markdown.
    # 2026-11-11: Fix - added variant param + fixed indent. Reason: old code had dead code after return with wrong indent + undefined variant -> IndentationError.
    if platform in PLAIN_TEXT_PLATFORMS:
        return "Games for Gravitas"
    if variant == 0:
        return f"**{BOOK_TITLE}**"
    elif variant == 1:
        return f"*{BOOK_TITLE}*"
    else:
        return "Games for Gravitas"

def format_for_platform(draft: str, platform: str) -> str:
    if not draft:
        return ""
    text = str(draft).strip().strip('"\u201c\u201d').strip()
    plain = platform in PLAIN_TEXT_PLATFORMS

    # Plain text platforms (YouTube/Shorts): strictly strip markdown links, URLs, and markdown formatting
    if plain:
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        text = text.replace("**", "").replace("*", "").replace("_", "")
        text = re.sub(r"\s{2,}", " ", text).strip()
        # 2026-11-11: Fix - plain platforms still get line break after every full stop.
        text = _break_after_full_stop(text)
        return text

    # Rich text platforms
    text, urls = _protect_urls(text)
    text = _bold_book_title(text)
    text = _italicise_keywords(text)
    text = _restore_urls(text, urls)
    text, urls2 = _protect_urls(text)
    text = _break_after_full_stop(text)
    text = _restore_urls(text, urls2)
    return text

def format_for_display(draft: str, platform: str = "Medium") -> str:
    return format_for_platform(draft, platform)

def format_for_copy(draft: str, platform: str = "Medium") -> str:
    return format_for_platform(draft, platform)

def validate_hook(draft: str) -> bool:
    t = (draft or "").strip().lower()
    return not any(t.startswith(b) for b in ["great post", "thanks for sharing", "thank you for sharing", "nice post", "love this"])
