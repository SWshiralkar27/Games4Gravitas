
"""scoring/selection.py — v4.6 heuristic (0 API calls)
FIX for quota-out giving 22 assessed: 0 promote / 0 engage / 22 skip

Root cause: heuristic needed promo >=60 to Engage, but web search returns
0 comments and titles rarely contain exact book-theme phrases like
`purposeful rehearsal`, so a good social post scored ~56 and was skipped.
Gemini would have understood context and promoted it. Heuristic did not.

Fix v4.6 (heuristic only, Gemini thresholds unchanged):
- Social platforms (LinkedIn, X, Threads, Facebook, Instagram) get
  +10 relevance if AI/leadership keywords present, +10 conversation
  because a thread exists to join.
- Heuristic Engage threshold is 50 for social posts, not 60.
  Gemini still uses 60/80 from config. This only affects the fallback.
- Question + social + promo >=45 -> Engage.

Web articles / _auto_skip still Skip. Sensitive still blocked.
"""
import re

from config import (
    A_PROMOTE, B_ENGAGE, BOOK_THEMES, DYNAMIC_THRESHOLD,
    MAX_GEMINI_CALLS_PER_RUN, SATURATION_COMMENTS, SENSITIVE_KEYWORDS,
    BREAKING_KEYWORDS, SOCIAL_PLATFORMS,
)


def _text(post):
    return ((post.get("title", "") or "") + " " + (post.get("snippet", "") or "")).lower()


def heuristic_assess(post):
    text = _text(post)
    title = (post.get("title", "") or "")
    platform = post.get("platform", "") or ""

    if any(k in text for k in SENSITIVE_KEYWORDS):
        return {"decision": "D_SENSITIVE", "promo": 0, "opp": 0.0,
                "theme": "other", "reason": "Sensitive topic - blocked."}

    if post.get("_auto_skip") or platform.startswith("Web -") or platform == "Medium":
        return {"decision": "D_SKIP", "promo": 0, "opp": 0.0,
                "theme": "other",
                "reason": "Web article - no thread to join. Pruned to social threads first."}

    is_social = platform in SOCIAL_PLATFORMS

    theme_hits = [t for t in BOOK_THEMES if t.lower() in text]
    relevance = 30
    if theme_hits:
        relevance += min(40, len(theme_hits) * 20)
    if any(w in text for w in ["ai", "leadership", "team", "upskill", "reskill", "manager", "hybrid"]):
        relevance += 15
    if is_social and any(w in text for w in ["ai", "leadership", "team", "upskill", "reskill", "manager", "hybrid"]):
        relevance += 10
    relevance = min(95, relevance)

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
    if is_social:
        conversation += 10
    conversation = max(5, min(95, conversation))

    recency = 70
    promo = round(relevance * 0.30 + conversation * 0.35 + recency * 0.15 + 20)
    opp = round((relevance * 0.40 + conversation * 0.35 + recency * 0.25) / 10, 1)

    if any(k in text for k in BREAKING_KEYWORDS):
        return {"decision": "C_WAIT", "promo": promo, "opp": opp,
                "theme": theme_hits[0] if theme_hits else "other",
                "reason": "Breaking / fast news - 24h hold."}

    # v4.6 heuristic thresholds: social Engage at 50, not 60
    if promo >= A_PROMOTE:
        decision = "A_PROMOTE"
    elif promo >= B_ENGAGE:
        decision = "B_ENGAGE"
    elif is_social and promo >= 50:
        decision = "B_ENGAGE"
    elif is_question and comments <= 30 and promo >= 45:
        decision = "B_ENGAGE"
    elif comments > SATURATION_COMMENTS and promo >= A_PROMOTE:
        decision = "B_ENGAGE"
    else:
        decision = "D_SKIP"

    theme = theme_hits[0] if theme_hits else "other"
    reason = f"Heuristic: relevance {relevance}, conversation {conversation}. Theme: {theme}."
    if decision == "D_SKIP":
        reason += " Low thread opportunity."
    if decision == "B_ENGAGE" and promo < B_ENGAGE:
        reason += " Heuristic fallback (Gemini quota out) - social thread."
    return {"decision": decision, "promo": promo, "opp": opp, "theme": theme, "reason": reason}


def select_for_gemini(posts):
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
    from drafting.formatting import format_draft
    title = (post.get("title", "") or "this post").strip()
    raw = (
        f"This reframing of how teams actually decide under AI pressure stuck with me. "
        f"Your point on {title[:80]} shows why purposeful rehearsal matters before a call locks in. "
        f"Where have you seen rehearsal change a decision that would otherwise have gone the other way?"
    )
    return format_draft(raw)

