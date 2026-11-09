"""#5 Opportunity Score — thread-level, no author data."""
from __future__ import annotations
from config import COMMENT_SWEET_MIN, COMMENT_SWEET_MAX, RECENCY_GOLD_HOURS, RECENCY_GOOD_HOURS

def _conversation_score(item) -> float:
    if item.comment_count and item.comment_count > 80:
        return 20.0
    if item.is_question:
        return 100.0
    if COMMENT_SWEET_MIN <= (item.comment_count or 0) <= COMMENT_SWEET_MAX:
        return 90.0
    if (item.comment_count or 0) == 0:
        return 60.0
    if (item.comment_count or 0) < COMMENT_SWEET_MIN:
        return 70.0
    return 50.0

def _recency_score(item) -> float:
    h = item.hours_since_post
    if h <= RECENCY_GOLD_HOURS:
        return 100.0
    if h <= 12:
        return 80.0
    if h <= RECENCY_GOOD_HOURS:
        return 60.0
    if h <= 72:
        return 40.0
    return 20.0

def calculate_opportunity_score(item) -> float:
    rel = max(0.0, min(100.0, item.relevance_score * 100))
    if getattr(item, "contextual_relevance_score", 0):
        rel = 0.5 * rel + 0.5 * float(item.contextual_relevance_score)
    conv = _conversation_score(item)
    rec = _recency_score(item)
    return round(0.40 * rel + 0.35 * conv + 0.25 * rec, 1)
