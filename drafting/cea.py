"""#1 CEA prompt builder + #2 idea-seeding + theme rotation from v2.2."""
from __future__ import annotations
import os
from config import BOOK_TITLE, BOOK_LINK, BOOK_NAME_YOUTUBE, IDEA_PHRASES, PLAIN_TEXT_PLATFORMS
from drafting.formatting import word_range, book_mention_form

BOOK_THEMES = [
    {"name": "Centaur leadership", "detail": "Humans and AI together out-think either one alone."},
    {"name": "Purposeful rehearsal", "detail": "Structured games let leaders rehearse high-stakes decisions safely."},
    {"name": "Playbook over theory", "detail": "Modular exercises that leaders actively apply, not just read about."},
    {"name": "Non-automatable skills", "detail": "Judgment, intuition, empathy, ethics and creativity stay human."},
    {"name": "Hybrid Intelligence Era", "detail": "AI is a strategic collaborator; humans and AI co-evolve."},
    {"name": "Structured human-AI teaming", "detail": "The 7-Phase Model for building blended human-AI teams."},
]

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
    plain = item.platform in PLAIN_TEXT_PLATFORMS
    lo, hi = word_range(item.platform)
    context = item.content_for_analysis or item.snippet
    
    core_book = _load_grounding_text("00_book_core.txt")
    voice_rules = _load_grounding_text("04_voice.txt")

    themes_str = "\n".join(f"{i}. {t['name']} - {t['detail']}" for i, t in enumerate(BOOK_THEMES, 1))

    if item.decision.value == "A_PROMOTE":
        form = book_mention_form(variant, plain)
        book_instruction = f'Mention the book exactly once as {form}. Do NOT add any other book title, author name, or URL. Variant {variant}: 0=linked, 1=plain title curiosity, 2=curiosity phrase without link.'
    else:
        phrases = ", ".join(f'"{p}"' for p in IDEA_PHRASES)
        book_instruction = f'Do NOT mention the book, author, Amazon, or any URL. You MAY seed ONE idea phrase if it fits naturally: {phrases}. This builds association without selling.'

    prompt = f"""
{core_book}

{voice_rules}

Write 3 distinct comments for this post, each in a DIFFERENT archetype and connecting to a distinct core book theme.
Decision: {item.decision.value} ({item.decision_reason})
POST: {item.title} | {context}

BOOK THEMES (choose one per draft, the single most relevant to THIS post; never stack themes):
{themes_str}

STRUCTURE for EVERY comment — CEA:
1. Compliment (1 line): Name the SPECIFIC idea, not "great post".
2. Expand (2-3 lines): Add ONE insight connecting the post's idea to your chosen theme with a cause-and-effect bridge.
3. Ask (1 line): End with ONE easy, specific open question they want to answer.

ARCHETYPES:
- Draft 1 = Insight Add: Add a missing insight bridging back to human judgment or rehearsal.
- Draft 2 = Curious Question: Lead with a thoughtful question, then add insight.
- Draft 3 = Play Invite: Invite them to rehearse this exact dilemma as a 20-min simulation/game.

RULES: {lo}-{hi} words each. Warm, peer-to-peer practitioner tone. No emojis. No lecturing. No generic openers like "Great post".
BOOK RULE: {book_instruction}

Return JSON: {{"recommended":"...", "alternatives":["...","..."], "archetypes":["Insight Add","Curious Question","Play Invite"]}}
"""
    return prompt, book_instruction
