"""Draft generation — robust handling of JSON or plain text responses with thematic enforcement and fallback integration."""
from __future__ import annotations
import re, logging, hashlib, json
from models import clean_text, Decision
from config import BOOK_TITLE, BOOK_LINK, BOOK_NAME_YOUTUBE, PLAIN_TEXT_PLATFORMS
from drafting.cea import build_draft_prompt
from drafting.formatting import format_for_platform, book_mention_form
from drafting.validation import is_valid_draft

log = logging.getLogger("digest")

BANNED_OPENERS = [
    "great post", "great question", "thanks for sharing", "thank you for sharing",
    "nice post", "love this", "great comprehensive guide", "great insights",
    "excellent article", "fascinating read"
]

def _sanitize_generic_opener(text: str) -> str:
    """Removes generic fluff openers so comments sound authentic and peer-to-peer."""
    if not text:
        return ""
    cleaned = text.strip()
    lower_c = cleaned.lower()
    for opener in BANNED_OPENERS:
        if lower_c.startswith(opener):
            # Cut off the banned opener phrase and any immediate punctuation/whitespace following it
            cleaned = cleaned[len(opener):].lstrip(" ,.!:-")
            # Capitalize the new starting letter if necessary
            if cleaned:
                cleaned = cleaned[0].upper() + cleaned[1:]
            break
    return cleaned

def build_fallback_comment(item, plain: bool) -> str:
    book = BOOK_NAME_YOUTUBE if plain else f"[{BOOK_TITLE}]({BOOK_LINK})"
    topic = item.title.split("|")[0].strip() or "this discussion"
    templates = [
        "This raises a real question about {t}: humans paired with AI out-think either one alone. That centaur leadership approach sits at the heart of {b}, where leaders learn to split the work between machine speed and human judgment. What would change in your team if you practised that split deliberately?",
        "This raises a real question about {t}: do leaders ever get to rehearse the hard calls before they arrive? In {b} I argue that structured games are a safe way to practise high-stakes decisions under pressure. Where do you see leaders getting that kind of practice today?",
        "This raises a real question about {t}: knowing a framework is not the same as using it under pressure. {b} is built as a playbook of modular exercises leaders apply, not passive theory they read. Which part of your own practice would you turn into an exercise first?",
    ]
    idx = int(hashlib.md5(item.link.encode() if item.link else b"fallback").hexdigest(), 16) % len(templates)
    return templates[idx].format(t=topic, b=book)

def generate_drafts(client, item, variant: int = 0, grok_client=None) -> None:
    _decision = item.get("decision") if isinstance(item, dict) else getattr(item, "decision", None)
    if item.decision not in (Decision.A_PROMOTE, Decision.B_ENGAGE):
        return
    item.draft_variant = variant
    item.grok_available = False
    item.grok_comment = ""
    item.grok_note = ""
    item.grok_verdict = ""
    
    prompt, _ = build_draft_prompt(item, variant)
    raw = None
    try:
        raw = client.generate(prompt, 2600)
    except Exception as ex:
        log.warning("Gemini generation failed: %s. Using fallback template.", ex)

    parsed = None
    fallback_raw_text = ""

    if raw:
        # Try parsing as JSON first
        try:
            from gemini_client import parse_gemini_json as _p
            parsed = _p(raw)
        except Exception:
            pass
        
        # If JSON parsing failed, check if raw is a plain string response from the LLM
        if not parsed and isinstance(raw, str) and len(raw.strip()) > 30:
            fallback_raw_text = raw.strip()
        elif isinstance(raw, dict):
            # If client.generate returned a dict wrapper
            txt = raw.get("text") or raw.get("recommended", "")
            if txt and len(str(txt)) > 30:
                fallback_raw_text = str(txt).strip()

    kept = []
    if parsed and isinstance(parsed, dict):
        drafts = [clean_text(parsed.get("recommended", ""))] + [clean_text(str(a)) for a in parsed.get("alternatives", [])]
        archetypes = parsed.get("archetypes", ["Insight Add", "Curious Question", "Play Invite"])
        for idx, d in enumerate(drafts):
            if not d:
                continue
            d = _sanitize_generic_opener(d)
            if item.decision == Decision.A_PROMOTE:
                plain = item.platform in PLAIN_TEXT_PLATFORMS
                form = book_mention_form(variant, plain)
                # Ensure book mention is correctly inserted if missing
                if BOOK_TITLE.lower() not in d.lower():
                    d = f"{d} (Explore more in **{BOOK_TITLE}**)."
                d = re.sub(r"\[\*\*Games for Gravitas\*\*\]\([^)]+\)|\"Games for Gravitas\"|Games for Gravitas", "BOOKPLACEHOLDER", d, count=1)
                d = d.replace("BOOKPLACEHOLDER", form)
            d = format_for_platform(d, item.platform)
            kept.append((d, archetypes[idx] if idx < len(archetypes) else ""))

    # If JSON parsing wasn't used but we have a valid text response from Gemini
    elif fallback_raw_text:
        d = clean_text(fallback_raw_text)
        d = _sanitize_generic_opener(d)
        if item.decision == Decision.A_PROMOTE:
            plain = item.platform in PLAIN_TEXT_PLATFORMS
            form = book_mention_form(variant, plain)
            if BOOK_TITLE.lower() not in d.lower():
                d = f"{d} For a structured playbook on this, see **{BOOK_TITLE}**."
            d = re.sub(r"\[\*\*Games for Gravitas\*\*\]\([^)]+\)|\"Games for Gravitas\"|Games for Gravitas", "BOOKPLACEHOLDER", d, count=1)
            d = d.replace("BOOKPLACEHOLDER", form)
        d = format_for_platform(d, item.platform)
        kept.append((d, "Insight Add"))

    # Ultimate fallback if everything else failed
    if not kept:
        plain = item.platform in PLAIN_TEXT_PLATFORMS
        fallback_text = build_fallback_comment(item, plain)
        fallback_text = _sanitize_generic_opener(fallback_text)
        fallback_text = format_for_platform(fallback_text, item.platform)
        kept.append((fallback_text, "Insight Add"))

    if kept:
        item.comment, item.draft_archetype = kept[0][0], kept[0][1]
        item.alternatives = [k[0] for k in kept[1:3]]

        # Dual-engine Grok review if available
        if grok_client is not None:
            try:
                reviewed = grok_client.review_draft(item, item.comment, item.draft_archetype)
                if reviewed:
                    cand = reviewed.get("reviewed_draft", "").strip()
                    if cand:
                        cand = _sanitize_generic_opener(cand)
                        if item.decision == Decision.A_PROMOTE:
                            plain = item.platform in PLAIN_TEXT_PLATFORMS
                            form = book_mention_form(variant, plain)
                            cand = re.sub(r"\[\*\*Games for Gravitas\*\*\]\([^)]+\)|\"Games for Gravitas\"|Games for Gravitas", "BOOKPLACEHOLDER", cand, count=1)
                            cand = cand.replace("BOOKPLACEHOLDER", form)
                        item.grok_comment = format_for_platform(cand, item.platform)
                        item.grok_note = reviewed.get("what_changed", "")
                        item.grok_verdict = reviewed.get("verdict", "")
                        item.grok_available = True
            except Exception as exc:
                log.warning("Grok review skipped: %s", exc)
                item.grok_available = False
