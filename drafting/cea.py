#1 CEA prompt builder + #2 idea-seeding + theme rotation from v2.2.
from __future__ import annotations
import os
from config import BOOK_TITLE, BOOK_LINK, BOOK_NAME_YOUTUBE, IDEA_PHRASES, PLAIN_TEXT_PLATFORMS
from drafting.formatting import word_range, book_mention_form

# ACT-1: Prefer BOOK_THEMES from config (locked 5 themes) if present, else use local fallback.
# Safe import: if config does not have BOOK_THEMES yet, app keeps working with fallback.
try:
    from config import BOOK_THEMES as _CONFIG_BOOK_THEMES
except Exception:
    _CONFIG_BOOK_THEMES = None

_FALLBACK_BOOK_THEMES = [
    {"name": "Centaur leadership", "detail": "Humans and AI together out-think either one alone."},
    {"name": "Purposeful rehearsal", "detail": "Structured games let leaders rehearse high-stakes decisions safely."},
    {"name": "Playbook over theory", "detail": "Modular exercises that leaders actively apply, not just read about."},
    {"name": "Non-automatable skills", "detail": "Judgment, intuition, empathy, ethics and creativity stay human."},
    {"name": "Hybrid Intelligence Era", "detail": "AI is a strategic collaborator; humans and AI co-evolve."},
    {"name": "Structured human-AI teaming", "detail": "The 7-Phase Model for building blended human-AI teams."},
]

BOOK_THEMES = _CONFIG_BOOK_THEMES if isinstance(_CONFIG_BOOK_THEMES, list) and len(_CONFIG_BOOK_THEMES) > 0 else _FALLBACK_BOOK_THEMES

def _format_themes(themes) -> str:
    lines = []
    for i, t in enumerate(themes, 1):
        if isinstance(t, dict):
            lines.append(f"{i}. {t.get('name', '')} - {t.get('detail', '')}")
        else:
            s = str(t).strip()
            if s and s[0].isdigit() and "." in s[:4]:
                lines.append(s)
            else:
                lines.append(f"{i}. {s}")
    return "\n".join(lines)

# ACT-1: Map keywords in the post to a grounding category file.
_CATEGORY_FILE_BY_KEYWORD = {
    "human edge": "01_hybrid_intelligence.txt",
    "hybrid intelligence": "01_hybrid_intelligence.txt",
    "experiential": "02_passive_ld.txt",
    "passive": "02_passive_ld.txt",
    "fail-safe": "02_passive_ld.txt",
    "failsafe": "02_passive_ld.txt",
    "facilitation": "03_roi_architecture.txt",
    "debrief": "03_roi_architecture.txt",
    "roi": "03_roi_architecture.txt",
    "payoff": "03_roi_architecture.txt",
    "prioritization": "03_roi_architecture.txt",
    "kirkpatrick": "03_roi_architecture.txt",
}

def _select_category_file(text: str) -> str:
    low = (text or "").lower()
    for kw, fname in _CATEGORY_FILE_BY_KEYWORD.items():
        if kw in low:
            return fname
    return ""

def _load_grounding_text(filename: str) -> str:
    try:
        paths = [os.path.join("grounding", filename), filename]
        for path in paths:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip()
    except Exception:
        pass
    return ""

def build_draft_prompt(item, variant: int) -> tuple[str, str]:
    _platform = item.get("platform") if isinstance(item, dict) else getattr(item, "platform", "")
    plain = _platform in PLAIN_TEXT_PLATFORMS
    lo, hi = word_range(_platform)
    if isinstance(item, dict):
        context = item.get("content_for_analysis") or item.get("snippet") or item.get("title") or ""
    else:
        context = getattr(item, "content_for_analysis", "") or getattr(item, "snippet", "") or ""
    
    core_book = _load_grounding_text("00_book_core.txt")
    voice_rules = _load_grounding_text("04_voice.txt")

    themes_str = _format_themes(BOOK_THEMES)

    _decision = item.get("decision") if isinstance(item, dict) else getattr(item, "decision", "")
    _decision_val = getattr(_decision, "value", _decision) if not isinstance(_decision, str) else _decision
    _decision_reason = item.get("decision_reason", "") if isinstance(item, dict) else getattr(item, "decision_reason", "")
    _title = item.get("title", "") if isinstance(item, dict) else getattr(item, "title", "")

    # ACT-1: Load selected category file based on post content. If none fits, load nothing.
    _search_text = f"{_title} {context} {_decision_reason}"
    _category_file = _select_category_file(_search_text)
    category_text = _load_grounding_text(_category_file) if _category_file else ""

    if _decision_val == "A_PROMOTE":
        form = book_mention_form(variant, plain)
        book_instruction = f'Mention the book exactly once as {form}. Do NOT add any other book title, author name, or URL. Variant {variant}: 0=linked, 1=plain title curiosity, 2=curiosity phrase without link.'
    else:
        phrases = ", ".join(f'"{p}"' for p in IDEA_PHRASES)
        book_instruction = f'Do NOT mention the book, author, 【entity-Amazon¦canonical_name=Amazon】, or any URL. You MAY seed ONE idea phrase if it fits naturally: {phrases}. This builds association without selling.'

    prompt = f"""
{core_book}

{voice_rules}

Write 3 distinct comments for this post, each in a DIFFERENT archetype and connecting to a distinct core book theme.
Decision: {_decision_val} ({_decision_reason})
POST: {_title} | {context}

BOOK THEMES (choose one per draft, the single most relevant to THIS post; never stack themes):
{themes_str}

SELECTED GROUNDING CATEGORY FILE (use only data from this file plus BOOK THEMES above. If this section is empty, use no data point, do not invent one):
{category_text}

STRUCTURE for EVERY comment — CEA:
1. Compliment (1 line): Name the SPECIFIC idea, not "great post".
2. Expand (2-3 lines): Add ONE insight connecting the post's idea to your chosen theme with a cause-and-effect bridge.
3. Ask (1 line): End with ONE easy, specific open question they want to answer.

ARCHETYPES:
- Draft 1 = Insight Add: Add a missing insight bridging back to human judgment or rehearsal.
- Draft 2 = Curious Question: Lead with a thoughtful question, then add insight.
- Draft 3 = Play Invite: Invite them to rehearse this exact dilemma as a 20-min simulation/game.

RULES: {lo}-{hi} words each. Warm, peer-to-peer practitioner tone. No emojis. No lecturing. No generic openers like "Great post".
DATA RULE: Use exactly ONE data point from the selected grounding category or BOOK THEMES above if it fits. Do NOT combine claims from different snippets. Do NOT merge treasure hunt, VR, and adoption claims into one sentence. Keep each claim with its original subject: treasure hunt = 3,000 senior oil managers mastered software within one month, VR = up to a 30% reduction in training duration, virtual games = 20% to 30% faster adoption. CORRECT: VR training simulations demonstrated up to a 30% reduction in training duration. INCORRECT: A virtual treasure hunt cut training time by up to 30%. If no category file is provided and no BOOK THEMES data point fits, use no data point. Do not invent numbers, studies, or claims not in grounding.
BOOK RULE: {book_instruction}

Return JSON: {{"recommended":"...", "alternatives":["...","..."], "archetypes":["Insight Add","Curious Question","Play Invite"]}}
"""
    return prompt, book_instruction
