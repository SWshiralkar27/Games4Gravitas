"""scoring/selection.py — v4.9.5 heuristic + guardrail gate, soft import

2026-11-13 Step 3: Safe version. Current flow not broken.
- heuristic_assess() scoring identical, only Sensitive / Breaking use whole-word match.
- Guardrails import is soft: if guardrails.py fails to import, gate uses internal fallback with same logic.
- Gate is new functions only. Old app.py calling heuristic_assess() directly will see no change until app.py is wired to call guarded versions in Step 4.
- Name translation: guardrails.py returns C_SENSITIVE, app uses D_SENSITIVE.
"""
import re
from types import SimpleNamespace

from config import (
    A_PROMOTE, B_ENGAGE, BOOK_THEMES, DYNAMIC_THRESHOLD,
    MAX_GEMINI_CALLS_PER_RUN, SATURATION_COMMENTS, SENSITIVE_KEYWORDS,
    BREAKING_KEYWORDS, SOCIAL_PLATFORMS, OPP_PROMOTE, OPP_ENGAGE,
)

# Soft imports - never break load if config / guardrails are incomplete.
try:
    from config import PROMOTE_CAP_KEYWORDS
except Exception:
    PROMOTE_CAP_KEYWORDS = ["layoff", "layoffs", "fired", "redundancy", "job cuts", "downsizing"]

try:
    from config import PROMOTION_THRESHOLD, PROMOTION_THRESHOLD_OPEN, ENGAGEMENT_THRESHOLD, MIN_CONTEXT_CHARS, MAX_COMMENT_COUNT_SATURATION
except Exception:
    PROMOTION_THRESHOLD = A_PROMOTE
    PROMOTION_THRESHOLD_OPEN = 45
    ENGAGEMENT_THRESHOLD = B_ENGAGE
    MIN_CONTEXT_CHARS = 180
    MAX_COMMENT_COUNT_SATURATION = SATURATION_COMMENTS

try:
    from guardrails import apply_guardrails as _GUARDRAILS_APPLY
except Exception:
    _GUARDRAILS_APPLY = None

# ACT-3 Step 3b: Locked D1 phrase set, fallback only, not primary. Strong + Medium from locked D1.
_STRONG_PHRASES = ["upskill", "reskill", "corporate training", "l&d", "learning and development", "hybrid intelligence", "human edge", "game-based", "experiential learning"]
_MEDIUM_PHRASES = ["ai training", "ai upskilling", "leadership", "coaching", "workforce", "future of work", "adaptability", "critical thinking"]

def _text(post):
    return ((post.get("title", "") or "") + " " + (post.get("snippet", "") or "")).lower()

def _first_hit(text, phrases):
    """Whole-word / phrase match. 'war' does not match 'software'."""
    for ph in phrases or []:
        p = (ph or "").strip().lower()
        if not p:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", text):
            return ph
    return ""

def _gate_text(post):
    """Title + snippet + deep body, lowercase. Checks all deep-body keys."""
    deep = (post.get("_deep_text", "") or post.get("deep_text", "") or post.get("content_for_analysis", "") or post.get("full_content", "") or "")[:600]
    return ((post.get("title", "") or "") + " " + (post.get("snippet", "") or "") + " " + deep).lower()

def _truthy(v):
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("true", "yes", "1", "high")

def heuristic_assess(post):
    text = _text(post)
    title = (post.get("title", "") or "")
    platform = post.get("platform", "") or ""

    if _first_hit(text, SENSITIVE_KEYWORDS):
        return {"decision": "D_SENSITIVE", "promo": 0, "opp": 0.0,
                "theme": "other", "reason": "Sensitive topic - blocked."}

    if post.get("_auto_skip"):
        return {"decision": "D_SKIP", "promo": 0, "opp": 0.0,
                "theme": "other",
                "reason": "Auto-skipped by upstream filter."}

    _plat_low = (platform or "").lower()
    is_social = any(s.lower() in _plat_low for s in SOCIAL_PLATFORMS) or _plat_low.startswith("linkedin") or _plat_low.startswith("threads") or _plat_low.startswith("x -") or _plat_low.startswith("x ")

    def _book_theme_names():
        names = []
        for _t in BOOK_THEMES:
            if isinstance(_t, dict):
                _name = _t.get("name", "")
                if _name:
                    names.append(_name)
            else:
                names.append(str(_t))
        return names
    theme_hits = [t for t in _book_theme_names() if t and t.lower() in text]
    relevance = 30
    if theme_hits:
        relevance += min(40, len(theme_hits) * 20)
    if any(w in text for w in _STRONG_PHRASES + _MEDIUM_PHRASES):
        relevance += 15
    if is_social and any(w in text for w in _STRONG_PHRASES + _MEDIUM_PHRASES):
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

    if _first_hit(text, BREAKING_KEYWORDS):
        return {"decision": "C_WAIT", "promo": promo, "opp": opp,
                "theme": theme_hits[0] if theme_hits else "other",
                "reason": "Breaking / fast news - 24h hold."}

    if promo >= A_PROMOTE and opp >= OPP_PROMOTE:
        decision = "A_PROMOTE"
    elif promo >= B_ENGAGE and opp >= OPP_ENGAGE:
        decision = "B_ENGAGE"
    elif is_social and promo >= 50 and opp >= OPP_ENGAGE:
        decision = "B_ENGAGE"
    elif is_question and comments <= 30 and promo >= 45 and opp >= OPP_ENGAGE:
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

# ======================================================================
# GUARDRAIL GATE - new functions only, old calls unaffected
# ======================================================================
_DECISION_RENAME = {"C_SENSITIVE": "D_SENSITIVE"}
_NEVER_RELAX = ("D_SENSITIVE", "C_WAIT")

def _fallback_guardrails(analysis, context_len, item):
    """Same logic as guardrails.py, used only if guardrails.py import fails."""
    decision = analysis["decision"]
    rejection = analysis.get("guardrail_override", "")
    sens = analysis["sensitivity"]
    conf = analysis["confidence"]
    promo = analysis["promotion_score"]
    threshold = PROMOTION_THRESHOLD_OPEN if (getattr(item, "is_question", False) and (item.comment_count or 0) <= 30) else PROMOTION_THRESHOLD
    if sens == "HIGH":
        return "C_SENSITIVE", "HIGH sensitivity hard veto.", threshold
    if analysis.get("is_breaking_news") and getattr(item, "hours_since_post", 9999) <= 24:
        return "C_WAIT", "Breaking / fast-moving news - hold 24h, do not comment now.", threshold
    if context_len < MIN_CONTEXT_CHARS:
        return "D_SKIP", "Context too short.", threshold
    if conf == "LOW":
        return "D_SKIP", "Low confidence.", threshold
    if (item.comment_count or 0) > MAX_COMMENT_COUNT_SATURATION and decision == "A_PROMOTE":
        decision = "B_ENGAGE"
        rejection = "Saturated thread (>80 comments) - downgraded to Engage."
    if decision == "A_PROMOTE" and promo < threshold:
        if promo >= ENGAGEMENT_THRESHOLD:
            decision = "B_ENGAGE"
            rejection = "Promo threshold downgrade."
        else:
            decision = "D_SKIP"
            rejection = "Promo threshold downgrade."
    return decision, rejection, threshold

def apply_assess_guardrails(post, result, source="heuristic", flags=None):
    """Run ONE Assess result through guardrails. Never raises - on any error returns original result."""
    try:
        flags = flags or {}
        out = dict(result)
        incoming = _DECISION_RENAME.get(out.get("decision", "D_SKIP"), out.get("decision", "D_SKIP"))
        text = _gate_text(post)

        kw_sens = _first_hit(text, SENSITIVE_KEYWORDS)
        kw_break = _first_hit(text, BREAKING_KEYWORDS)
        kw_cap = _first_hit(text, PROMOTE_CAP_KEYWORDS)
        ai_sens = _truthy(flags.get("sensitive"))
        ai_break = _truthy(flags.get("is_breaking"))

        sensitivity = "HIGH" if (ai_sens or kw_sens or incoming == "D_SENSITIVE") else "LOW"
        is_breaking = bool(ai_break or kw_break or incoming == "C_WAIT")
        conf = str(flags.get("confidence") or "MEDIUM").strip().upper()
        if conf not in ("HIGH", "MEDIUM", "LOW"):
            conf = "MEDIUM"

        context_len = len(post.get("title", "") or "") + len(post.get("snippet", "") or "") + len(post.get("_deep_text", "") or post.get("deep_text", "") or post.get("content_for_analysis", "") or post.get("full_content", "") or "")

        hrs = post.get("hours_since_post")
        if not isinstance(hrs, (int, float)):
            hrs = 0 if is_breaking else 9999

        cc = post.get("comments")
        if cc is None:
            cc = post.get("comment_count")
        cc = cc if isinstance(cc, (int, float)) else 0
        is_question = "?" in (post.get("title", "") or "") or "?" in (post.get("snippet", "") or "")

        item = SimpleNamespace(is_question=is_question, comment_count=cc, hours_since_post=hrs)
        pre = incoming if incoming in ("A_PROMOTE", "B_ENGAGE", "D_SKIP") else "D_SKIP"
        analysis = {
            "decision": pre,
            "promotion_score": out.get("promo", 0) or 0,
            "sensitivity": sensitivity,
            "confidence": conf,
            "is_breaking_news": is_breaking,
        }
        _apply = _GUARDRAILS_APPLY or _fallback_guardrails
        decision, rejection, _thr = _apply(analysis, context_len, item)
        decision = _DECISION_RENAME.get(decision, decision)

        if incoming in _NEVER_RELAX:
            decision = incoming

        if decision == "A_PROMOTE" and kw_cap:
            if (out.get("promo", 0) or 0) >= B_ENGAGE and (out.get("opp", 0) or 0) >= OPP_ENGAGE:
                decision = "B_ENGAGE"
            else:
                decision = "D_SKIP"
            rejection = f"Layoff-type topic ('{kw_cap}') - Engage at most, no book mention."

        reason = str(out.get("reason", "") or "")
        if decision == "D_SENSITIVE":
            why = f"matched '{kw_sens}'" if kw_sens else ("AI flagged it sensitive" if ai_sens else "sensitive")
            reason = f"BLOCKED - sensitive topic ({why}). No draft allowed."
        elif rejection and decision != incoming:
            reason = f"{reason} | Guardrail: {rejection}".strip(" |")
        elif decision == "C_WAIT" and not reason:
            reason = "Breaking / fast news - 24h hold."

        out.update({
            "decision": decision,
            "reason": reason[:300],
            "sensitivity": sensitivity,
            "confidence": conf,
            "is_breaking_news": is_breaking,
            "scored_by": source,
        })
        return out
    except Exception as e:
        # Never break the app for a guardrail error - return original result with note.
        _o = dict(result)
        _o["reason"] = (str(_o.get("reason", "")) + f" | Guardrail error, kept original: {e}")[:300]
        _o["scored_by"] = source
        return _o

def assess_from_scores(post, relevance, conversation, recency, theme, reason, source, flags=None):
    """Gemini / Groq Assess: scores -> promo + opp + decision (Locked D1), then guardrail gate."""
    def _clamp(v, default):
        try:
            return max(0, min(100, int(v)))
        except Exception:
            return default
    relevance = _clamp(relevance, 50)
    conversation = _clamp(conversation, 50)
    recency = _clamp(recency, 70)
    promo = round(relevance * 0.30 + conversation * 0.35 + recency * 0.15 + 20)
    opp = round((relevance * 0.40 + conversation * 0.35 + recency * 0.25) / 10, 1)
    if promo >= A_PROMOTE and opp >= OPP_PROMOTE:
        decision = "A_PROMOTE"
    elif promo >= B_ENGAGE and opp >= OPP_ENGAGE:
        decision = "B_ENGAGE"
    else:
        decision = "D_SKIP"
    base = {"decision": decision, "promo": promo, "opp": opp, "theme": theme or "other", "reason": reason}
    return apply_assess_guardrails(post, base, source=source, flags=flags)

def assess_heuristic_guarded(post):
    """Heuristic Assess followed by the guardrail gate."""
    return apply_assess_guardrails(post, heuristic_assess(post), source="heuristic")

def select_for_gemini(posts):
    candidates = []
    for p in posts or []:
        if p.get("_auto_skip"):
            continue
        h = heuristic_assess(p)
        if h["decision"] in ("D_SENSITIVE", "C_WAIT"):
            continue
        candidates.append((h["opp"], h["promo"], p))
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [p for _, _, p in candidates[:MAX_GEMINI_CALLS_PER_RUN]]

def template_draft(post, analysis=None):
    from drafting.formatting import format_draft
    title = (post.get("title", "") or "this post").strip()
    raw = (
        f"This reframing of how teams actually decide under AI pressure stuck with me. "
        f"Your point on {title[:80]} shows why the non-automatable human edge still matters, judgment, empathy, and critical thinking alongside AI. "
        f"Where have you seen human judgment change a decision that AI alone would have got wrong?"
    )
    return format_draft(raw)
