"""#1 CEA prompt builder + #2 idea-seeding + #10 rotation hint with grounding file injection."""
from __future__ import annotations
import os
from config import BOOK_TITLE, BOOK_URL, BOOK_NAME_YOUTUBE, IDEA_PHRASES, PLAIN_TEXT_PLATFORMS
from drafting.formatting import word_range, book_mention_form

def _load_grounding_text(filename: str) -> str:
    """Helper to safely load text files from the grounding folder."""
    try:
        # Assuming grounding files are in a folder named 'grounding' or root
        paths = [os.path.join("grounding", filename), filename]
        for path in paths:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip()
    except Exception:
        pass
    return ""

def _select_grounding_category(post_text: str) -> str:
    """Selects the correct category file based on post keywords."""
    text = post_text.lower()
    if any(w in text for w in ["roi", "budget", "cost", "transform", "change management", "metrics"]):
        return _load_grounding_text("03_roi_architecture.txt")
    elif any(w in text for w in ["webinar", "course", "lecture", "slide", "training", "passive", "e-learning"]):
        return _load_grounding_text("02_passive_ld.txt")
    else:
        return _load_grounding_text("01_hybrid_intelligence.txt")

def build_draft_prompt(item, variant: int) -> tuple[str, str]:
    plain = item.platform in PLAIN_TEXT_PLATFORMS
    lo, hi = word_range(item.platform)
    context = item.content_for_analysis
    
    # Load core book context, voice rules, and relevant category grounding
    core_book = _load_grounding_text("00_book_core.txt")
    voice_rules = _load_grounding_text("04_voice.txt")
    category_grounding = _select_grounding_category(item.title + " " + context)

    if item.decision.value == "A_PROMOTE":
        form = book_mention_form(variant, plain)
        book_instruction = f'Mention the book exactly once as {form}. Do NOT add any other book title, author name, or URL. Variant {variant}: 0=linked, 1=plain title curiosity, 2=curiosity phrase without link.'
    else:
        phrases = ", ".join(f'"{p}"' for p in IDEA_PHRASES)
        book_instruction = f'Do NOT mention the book, author, Amazon, or any URL. You MAY seed ONE idea phrase if it fits naturally: {phrases}. This builds association without selling.'

    prompt = f"""
{core_book}

{category_grounding}

{voice_rules}

Write 3 distinct comments for this post, each in a DIFFERENT archetype.
Decision: {item.decision.value} ({item.decision_reason})
POST: {item.title} | {context}

STRUCTURE for EVERY comment — CEA:
1. Compliment (1 line): Name the SPECIFIC idea, not "great post".
2. Expand (2-3 lines): Add ONE insight they did not say. Use a data point or argument from the grounding material above if it fits.
3. Ask (1 line): End with ONE easy, specific open question they want to answer.

RULES: {lo}-{hi} words each. Warm, peer-to-peer practitioner tone. No emojis. No lecturing.
BOOK RULE: {book_instruction}

Return JSON: {{"recommended":"...", "alternatives":["...","..."], "archetypes":["Insight Add","Curious Question","Play Invite"]}}
"""
    return prompt, book_instruction
