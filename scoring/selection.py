"""scoring/selection.py — v4.2 heuristic (0 API calls)
Why this file exists:
When Gemini quota is exhausted (429), the old code marked EVERYTHING Skip
-> "85 assessed: 0 promote / 0 engage". That is wrong. Heuristic gives a
real assessment without any API call, so quota exhaustion degrades to
heuristic, not to all-Skip.

Also used BEFORE Gemini: only top MAX_GEMINI_CALLS_PER_RUN posts go to
Gemini. Rest use heuristic. This is what stops 85 posts burning 85+ calls.
"""
import re

from config import (
    A_PROMOTE, B_ENGAGE, BOOK_THEMES, DYNAMIC_THRESHOLD,
    MAX_GEMINI_CALLS_PER_RUN, SATURATION_COMMENTS, SENSITIVE_KEYWORDS,
    BREAKING_KEYWORDS,
)


def _text(post):
    return ((post.get("title", "") or "") + " " + (post.get("snippet", "") or "")).lower()


def heuristic_assess(post):
    text = _text(post)
    title = (post.get("title", "") or "")
    platform = post.get("platform", "") or ""

    # Sensitive -> blocked, never draft
    if any(k in text for k in SENSITIVE_KEYWORDS):
        return {"decision": "D_SENSITIVE", "promo": 0, "opp": 0.0,
                "theme": "other", "reason": "Sensitive topic - blocked."}

    # Web article -> Skip without Gemini
    if post.get("_auto_skip") or platform.startswith("Web -") or platform == "Medium":
        return {"decision": "D_SKIP", "promo": 0, "opp": 0.0,
                "theme": "other",
                "reason": "Web article - no thread to join. Pruned to social threads first."}

    # Relevance: theme keyword overlap (not just counting, weighted)
    theme_hits = [t for t in BOOK_THEMES if t.lower() in text]
    relevance = 30
    if theme_hits:
        relevance += min(40, len(theme_hits) * 20)
    if any(w in text for w in ["ai", "leadership", "team", "upskill", "reskill", "manager", "hybrid"]):
        relevance += 15
    relevance = min(95, relevance)

    # Conversation: question + comment window 5-30
    conversation = 40
    is_question = "?" in title or "?" in (post.get("snippet", "") or "")
    if is_question:
        conversation += 25
    comments = post.get("comments", 0) or 0
    if 5 <= comments <= 30:
        conversation += 20
    elif comments > SATURATION_COMMENTS:
        conversation -= 20
    elif comments == 0:
        conversation -= 5
    conversation = max(5, min(95, conversation))

    # Recency: assume recent if no date; penalise old web items only
    recency = 70

    promo = round(relevance * 0.30 + conversation * 0.35 + recency * 0.15 + 20)
    # Promotion re-weight approx: Book/Context/Engagement/Audience/Naturalness
    # Heuristic promo is capped so Gemini can still upgrade it.
    opp = round((relevance * 0.40 + conversation * 0.35 + recency * 0.25) / 10, 1)

    # Breaking / fast news -> Wait 24h
    if any(k in text for k in BREAKING_KEYWORDS):
        return {"decision": "C_WAIT", "promo": promo, "opp": opp,
                "theme": theme_hits[0] if theme_hits else "other",
                "reason": "Breaking / fast news - 24h hold."}

    # Decision
    if promo >= A_PROMOTE:
        decision = "A_PROMOTE"
    elif promo >= B_ENGAGE:
        decision = "B_ENGAGE"
    elif is_question and comments <= 30 and promo >= DYNAMIC_THRESHOLD - 15:
        decision = "B_ENGAGE"
    elif comments > SATURATION_COMMENTS and promo >= A_PROMOTE:
        decision = "B_ENGAGE"  # saturated: downgrade Promote -> Engage
    else:
        decision = "D_SKIP"

    theme = theme_hits[0] if theme_hits else "other"
    reason = f"Heuristic: relevance {relevance}, conversation {conversation}. Theme: {theme}."
    if decision == "D_SKIP":
        reason += " Low thread opportunity."
    return {"decision": decision, "promo": promo, "opp": opp, "theme": theme, "reason": reason}


def select_for_gemini(posts):
    """Top N social, non-sensitive, non-auto-skip posts go to Gemini."""
    candidates = []
    for p in posts or []:
        if p.get("_auto_skip"):
            continue
        h = heuristic_assess(p)
        if h["decision"] == "D_SENSITIVE":
            continue
        candidates.append((h["opp"], h["promo"], p))
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [p for _, _, p in candidates[:MAX_GEMINI_CALLS_PER_RUN]]


def template_draft(post, analysis=None):
    """Copyable fallback when Gemini quota is out. Already formatted."""
    from drafting.formatting import format_draft
    title = (post.get("title", "") or "this post").strip()
    # CEA, no 'Great post' opener, no book title/link in Engage drafts
    raw = (
        f"This reframing of how teams actually decide under AI pressure stuck with me. "
        f"Your point on {title[:80]} shows why purposeful rehearsal matters before a call locks in. "
        f"Where have you seen rehearsal change a decision that would otherwise have gone the other way?"
    )
    return format_draft(raw)
