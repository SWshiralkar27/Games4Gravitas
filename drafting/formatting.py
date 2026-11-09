"""#4 Platform-native formatting + #10 book mention rotation."""
from __future__ import annotations
import re
from config import BOOK_TITLE, BOOK_URL, BOOK_NAME_YOUTUBE, PLAIN_TEXT_PLATFORMS

def word_range(platform: str):
    return {"LinkedIn": (40, 80), "X": (20, 60), "Threads": (25, 60), "Medium": (60, 120), "YouTube": (30, 90), "YouTube Shorts": (25, 70), "Facebook": (40, 90), "Instagram": (40, 90)}.get(platform, (40, 90))

def book_mention_form(variant: int, plain: bool) -> str:
    if plain:
        if variant == 1:
            return f'"{BOOK_NAME_YOUTUBE}"'
        if variant == 2:
            return f'the game I wrote about in "{BOOK_NAME_YOUTUBE}"'
        return f'"{BOOK_NAME_YOUTUBE}"'
    if variant == 1:
        return f'"{BOOK_TITLE}"'
    if variant == 2:
        return f'the game I wrote about in **{BOOK_TITLE}**'
    return f"[**{BOOK_TITLE}**]({BOOK_URL})"

def format_for_platform(draft: str, platform: str) -> str:
    d = (draft or "").strip()
    if platform == "LinkedIn":
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", d) if s.strip()]
        if len(sentences) >= 3:
            return sentences[0] + "\n\n" + " ".join(sentences[1:-1]) + "\n\n" + sentences[-1]
        return d
    if platform in ("X", "Threads"):
        return " ".join(d.split())
    return d
