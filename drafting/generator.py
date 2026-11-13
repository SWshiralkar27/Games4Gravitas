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

def build_fallback_comment(item, plain: bool, variant: int = 0) -> str:
    # 2026-11-12: Stage 6A - Use book_mention_form (bold-only), NOT [BOOK_TITLE](BOOK_LINK).
    # Reason: Amazon link was leaking into Copy box for fallback drafts.
    # variant param added with default 0, so old calls build_fallback_comment(item, plain) still work.
    # 2026-11-13: Guardrail - book only for A_PROMOTE. Engage / Skip fallback gets no book.
    _dec_raw = item.get("decision") if isinstance(item, dict) else getattr(item, "decision", None)
    if hasattr(_dec_raw, "value"):
        _dec = str(_dec_raw.value)
    else:
        _dec = str(_dec_raw or "")
    _is_promote = (_dec == "A_PROMOTE")
    try:
        book = book_mention_form(variant, plain) if _is_promote else ""
    except Exception:
        book = (BOOK_NAME_YOUTUBE if plain else BOOK_TITLE) if _is_promote else ""
    item_title = item.get("title") if isinstance(item, dict) else getattr(item, "title", "")
    topic = item_title.split("|")[0].strip() or "this discussion"
    
    item_link = item.get("link") if isinstance(item, dict) else getattr(item, "link", "")
    if _is_promote:
        templates = [
            "This raises a real question about {t}: humans paired with AI out-think either one alone. That centaur leadership approach sits at the heart of {b}, where leaders learn to split the work between machine speed and human judgment. What would change in your team if you practised that split deliberately?",
            "This raises a real question about {t}: do leaders ever get to rehearse the hard calls before they arrive? In {b} I argue that structured games are a safe way to practise high-stakes decisions under pressure. Where do you see leaders getting that kind of practice today?",
            "This raises a real question about {t}: knowing a framework is not the same as using it under pressure. {b} is built as a playbook of modular exercises leaders apply, not passive theory they read. Which part of your own practice would you turn into an exercise first?",
        ]
    else:
        templates = [
            "This raises a real question about {t}: humans paired with AI out-think either one alone. That centaur leadership approach is about splitting the work between machine speed and human judgment. What would change in your team if you practised that split deliberately?",
            "This raises a real question about {t}: do leaders ever get to rehearse the hard calls before they arrive? Structured games are a safe way to practise high-stakes decisions under pressure. Where do you see leaders getting that kind of practice today?",
            "This raises a real question about {t}: knowing a framework is not the same as using it under pressure. The real test is turning it into modular exercises leaders apply, not passive theory they read. Which part of your own practice would you turn into an exercise first?",
        ]
    idx = int(hashlib.md5(item_link.encode() if item_link else b"fallback").hexdigest(), 16) % len(templates)
    if _is_promote:
        return templates[idx].format(t=topic, b=book)
    else:
        return templates[idx].format(t=topic)

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
    # Guardrail - Sensitive must never generate, even if button bypassed.
    if _decision == "D_SENSITIVE":
        _blocked = "BLOCKED - sensitive topic. No draft allowed."
        if isinstance(item, dict):
            item["comment"] = _blocked
            item["gemini_comment"] = _blocked
            item["groq_comment"] = ""
            item["grok_comment"] = ""
            item["fallback_comment"] = ""
            item["draft_source"] = "blocked"
            item["groq_note"] = _blocked
            item["grok_note"] = _blocked
            item["groq_verdict"] = "blocked"
            item["grok_verdict"] = "blocked"
        else:
            item.comment = _blocked
            item.gemini_comment = _blocked
            item.groq_comment = ""
            item.grok_comment = ""
            item.fallback_comment = ""
            item.draft_source = "blocked"
            item.groq_note = _blocked
            item.grok_note = _blocked
            item.groq_verdict = "blocked"
            item.grok_verdict = "blocked"
        return
    # 2026-11-12: FIX - Don't return early for D_SKIP. Button is "Generate draft anyway", so it must generate even for D_SKIP.
    # Only return if there is no decision at all. D_SKIP drafts get no book mention (only A_PROMOTE does).
    if not _decision:
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
        item["gemini_comment"] = ""
        item["fallback_comment"] = ""
        item["draft_source"] = ""
        item["groq_role"] = ""
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
        item.gemini_comment = ""
        item.fallback_comment = ""
        item.draft_source = ""
        item.groq_role = ""
        
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
        
        # 2026-11-12: FIX - Don't treat Gemini error text as a draft. Old code: any string >30 chars became fallback_raw_text,
        # so "429 Quota exceeded..." became a "Gemini draft", kept became non-empty, and Groq generation was never attempted (if not kept = False).
        # Now: if raw looks like an error / quota message, ignore it so Groq generate runs.
        _raw_str = raw.strip() if isinstance(raw, str) else ""
        _is_error_text = False
        if _raw_str:
            _low = _raw_str.lower()
            if ("quota" in _low and "exceed" in _low) or "429" in _raw_str or "503" in _raw_str or _low.startswith("error") or "api key not valid" in _low or "rate limit" in _low:
                # If it also contains JSON with recommended, parse above already handled it. Otherwise it's error text.
                if not parsed:
                    _is_error_text = True
        if not parsed and not _is_error_text and isinstance(raw, str) and len(raw.strip()) > 30:
            fallback_raw_text = raw.strip()
        elif isinstance(raw, dict):
            txt = raw.get("text") or raw.get("recommended", "")
            if txt and len(str(txt)) > 30:
                # Same error-text guard for dict text
                _tlow = str(txt).lower()
                if not (("quota" in _tlow and "exceed" in _tlow) or "429" in str(txt)):
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

    # 2026-11-12: Stage 6A - Groq as INDEPENDENT GENERATOR when Gemini produced nothing. Same prompt, fresh generation, NOT review.
    # 2026-11-12: FIX - Track groq_gen_error separately. Old code set groq_note in except, then is_fallback branch overwrote it with
    # "Fallback - Groq review skipped", hiding the real Groq error. Now groq_gen_error is preserved and shown in fallback note.
    groq_used_as_generator = False
    groq_gen_error = ""
    if not kept:
        if groq_client is None:
            groq_gen_error = "groq_client is None (app.py passed None / GroqClient not ready)"
            log.warning("Groq generation skipped: %s", groq_gen_error)
        else:
            try:
                groq_raw = groq_client.generate(prompt, max_tokens=900)
                groq_text = ""
                if groq_raw:
                    # REVIEW FIX: Groq may return JSON (prompt asks for JSON) - try parse first, else treat as raw text.
                    try:
                        from gemini_client import parse_gemini_json as _pg
                        _gparsed = _pg(groq_raw)
                        if _gparsed and isinstance(_gparsed, dict) and _gparsed.get("recommended"):
                            groq_text = str(_gparsed.get("recommended", "")).strip()
                        elif isinstance(groq_raw, str) and len(groq_raw.strip()) > 30:
                            groq_text = groq_raw.strip()
                        elif isinstance(groq_raw, dict):
                            groq_text = str(groq_raw.get("text") or groq_raw.get("recommended", "")).strip()
                    except Exception:
                        if isinstance(groq_raw, str):
                            groq_text = groq_raw.strip()
                # 2026-11-12: FIX - Record empty/short return as error. Old code left groq_text="" with no error, fell to fallback silently.
                if not groq_text:
                    groq_gen_error = f"Groq returned empty/short (raw={repr(groq_raw)[:200]})"
                elif len(groq_text) <= 30:
                    groq_gen_error = f"Groq text too short ({len(groq_text)} chars): {groq_text[:100]}"
                else:
                    d = clean_text(groq_text)
                    d = _sanitize_generic_opener(d)
                    if _decision == "A_PROMOTE":
                        plain = item_platform in PLAIN_TEXT_PLATFORMS
                        form = book_mention_form(variant, plain)
                        if BOOK_TITLE.lower() not in d.lower():
                            d = f"{d} For a structured playbook on this, see **{BOOK_TITLE}**."
                        d = re.sub(r"\[\*\*Games for Gravitas\*\*\]\([^)]+\)|\"Games for Gravitas\"|Games for Gravitas", "BOOKPLACEHOLDER", d, count=1)
                        d = d.replace("BOOKPLACEHOLDER", form)
                    d = format_for_platform(d, item_platform)
                    kept.append((d, "Insight Add"))
                    groq_used_as_generator = True
                    log.info("Groq generated fresh (Gemini failed) - Stage 6A")
            except Exception as _ge:
                groq_gen_error = str(_ge)[:300]
                log.warning("Groq generation (Stage 6A) failed: %s. Using fallback template.", _ge)
                # Don't set groq_note here - it will be set in the final assignment below from groq_gen_error, so fallback can't overwrite it.
    is_fallback = False
    if not kept:
        plain = item_platform in PLAIN_TEXT_PLATFORMS
        fallback_text = build_fallback_comment(item, plain, variant)
        fallback_text = _sanitize_generic_opener(fallback_text)
        fallback_text = format_for_platform(fallback_text, item_platform)
        kept.append((fallback_text, "Insight Add"))
        is_fallback = True

    # 2026-11-12: 3-slot tracking - keep Gemini / Groq / fallback separate so app.py can show all 3
    _gemini_val = ""
    _groq_authored_val = ""
    _fallback_val = ""
    if is_fallback:
        _fallback_val = kept[0][0]
    elif groq_used_as_generator:
        _groq_authored_val = kept[0][0]
    else:
        _gemini_val = kept[0][0]
    if isinstance(item, dict):
        item["gemini_comment"] = _gemini_val
        item["fallback_comment"] = _fallback_val
        item["draft_source"] = "fallback" if is_fallback else ("groq_generator" if groq_used_as_generator else "gemini")
        item["groq_role"] = "generator" if groq_used_as_generator else ("fallback" if is_fallback else "")
    else:
        item.gemini_comment = _gemini_val
        item.fallback_comment = _fallback_val
        item.draft_source = "fallback" if is_fallback else ("groq_generator" if groq_used_as_generator else "gemini")
        item.groq_role = "generator" if groq_used_as_generator else ("fallback" if is_fallback else "")

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

        # 2026-11-12: Stage 6A - Option B ONLY for real drafts. Never review a template, never self-review Groq output.
        if groq_used_as_generator:
            _note = "Groq used as generator (Gemini failed) - no self-review"
            if isinstance(item, dict):
                item["groq_available"] = True
                item["grok_available"] = True
                item["groq_comment"] = _groq_authored_val
                item["grok_comment"] = _groq_authored_val
                item["groq_note"] = _note
                item["grok_note"] = _note
                item["groq_verdict"] = "generator"
                item["grok_verdict"] = "generator"
            else:
                # 2026-11-12: FIX - Old code set available=False and comment="" here even though Groq succeeded, hiding the draft for object items.
                item.groq_available = True
                item.grok_available = True
                item.groq_comment = _groq_authored_val
                item.grok_comment = _groq_authored_val
                item.groq_note = _note
                item.grok_note = _note
                item.groq_verdict = "generator"
                item.grok_verdict = "generator"
        elif is_fallback:
            # 2026-11-12: FIX - Don't overwrite Groq generation error with generic "review skipped". Show why Groq generate failed.
            if groq_gen_error:
                _note = f"Fallback - Groq generation failed: {groq_gen_error}"
            else:
                _note = "Fallback - Groq generation not attempted (groq_client None)"
            if isinstance(item, dict):
                item["groq_available"] = False
                item["grok_available"] = False
                item["groq_comment"] = ""
                item["grok_comment"] = ""
                item["groq_note"] = _note
                item["grok_note"] = _note
                item["groq_verdict"] = "fallback"
                item["grok_verdict"] = "fallback"
            else:
                item.groq_available = False
                item.grok_available = False
                item.groq_comment = ""
                item.grok_comment = ""
                item.groq_note = _note
                item.grok_note = _note
                item.groq_verdict = "fallback"
                item.grok_verdict = "fallback"
        elif groq_client is not None:
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
                            item["groq_role"] = "review"
                            item["grok_role"] = "review"
                        else:
                            item.groq_comment = groq_comment_val
                            item.grok_comment = groq_comment_val
                            item.groq_note = groq_note_val
                            item.grok_note = groq_note_val
                            item.groq_verdict = groq_verdict_val
                            item.grok_verdict = groq_verdict_val
                            item.groq_available = True
                            item.grok_available = True
                            # 2026-11-12: FIX - Old code used item["groq_role"] on an object here, raising TypeError and hiding a successful review.
                            item.groq_role = "review"
                            item.grok_role = "review"
                    else:
                        # Review returned empty - record it, don't leave groq_note empty
                        _empty_note = "Groq review returned empty reviewed_draft"
                        if isinstance(item, dict):
                            item["groq_note"] = _empty_note
                            item["grok_note"] = _empty_note
                        else:
                            item.groq_note = _empty_note
                            item.grok_note = _empty_note
                else:
                    _none_note = "Groq review returned None"
                    if isinstance(item, dict):
                        item["groq_note"] = _none_note
                        item["grok_note"] = _none_note
                    else:
                        item.groq_note = _none_note
                        item.grok_note = _none_note
            except Exception as exc:
                log.warning("Groq review skipped: %s", exc)
                if isinstance(item, dict):
                    item["groq_available"] = False
                    item["grok_available"] = False
                    item["groq_note"] = f"Groq review failed: {str(exc)[:200]}"
                    item["grok_note"] = f"Groq review failed: {str(exc)[:200]}"
                else:
                    item.groq_available = False
                    item.grok_available = False
                    item.groq_note = f"Groq review failed: {str(exc)[:200]}"
                    item.grok_note = f"Groq review failed: {str(exc)[:200]}"
