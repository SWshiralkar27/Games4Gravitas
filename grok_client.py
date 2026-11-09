"""Grok reviewer — second engine. Gemini drafts, Grok reviews + rewrites. You pick.
Uses xAI API (OpenAI-compatible). No new dependency — uses requests.
Env: GROK_API_KEY, GROK_MODEL (default grok-4), GROK_BASE_URL (default https://api.x.ai/v1)
Fail-open for Grok: if Grok fails, Gemini draft still shows, Grok slot shows 'Review unavailable'.
"""
from __future__ import annotations
import json, logging, time
import requests
from config import GROK_API_KEY, GROK_MODEL, GROK_BASE_URL, GROK_DELAY_SECONDS
log = logging.getLogger("digest")

class GrokUnavailable(RuntimeError):
    pass

class GrokClient:
    def __init__(self, api_key: str = "", model: str = "", base_url: str = ""):
        self.api_key = api_key or GROK_API_KEY
        self.model = model or GROK_MODEL
        self.base_url = (base_url or GROK_BASE_URL).rstrip("/")
        if not self.api_key:
            raise GrokUnavailable("GROK_API_KEY is not set.")

    def _chat(self, system: str, user: str, max_tokens: int = 1200) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.4,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        for attempt in range(2):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=30)
                r.raise_for_status()
                data = r.json()
                return (data["choices"][0]["message"]["content"] or "").strip()
            except Exception as exc:
                log.warning("Grok attempt %d failed: %s", attempt + 1, exc)
                time.sleep(2 ** attempt)
        raise GrokUnavailable("Grok failed after retries.")

    def review_draft(self, item, gemini_draft: str, archetype: str = "") -> dict | None:
        """Review one Gemini draft and return a rewritten alternative + note. Returns None on failure."""
        if not gemini_draft:
            return None
        system = "You are a sharp social-media editor. You do NOT write generic praise. You improve specificity, hook, and conversation potential."
        user = f"""
You are reviewing a comment draft written by another AI (Gemini) for the book "Games for Gravitas".
POST: {item.title} | {item.content_for_analysis[:4000]}
PLATFORM: {item.platform} | Decision: {item.decision.value} | Archetype: {archetype or item.draft_archetype}
GEMINI DRAFT TO REVIEW:
---
{gemini_draft}
---
TASK:
1. Keep the same archetype and CEA structure (Compliment-Expand-Ask), same word-count range, same book rule as Gemini had.
2. Improve: make the Compliment name a SPECIFIC idea from the post, make the Expand add one insight Gemini missed, make the Ask easier and more specific to answer.
3. If Gemini draft mentions the book, keep exactly one mention. If it is B_ENGAGE, keep zero book/author/link mentions. Do not add new links.
4. Do NOT start with "Great post" or generic openers.
Return ONLY valid JSON: {{"reviewed_draft":"...", "what_changed":"1 sentence, e.g. Sharpened hook + made question specific", "verdict":"keep_gemini" or "prefer_grok"}}
If the Gemini draft is already excellent, return it nearly unchanged with verdict keep_gemini.
"""
        try:
            time.sleep(max(0.0, GROK_DELAY_SECONDS))
            raw = self._chat(system, user, max_tokens=1200)
            parsed = json.loads(raw)
            reviewed = (parsed.get("reviewed_draft") or "").strip()
            if len(reviewed) < 30:
                return None
            return {"reviewed_draft": reviewed, "what_changed": parsed.get("what_changed", ""), "verdict": parsed.get("verdict", "prefer_grok")}
        except Exception as exc:
            log.warning("Grok review failed: %s", exc)
            return None
