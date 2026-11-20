"""drafting/formatting.py — v4.4.1 with v3.0 Sentence-per-Block & Italics-Only, Colab-safe."""
from __future__ import annotations
import re

# Colab-safe import: use real config.py in the app, fallback defaults in Colab
try:
    from config import ABBREVIATIONS, BOOK_TITLE, BOOK_LINK, BOOK_NAME_YOUTUBE, ITALIC_KEYWORDS, PLAIN_TEXT_PLATFORMS
except (ModuleNotFoundError, ImportError):
    ABBREVIATIONS = ["Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "Sr.", "Jr.", "St.", "vs.", "etc.", "e.g.", "i.e.", "a.m.", "p.m.", "Ph.D."]
    BOOK_TITLE = "Games for Gravitas"
    BOOK_LINK = ""
    BOOK_NAME_YOUTUBE = "Games for Gravitas"
    ITALIC_KEYWORDS = []
    PLAIN_TEXT_PLATFORMS = ["YouTube", "Shorts"]

_URL_RE = re.compile(r"https?://[^\s\)\]]+")

# Abbreviations that must never end a sentence, merged with config ABBREVIATIONS.
# ITALIC_KEYWORDS is kept for backward compatibility, but it is no longer auto-applied.
_DEFAULT_ABBRS = [
    "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "Sr.", "Jr.", "St.", "vs.", "etc.",
    "e.g.", "i.e.", "a.m.", "p.m.", "Ph.D.", "M.D.", "U.S.", "U.K.", "U.S.A.",
    "No.", "Fig.", "Vol.", "pp.", "approx.", "appt.", "dept.",
]

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
    all_abbrs = sorted(set(list(ABBREVIATIONS) + _DEFAULT_ABBRS), key=len, reverse=True)
    for abbr in all_abbrs:
        if abbr in text:
            key = f"\x00ABBR{len(placeholders)}\x00"
            placeholders[key] = abbr
            text = text.replace(abbr, key)
    return text, placeholders

def _restore_abbreviations(text, placeholders):
    for k, v in placeholders.items():
        text = text.replace(k, v)
    return text

def _strip_bold_underline(text):
    # Rule 2: no bold, no underline for emphasis. Keep single *italics*.
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    return text

def _enforce_italics_limit(block: str) -> str:
    # Keep author's *italics*, but max 2 phrases per sentence/block.
    count = [0]
    def _repl(m):
        count[0] += 1
        if count[0] <= 2:
            return m.group(0)
        return m.group(1)
    return re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", _repl, block)

def _split_sentences(paragraph: str) -> list[str]:
    if not paragraph.strip():
        return []
    text = paragraph.strip()
    text, urls = _protect_urls(text)
    text = text.replace("...", "\x00ELLIPSIS\x00")
    decimals = {}
    def _dec_repl(m):
        k = f"\x00DEC{len(decimals)}\x00"
        decimals[k] = m.group(0)
        return k
    text = re.sub(r"\d+\.\d+", _dec_repl, text)
    text, abbr_map = _protect_abbreviations(text)
    acronyms = {}
    def _acr_repl(m):
        k = f"\x00ACR{len(acronyms)}\x00"
        acronyms[k] = m.group(0)
        return k
    text = re.sub(r"\b(?:[A-Z]\.){2,}", _acr_repl, text)
    initials = {}
    def _init_repl(m):
        k = f"\x00INIT{len(initials)}\x00"
        initials[k] = m.group(0)
        return k
    text = re.sub(r"\b[A-Z]\.(?=\s+[A-Z])", _init_repl, text)
    text = re.sub(
        r"([.?!][\"'”\)\]]?)\s+(?=[\"'“‘\(\[]?[A-Z0-9])",
        lambda m: m.group(1) + "\x00SENT_SPLIT\x00",
        text,
    )
    parts = text.split("\x00SENT_SPLIT\x00")
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        for k, v in initials.items():
            p = p.replace(k, v)
        for k, v in acronyms.items():
            p = p.replace(k, v)
        p = _restore_abbreviations(p, abbr_map)
        for k, v in decimals.items():
            p = p.replace(k, v)
        p = p.replace("\x00ELLIPSIS\x00", "...")
        p = _restore_urls(p, urls)
        out.append(p)
    return out

def _format_blocks(text: str, plain: bool) -> str:
    lines = text.splitlines()
    blocks: list[str] = []
    para_buf: list[str] = []

    def _flush_para():
        if not para_buf:
            return
        para = " ".join(p.strip() for p in para_buf if p.strip())
        para_buf.clear()
        if not para:
            return
        for s in _split_sentences(para):
            s = s.strip()
            if not s:
                continue
            if not plain:
                s = _enforce_italics_limit(s)
            blocks.append(s)

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            _flush_para()
            continue
        if stripped.startswith("#"):
            _flush_para()
            heading = stripped.lstrip("#").strip()
            if not plain:
                heading = _strip_bold_underline(heading)
                heading = _enforce_italics_limit(heading)
                hashes = stripped[:len(stripped) - len(stripped.lstrip("#"))]
                blocks.append(f"{hashes} {heading}".strip())
            else:
                blocks.append(heading)
            continue
        m_bullet = re.match(r"^(\s*[-*•]\s+)(.+)$", raw_line)
        m_num = re.match(r"^(\s*\d+[.)]\s+)(.+)$", raw_line)
        if m_bullet:
            _flush_para()
            prefix, content = m_bullet.groups()
            prefix = re.sub(r"[-*•]", "-", prefix, count=1)
            for s in _split_sentences(content.strip()):
                s = s.strip()
                if not s:
                    continue
                if not plain:
                    s = _enforce_italics_limit(s)
                blocks.append(f"{prefix}{s}")
            continue
        if m_num:
            _flush_para()
            prefix, content = m_num.groups()
            num_m = re.search(r"\d+", prefix)
            num = int(num_m.group(0)) if num_m else 1
            sep = "." if "." in prefix else ")"
            leading = re.match(r"^\s*", prefix).group(0)
            for i, s in enumerate(_split_sentences(content.strip())):
                s = s.strip()
                if not s:
                    continue
                if not plain:
                    s = _enforce_italics_limit(s)
                blocks.append(f"{leading}{num + i}{sep} {s}")
            continue
        para_buf.append(stripped)
    _flush_para()
    return "\n\n".join(blocks)

def word_range(platform: str) -> tuple[int, int]:
    return (70, 90)

def book_mention_form(platform: str, variant: int = 0) -> str:
    return "Games for Gravitas"

def format_for_platform(draft: str, platform: str) -> str:
    if not draft:
        return ""
    text = str(draft).strip().strip('"\u201c\u201d').strip()
    plain = platform in PLAIN_TEXT_PLATFORMS
    if plain:
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"(?m)^\s*[*•]\s+", "- ", text)
        text = text.replace("**", "").replace("*", "").replace("_", "")
        text = re.sub(r"\s{2,}", " ", text).strip()
        text = _format_blocks(text, plain=True)
        return text
    text = _strip_bold_underline(text)
    text, urls = _protect_urls(text)
    text = _format_blocks(text, plain=False)
    text = _restore_urls(text, urls)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def format_for_display(draft: str, platform: str = "Medium") -> str:
    return format_for_platform(draft, platform)

def format_for_copy(draft: str, platform: str = "Medium") -> str:
    return format_for_platform(draft, platform)

def validate_hook(draft: str) -> bool:
    t = (draft or "").strip().lower()
    return not any(t.startswith(b) for b in ["great post", "thanks for sharing", "thank you for sharing", "nice post", "love this"])
