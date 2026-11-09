"""Exporters — HTML/MD/JSON with new fields: C_WAIT, opportunity, repurpose, archetype."""
from __future__ import annotations
import html, json
from dataclasses import asdict
from pathlib import Path
from config import PLATFORM_LABEL

_HTML_CSS = "body{font:15px/1.55 -apple-system,sans-serif;background:#f5f6f8;color:#202733;margin:0}.wrap{max-width:1000px;margin:auto;padding:24px}.card{background:white;border:1px solid #dfe3e8;border-radius:10px;padding:18px;margin:16px 0}.meta{color:#667085;font-size:13px}.pill{display:inline-block;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;background:#e5e7eb}.pill.A_PROMOTE{background:#dcfce7;color:#166534}.pill.B_ENGAGE{background:#dbeafe;color:#1e40af}.pill.C_SENSITIVE{background:#fee2e2;color:#991b1b}.pill.C_WAIT{background:#fef3c7;color:#92400e}.pill.D_SKIP{background:#e5e7eb;color:#374151}.draft{border-left:3px solid #d6a23a;padding:10px 14px;margin:12px 0;background:#fafafa}button{border:0;border-radius:6px;padding:7px 12px;background:#1d4ed8;color:white;cursor:pointer;font-size:13px}a{color:#1d4ed8;text-decoration:none}.badge{display:inline-block;background:#fef3c7;color:#92400e;border-radius:6px;padding:2px 8px;font-size:12px;font-weight:600}"

def write_html(digest, path: Path):
    esc = lambda s: html.escape(str(s or ""), quote=True)
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><style>{_HTML_CSS}</style></head><body><div class='wrap'>", f"<h1>Leadership AI Digest — {esc(digest.date)}</h1><p>{esc(digest.summary)}</p>"]
    for p, items in digest.items_by_platform.items():
        parts.append(f"<h2>{esc(PLATFORM_LABEL.get(p, p))}</h2>")
        for n, it in enumerate(items, 1):
            parts.append(f"<section class='card'><h3><a href='{esc(it.url)}' target='_blank' rel='noopener noreferrer'>{esc(it.title)}</a></h3>")
            parts.append(f"<p><span class='pill {esc(it.decision.value)}'>{esc(it.decision.value)}</span> <span class='meta'>Promo: {it.promotion_score} | Opp: {it.opportunity_score} | Sens: {it.sensitivity.value} | Conf: {it.confidence.value} | Theme: {esc(it.book_theme)}</span></p>")
            if it.repurpose_candidate:
                parts.append(f"<p><span class='badge'>Repurpose idea: {esc(it.repurpose_reason)}</span></p>")
            parts.append(f"<p class='meta'><b>Why:</b> {esc(it.decision_reason)}</p>")
            if it.comment:
                draft_id = f"draft-{p}-{n}"
                html_draft = esc(it.comment).replace("\n", "<br>")
                parts.append(f"<div class='draft'><p class='meta'><b>Option A — Gemini</b> • Archetype: {esc(it.draft_archetype)} • Variant {it.draft_variant}</p><p id='{draft_id}'>{html_draft}</p><button data-copy='{draft_id}'>Copy Gemini draft</button></div>")
                if getattr(it, "grok_available", False) and getattr(it, "grok_comment", ""):
                    gid = f"grok-{p}-{n}"
                    gdraft = esc(it.grok_comment).replace("\n", "<br>")
                    parts.append(f"<div class='draft' style='border-left-color:#111'><p class='meta'><b>Option B — Grok reviewed</b> • {esc(it.grok_note)} • Verdict: {esc(it.grok_verdict)}</p><p id='{gid}'>{gdraft}</p><button data-copy='{gid}'>Copy Grok draft</button></div>")
                elif it.comment:
                    parts.append("<p class='meta'><i>Grok review unavailable for this item — Gemini draft only.</i></p>")
                if it.alternatives:
                    parts.append("<p class='meta'><b>More Gemini alternatives:</b></p>")
                    for alt in it.alternatives:
                        parts.append(f"<div class='draft'><p>{esc(alt)}</p></div>")
            else:
                parts.append("<p class='meta'><i>No draft generated (abstain / skip / wait).</i></p>")
            parts.append("</section>")
    parts.append("""<script>document.querySelectorAll("button[data-copy]").forEach(b=>b.addEventListener("click",()=>{var e=document.getElementById(b.getAttribute("data-copy"));navigator.clipboard.writeText(e.innerText);b.textContent="Copied";setTimeout(()=>b.textContent="Copy draft",1500)}));</script></div></body></html>""")
    path.write_text("".join(parts), encoding="utf-8")

def write_markdown(digest, path: Path):
    lines = [f"# Leadership AI Digest — {digest.date}", f"**Summary:** {digest.summary}", ""]
    for p, items in digest.items_by_platform.items():
        lines.append(f"## {PLATFORM_LABEL.get(p, p)}")
        for n, it in enumerate(items, 1):
            lines += [f"### {n}. [{it.title}]({it.url})", f"- **Decision:** {it.decision.value} ({it.promotion_score}/100, Opp {it.opportunity_score})", f"- **Why:** {it.decision_reason}", f"- **Theme:** {it.book_theme}"]
            if it.repurpose_candidate:
                lines.append(f"- **Repurpose:** {it.repurpose_reason}")
            if it.comment:
                lines += ["**Option A — Gemini:**", it.comment, ""]
                if getattr(it, "grok_available", False) and getattr(it, "grok_comment", ""):
                    lines += [f"**Option B — Grok reviewed ({it.grok_note} / {it.grok_verdict}):**", it.grok_comment, ""]
    path.write_text("\n".join(lines), encoding="utf-8")

def write_json(digest, path: Path):
    data = {"version": digest.version, "date": digest.date, "summary": digest.summary, "items": [{**asdict(it), "decision": it.decision.value, "sensitivity": it.sensitivity.value, "confidence": it.confidence.value} for p, grp in digest.items_by_platform.items() for it in grp]}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
