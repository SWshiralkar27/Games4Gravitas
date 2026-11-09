"""Guardrails — fail-closed. #9 saturation + C_WAIT, #15 dynamic threshold."""
from __future__ import annotations
from config import PROMOTION_THRESHOLD, PROMOTION_THRESHOLD_OPEN, ENGAGEMENT_THRESHOLD, MIN_CONTEXT_CHARS, MAX_COMMENT_COUNT_SATURATION
from models import Decision

def apply_guardrails(analysis: dict, context_len: int, item) -> tuple[str, str, int]:
    decision = analysis["decision"]
    rejection = analysis.get("guardrail_override", "")
    sens = analysis["sensitivity"]
    conf = analysis["confidence"]
    promo = analysis["promotion_score"]
    threshold = PROMOTION_THRESHOLD_OPEN if (getattr(item, "is_question", False) and (item.comment_count or 0) <= 30) else PROMOTION_THRESHOLD
    if sens == "HIGH":
        return "C_SENSITIVE", "HIGH sensitivity hard veto.", threshold
    if analysis.get("is_breaking_news") and getattr(item, "hours_since_post", 9999) <= 24:
        return "C_WAIT", "Breaking / fast-moving news — hold 24h, do not comment now.", threshold
    if context_len < MIN_CONTEXT_CHARS:
        return "D_SKIP", "Context too short.", threshold
    if conf == "LOW":
        return "D_SKIP", "Low confidence.", threshold
    if (item.comment_count or 0) > MAX_COMMENT_COUNT_SATURATION and decision == "A_PROMOTE":
        decision = "B_ENGAGE"
        rejection = "Saturated thread (>80 comments) — downgraded to Engage."
    if decision == "A_PROMOTE" and promo < threshold:
        if promo >= ENGAGEMENT_THRESHOLD:
            decision = "B_ENGAGE"
            rejection = "Promo threshold downgrade."
        else:
            decision = "D_SKIP"
            rejection = "Promo threshold downgrade."
    return decision, rejection, threshold
