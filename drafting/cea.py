"""#1 CEA prompt builder + #2 idea-seeding + #10 rotation hint."""
from __future__ import annotations
from config import BOOK_TITLE, BOOK_URL, BOOK_NAME_YOUTUBE, IDEA_PHRASES, PLAIN_TEXT_PLATFORMS
from drafting.formatting import word_range, book_mention_form

def build_draft_prompt(item, variant: int) -> tuple[str, str]:
    plain = item.platform in PLAIN_TEXT_PLATFORMS
    lo, hi = word_range(item.platform)
    context = item.content_for_analysis
    if item.decision.value == "A_PROMOTE":
        form = book_mention_form(variant, plain)
        book_instruction = f'Mention the book exactly once as {form}. Do NOT add any other book title, author name, or URL. Variant {variant}: 0=linked, 1=plain title curiosity, 2=curiosity phrase without link.'
    else:
        phrases = ", ".join(f'"{p}"' for p in IDEA_PHRASES)
        book_instruction = f'Do NOT mention the book, author, Amazon, or any URL. You MAY seed ONE idea phrase if it fits naturally: {phrases}. This builds association without selling.'
    prompt = f"""
Write 3 distinct comments for this post, each in a DIFFERENT archetype.
Decision: {item.decision.value} ({item.decision_reason})
POST: {item.title} | {context}
STRUCTURE for EVERY comment — CEA:
1. Compliment (1 line): Name the SPECIFIC idea, not "great post".
2. Expand (2-3 lines): Add ONE insight they did not say. Connect to a book theme if natural.
3. Ask (1 line): End with ONE easy, specific question they want to answer.
ARCHETYPES:
- Draft 1 = Insight Add: Add a missing insight.
- Draft 2 = Curious Question: Lead with a thoughtful question, then add insight.
- Draft 3 = Play Invite: Invite them to rehearse this exact dilemma as a 20-min game. Example: "We rehearse this as a 20-min game — leaders decide with incomplete data. Most change their answer after round 2." Ask if they have ever rehearsed a decision like this.
RULES: {lo}-{hi} words each. Warm, peer-to-peer. No emojis. No lecturing. No generic openers like "Great post".
BOOK RULE: {book_instruction}
Return JSON: {{"recommended":"...", "alternatives":["...","..."], "archetypes":["Insight Add","Curious Question","Play Invite"]}}
"""
    return prompt, book_instruction
