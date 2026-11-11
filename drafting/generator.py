"""Draft generation — robust handling of JSON or plain text responses with thematic enforcement and fallback integration."""
from __future__ import annotations
import re, logging, hashlib, json, os
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
            cleaned = cleaned[len(opener):].lstrip(" ,.!:-")
            if cleaned:
                cleaned = cleaned[0].upper() + cleaned[1:]
            break
    return cleaned

def build_fallback_comment(item, plain: bool) -> str:
    book = BOOK_NAME_YOUTUBE if plain else f"[{BOOK_TITLE}]({BOOK_LINK})"
    item_title = item.get("title") if isinstance(item, dict) else getattr(item, "title", "")
    topic = item_title.split("|")[0].strip() or "this discussion"
    
    item_link = item.get("link") if isinstance(item, dict) else getattr(item, "link", "")
    templates = [
        "This raises a real question about {t}: humans paired with AI out-think either one alone. That centaur leadership approach sits at the heart of {b}, where leaders learn to split the work between machine speed and human judgment. What would change in your team if you practised that split deliberately?",
        "This raises a real question about {t}: do leaders ever get to rehearse the hard calls before they arrive? In {b} I argue that structured games are a safe way to practise high-stakes decisions under pressure. Where do you see leaders getting that kind of practice today?",
        "This raises a real question about {t}: knowing a framework is not the same as using it under pressure. {b} is built as a playbook of modular exercises leaders apply, not passive theory they read. Which part of your own practice would you turn into an exercise first?",
    ]
    idx = int(hashlib.md5(item_link.encode() if item_link else b"fallback").hexdigest(), 16) % len(templates)
    return templates[idx].format(t=topic, b=book)

def generate_drafts(client, item, variant: int = 0, groq_client=None, grok_client=None) -> None:
    # 2026-11-11: Stage 5 - Grok -> Groq rename. Accept both param names, prefer groq. Dual-write groq_* + grok_* for old app.py until Stage 5B.
    if groq_client is None:
        groq_client = grok_client
    grok_client = groq_client
    # 2026-11-11: Fix - decision in assessed dicts is string "A_PROMOTE"/"B_ENGAGE", not Decision enum.
    # Reason: old check `if _decision not in (Decision.A_PROMOTE, Decision.B_ENGAGE)` was always True for strings,
    # so function returned early with no draft and button appeared to do nothing.
    _decision_raw = item.get("decision") if isinstance(item, dict) else getattr(item, "decision", None)
    # Normalize both string and enum to plain string "A_PROMOTE" / "B_ENGAGE" for all checks below.
    if hasattr(_decision_raw, "value"):
        _decision_str = str(_decision_raw.value)
    else:
        _decision_str = str(_decision_raw or "")
    _decision = _decision_str
    if _decision not in ("A_PROMOTE", "B_ENGAGE"):
        return
    
    if isinstance(item, dict):
        item["draft_variant"] = variant
        item["grok_available"] = False
        item["groq_available"] = False
        item["grok_comment"] = ""
        item["groq_comment"] = ""
        item["grok_note"] = ""
        item["groq_note"] = ""
        item["grok_verdict"] = ""
        item["groq_verdict"] = ""
    else:
        item.draft_variant = variant
        item.grok_available = False
        item.groq_available = False
        item.grok_comment = ""
        item.groq_comment = ""
        item.grok_note = ""
        item.groq_note = ""
        item.grok_verdict = ""
        item.groq_verdict = ""
        
    prompt, _ = build_draft_prompt(item, variant)
    raw = None
    # 2026-11-11: Fix - client was None when app.py passed st.session_state.get("gemini_client") which is never set.
    # Reason: caused "'NoneType' object has no attribute 'generate'" in logs, 10x fallback to template.
    # Fix: create GeminiClient from GEMINI_API_KEY only if client is None.
    if client is None:
        try:
            from gemini_client import GeminiClient as _GC
            # 2026-11-11: Fix - use GEMINI_API_KEY only, not GOOGLE_API_KEY.
            # Reason: google-genai picks GOOGLE_API_KEY when both are set ("Both GOOGLE_API_KEY and GEMINI_API_KEY are set. Using GOOGLE_API_KEY"),
            # which is the wrong key and breaks auth. Explicitly pass GEMINI_API_KEY.
            _api_key = (os.getenv("GEMINI_API_KEY", "") or "").strip()
            if _api_key:
                client = _GC(api_key=_api_key)
            else:
                log.warning("Gemini client is None and no GEMINI_API_KEY in Secrets. Using fallback template.")
                client = None
        except Exception as _ce:
            log.warning("Gemini client create failed: %s. Using fallback template.", _ce)
            client = None
    try:
        if client is None:
            raise Exception("Gemini client is None (not ready)")
        # 2026-11-11: Fix - check is_ready() before generate.
        # Reason: if GeminiClient init failed, _client is None and generate would raise confusing AttributeError.
        if hasattr(client, "is_ready") and not client.is_ready():
            raise Exception(f"Gemini client not ready: {getattr(client, 'init_error', 'unknown')}")
        raw = client.generate(prompt, 2600)
    except Exception as ex:
        log.warning("Gemini generation failed: %s. Using fallback template.", ex)

    parsed = None
    fallback_raw_text = ""

    if raw:
        try:
            from gemini_client import parse_gemini_json as _p
            parsed = _p(raw)
        except Exception:
            pass
        
        if not parsed and isinstance(raw, str) and len(raw.strip()) > 30:
            fallback_raw_text = raw.strip()
        elif isinstance(raw, dict):
            txt = raw.get("text") or raw.get("recommended", "")
            if txt and len(str(txt)) > 30:
                fallback_raw_text = str(txt).strip()

    kept = []
    item_platform = item.get("platform") if isinstance(item, dict) else getattr(item, "platform", "")
    
    if parsed and isinstance(parsed, dict):
        drafts = [clean_text(parsed.get("recommended", ""))] + [clean_text(str(a)) for a in parsed.get("alternatives", [])]
        archetypes = parsed.get("archetypes", ["Insight Add", "Curious Question", "Play Invite"])
        for idx, d in enumerate(drafts):
            if not d:
                continue
            d = _sanitize_generic_opener(d)
            # 2026-11-11: Fix - use normalized _decision string, not Decision enum.
            # Reason: old `if _decision == Decision.A_PROMOTE` was False for string "A_PROMOTE", so book mention logic never ran.
            if _decision == "A_PROMOTE":
                plain = item_platform in PLAIN_TEXT_PLATFORMS
                form = book_mention_form(variant, plain)
                if BOOK_TITLE.lower() not in d.lower():
                    d = f"{d} (Explore more in **{BOOK_TITLE}**)."
                d = re.sub(r"\[\*\*Games for Gravitas\*\*\]\([^)]+\)|\"Games for Gravitas\"|Games for Gravitas", "BOOKPLACEHOLDER", d, count=1)
                d = d.replace("BOOKPLACEHOLDER", form)
            d = format_for_platform(d, item_platform)
            kept.append((d, archetypes[idx] if idx < len(archetypes) else ""))

    elif fallback_raw_text:
        d = clean_text(fallback_raw_text)
        d = _sanitize_generic_opener(d)
        # 2026-11-11: Fix - same string-vs-enum fix as above, for fallback path.
        if _decision == "A_PROMOTE":
            plain = item_platform in PLAIN_TEXT_PLATFORMS
            form = book_mention_form(variant, plain)
            if BOOK_TITLE.lower() not in d.lower():
                d = f"{d} For a structured playbook on this, see **{BOOK_TITLE}**."
            d = re.sub(r"\[\*\*Games for Gravitas\*\*\]\([^)]+\)|\"Games for Gravitas\"|Games for Gravitas", "BOOKPLACEHOLDER", d, count=1)
            d = d.replace("BOOKPLACEHOLDER", form)
        d = format_for_platform(d, item_platform)
        kept.append((d, "Insight Add"))

    if not kept:
        plain = item_platform in PLAIN_TEXT_PLATFORMS
        fallback_text = build_fallback_comment(item, plain)
        fallback_text = _sanitize_generic_opener(fallback_text)
        fallback_text = format_for_platform(fallback_text, item_platform)
        kept.append((fallback_text, "Insight Add"))

    if kept:
        comment_val, archetype_val = kept[0][0], kept[0][1]
        alternatives_val = [k[0] for k in kept[1:3]]
        
        if isinstance(item, dict):
            item["comment"] = comment_val
            item["draft_archetype"] = archetype_val
            item["alternatives"] = alternatives_val
        else:
            item.comment = comment_val
            item.draft_archetype = archetype_val
            item.alternatives = alternatives_val

        if groq_client is not None:
            try:
                reviewed = groq_client.review_draft(item, comment_val, archetype_val)
                if reviewed:
                    cand = reviewed.get("reviewed_draft", "").strip()
                    if cand:
                        cand = _sanitize_generic_opener(cand)
                        # 2026-11-11: Fix - same string-vs-enum fix as above, for Groq review path.
                        if _decision == "A_PROMOTE":
                            plain = item_platform in PLAIN_TEXT_PLATFORMS
                            form = book_mention_form(variant, plain)
                            cand = re.sub(r"\[\*\*Games for Gravitas\*\*\]\([^)]+\)|\"Games for Gravitas\"|Games for Gravitas", "BOOKPLACEHOLDER", cand, count=1)
                            cand = cand.replace("BOOKPLACEHOLDER", form)
                        
                        groq_comment_val = format_for_platform(cand, item_platform)
                        groq_note_val = reviewed.get("what_changed", "")
                        groq_verdict_val = reviewed.get("verdict", "")
                        
                        if isinstance(item, dict):
                            item["groq_comment"] = groq_comment_val
                            item["grok_comment"] = groq_comment_val
                            item["groq_note"] = groq_note_val
                            item["grok_note"] = groq_note_val
                            item["groq_verdict"] = groq_verdict_val
                            item["grok_verdict"] = groq_verdict_val
                            item["groq_available"] = True
                            item["grok_available"] = True
                        else:
                            item.groq_comment = groq_comment_val
                            item.grok_comment = groq_comment_val
                            item.groq_note = groq_note_val
                            item.grok_note = groq_note_val
                            item.groq_verdict = groq_verdict_val
                            item.grok_verdict = groq_verdict_val
                            item.groq_available = True
                            item.grok_available = True
            except Exception as exc:
                log.warning("Groq review skipped: %s", exc)
                if isinstance(item, dict):
                    item["groq_available"] = False
                    item["grok_available"] = False
                else:
                    item.groq_available = False
                    item.grok_available = False
