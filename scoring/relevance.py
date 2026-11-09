"""#8 Semantic relevance: keyword is fallback, Gemini theme-fit is primary (in analysis)."""
from __future__ import annotations
import re
from config import KEYWORDS

def calculate_relevance_score(item) -> float:
    text = f"{item.title} {item.snippet}".lower()
    tokens = re.findall(r"[a-z]+", text)
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in KEYWORDS)
    return hits / len(tokens)
