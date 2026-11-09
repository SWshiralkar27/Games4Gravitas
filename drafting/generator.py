"""Draft generation — uses CEA, validation, formatting, rotation."""
from __future__ import annotations
import re, logging
from models import clean_text, Decision
from config import BOOK_TITLE, PLAIN_TEXT_PLATFORMS
from drafting.cea import build_draft_prompt
from drafting.formatting import format_for_platform, book_mention_form
from drafting.validation import is_valid_draft
log = logging.getLogger("digest")

def generate_drafts(client, item, variant: int = 0, grok_client=None) -> None:
    if item.decision not in (Decision.A_PROMOTE, Decision.B_ENGAGE):
        return
    item.draft_variant = variant
    item.grok_available = False
    item.grok_comment = ""
    item.grok_note = ""
    item.grok_verdict = ""
    prompt, _ = build_draft_prompt(item, variant)
    try:
        raw = client.generate(prompt, 2600)
    except Exception:
        return
    parsed = None
    try:
        from gemini_client import parse_gemini_json as _p
        parsed = _p(raw)
    except Exception:
        return
    if not parsed:
        return
    drafts = [clean_text(parsed.get("recommended", ""))] + [clean_text(str(a)) for a in parsed.get("alternatives", [])]
    archetypes = parsed.get("archetypes", ["Insight Add", "Curious Question", "Play Invite"])
    kept = []
    for idx, d in enumerate(drafts):
        ok, why = is_valid_draft(d, item.decision.value, item.platform in PLAIN_TEXT_PLATFORMS)
        if not ok:
            continue
        if item.decision == Decision.A_PROMOTE:
            plain = item.platform in PLAIN_TEXT_PLATFORMS
            form = book_mention_form(variant, plain)
            d = re.sub(r"\[\*\*Games for Gravitas\*\*\]\([^)]+\)|\"Games for Gravitas\"|Games for Gravitas", "BOOKPLACEHOLDER", d, count=1)
            d = d.replace("BOOKPLACEHOLDER", form)
        d = format_for_platform(d, item.platform)
        kept.append((d, archetypes[idx] if idx < len(archetypes) else ""))
    if kept:
        item.comment, item.draft_archetype = kept[0][0], kept[0][1]
        item.alternatives = [k[0] for k in kept[1:3]]
        # Dual-engine: Grok reviews ONLY the recommended Gemini draft (cost saver)
        if grok_client is not None:
            try:
                reviewed = grok_client.review_draft(item, item.comment, item.draft_archetype)
                if reviewed:
                    cand = reviewed.get("reviewed_draft", "").strip()
                    # Validate Grok draft with same rules + formatting
                    ok_g, _ = is_valid_draft(cand, item.decision.value, item.platform in PLAIN_TEXT_PLATFORMS)
                    if ok_g:
                        # Re-apply book rotation if Grok changed the mention form
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
