"""#3 Hook-first validation."""
from __future__ import annotations
import re
from config import BOOK_TITLE

BANNED_OPENERS = ["great post", "interesting post", "thanks for sharing", "great insight", "nice post", "love this", "amazing post", "well said", "great point"]

def is_valid_draft(draft: str, decision: str, plain: bool) -> tuple[bool, str]:
    d = (draft or "").strip()
    if len(d) < 30:
        return False, "Too short"
    low = d.lower()
    for b in BANNED_OPENERS:
        if low.startswith(b):
            return False, f"Generic opener: {b}"
    first = re.split(r"[.!?\n]", d)[0].strip()
    if len(first) < 12:
        return False, "Weak hook"
    if decision == "A_PROMOTE":
        if low.count(BOOK_TITLE.lower()) != 1:
            return False, "A_PROMOTE must mention book exactly once"
    else:
        if re.search(r"games\s+for\s+gravitas|shiralkar|http", d, re.I):
            return False, "B_ENGAGE must not mention book/author/link"
    return True, ""
