"""drafting/formatting.py — v4.2 (Fix for Q2)
Requirements:
- Bold book name: **Games for Gravitas**
- Italics for key phrases: *purposeful rehearsal*, *centaur leadership*, etc.
- Line break after every full stop (.)

Rules to avoid breaking text:
- URLs are protected (no break inside https://... and no bold/italics inside URLs).
- Decimals (3.5) and abbreviations (Mr., Dr., e.g., U.S.) are protected.
- Never double-wrap: **...** stays bold, *...* stays italic.
- Applied to BOTH Gemini drafts and template drafts, and to Grok-reviewed drafts.
"""
import re

from config import ABBREVIATIONS, BOOK_TITLE, ITALIC_KEYWORDS

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
    # Split on existing **...** so we never double-bold inside bold.
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
    # Longest phrases first, so "rehearse before you decide" wins over "rehearse".
    keywords = sorted(ITALIC_KEYWORDS, key=len, reverse=True)
    # Split on **...** (bold) and *...* (already italic) — only format plain parts.
    parts = re.split(r"(\*\*.*?\*\*|\*[^*]+?\*)", text)
    out = []
    for part in parts:
        if not part:
            continue
        if (part.startswith("**") and part.endswith("**")) or (part.startswith("*") and part.endswith("*") and not part.startswith("**")):
            out.append(part)
            continue
        for kw in keywords:
            # Skip if kw is inside book title (already bold-handled)
            part = re.sub(
                r"(?<!\*)\b" + re.escape(kw) + r"\b(?!\*)",
                lambda m: f"*{m.group(0)}*",
                part, flags=re.I,
            )
        out.append(part)
    return "".join(out)


def _break_after_full_stop(text):
    # Protect decimals: 3.5 -> placeholder, restore after.
    text, abbr_map = _protect_abbreviations(text)
    # Protect decimals
    decimals = {}
    def _dec_repl(m):
        k = f"\x00DEC{len(decimals)}\x00"
        decimals[k] = m.group(0)
        return k
    text = re.sub(r"\d+\.\d+", _dec_repl, text)
    # Break: ". " or "." + newline -> ".\n\n". Also ". " at end.
    text = re.sub(r"\.\s+", ".\n\n", text)
    text = re.sub(r"\.\n(?!\n)", ".\n\n", text)
    # Restore decimals + abbreviations
    for k, v in decimals.items():
        text = text.replace(k, v)
    text = _restore_abbreviations(text, abbr_map)
    # Collapse 3+ newlines, strip
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def format_draft(draft):
    """Main entry: bold + italics + line break after every full stop."""
    if not draft:
        return ""
    text = str(draft).strip()
    # 1. Protect URLs
    text, urls = _protect_urls(text)
    # 2. Bold book title
    text = _bold_book_title(text)
    # 3. Italics keywords (skips bold segments)
    text = _italicise_keywords(text)
    # 4. Restore URLs before line-break (so URLs are intact)
    text = _restore_urls(text, urls)
    # 5. Line break after every full stop (URLs + decimals protected inside)
    text, urls2 = _protect_urls(text)
    text = _break_after_full_stop(text)
    text = _restore_urls(text, urls2)
    return text


def format_for_display(draft):
    """For st.markdown — same as format_draft."""
    return format_draft(draft)


def format_for_copy(draft):
    """For st.code / .txt download — same markdown, so bold/italics survive copy."""
    return format_draft(draft)


def validate_hook(draft):
    """Reject 'Great post / Thanks for sharing' openers."""
    t = (draft or "").strip().lower()
    return not (t.startswith("great post") or t.startswith("thanks for sharing") or t.startswith("thank you for sharing"))
