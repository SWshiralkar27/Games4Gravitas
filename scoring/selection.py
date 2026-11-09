"""Selection + theme cap / diversity — #6."""
from __future__ import annotations
from collections import Counter
from config import PLATFORM_ORDER, RELEVANCE_THRESHOLD, MAX_RESULTS_PER_SOURCE, MAX_PROMOTE_PER_THEME, MIN_THEMES_PER_RUN
from scoring.relevance import calculate_relevance_score
from scoring.opportunity import calculate_opportunity_score
from models import Decision

def select_candidates(items):
    selected = []
    for p in PLATFORM_ORDER:
        pool = [i for i in items if i.platform == p]
        for i in pool:
            i.relevance_score = calculate_relevance_score(i)
            i.opportunity_score = calculate_opportunity_score(i)
        pool.sort(key=lambda i: (i.opportunity_score, i.relevance_score), reverse=True)
        selected.extend([i for i in pool if i.relevance_score >= RELEVANCE_THRESHOLD][:MAX_RESULTS_PER_SOURCE])
    return selected

def enforce_theme_cap_and_diversity(selected):
    counts = Counter()
    for it in selected:
        if it.decision == Decision.A_PROMOTE:
            theme = it.book_theme or "General"
            counts[theme] += 1
            if counts[theme] > MAX_PROMOTE_PER_THEME:
                it.decision = Decision.B_ENGAGE
                it.rejection_reason = f"Theme cap: max {MAX_PROMOTE_PER_THEME} Promote per theme per run. Downgraded to Engage."
                it.decision_reason += " [Theme cap downgrade]"
    themes = {it.book_theme for it in selected if it.book_theme and it.decision in (Decision.A_PROMOTE, Decision.B_ENGAGE)}
    return {"themes_covered": len(themes), "diversity_ok": len(themes) >= MIN_THEMES_PER_RUN, "counts": dict(counts)}
