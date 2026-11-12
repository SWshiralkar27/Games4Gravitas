# groq_client.py - v4.9.3.5 - Groq Cloud fallback generator (fail-open)
# Root: groq_client.py - replaces grok_client.py
# When Gemini quota is out / 503 / init failed, Groq takes over as generator.
# 2026-11-11: Stage 3 - Renamed from grok_client.py. Reason: file was already calling Groq API, only class names said Grok.
# 2026-11-12: FIX review_draft robust parse - was json.loads(raw) only, failed on ```json fences / leading text, returned original draft as fake review.
import json, re

try:
    import requests
except Exception:
    requests = None

class GroqQuotaExceeded(Exception):
    pass
class GroqTransientError(Exception):
    pass
class GroqInitError(Exception):
    pass

def _normalize_groq_model(m):
    m = (m or "openai/gpt-oss-20b").strip().lower()
    if "gpt-oss" in m or "llama" in m or "gemma" in m:
        return m
    return "openai/gpt-oss-20b"

def _parse_groq_json(raw):
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    try:
        s = text.find("{"); e = text.rfind("}")
        if s != -1 and e != -1 and e > s:
            d = json.loads(text[s:e+1])
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return None

class GroqClient:
    def __init__(self, api_key=None, model="openai/gpt-oss-20b", api_url="https://api.groq.com/openai/v1/chat/completions"):
        import os
        self.api_key = (api_key or os.getenv("GROQ_API_KEY", "") or os.getenv("GROK_API_KEY", "")).strip()
        self.model = _normalize_groq_model(model)
        self.api_url = api_url or "https://api.groq.com/openai/v1/chat/completions"
        self._init_error = None
        if not self.api_key:
            self._init_error = "No GROQ_API_KEY in Secrets."
        elif requests is None:
            self._init_error = "requests not installed."

    @property
    def init_error(self):
        return self._init_error
    def is_ready(self):
        return not self._init_error and bool(self.api_key) and requests is not None

    def generate(self, prompt, max_tokens=1200):
        if not self.is_ready():
            raise GroqInitError(self._init_error or "Groq not initialised")
        try:
            resp = requests.post(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                },
                timeout=60,
            )
        except Exception as e:
            raise GroqTransientError(f"Groq request failed (network/timeout): {e}")
        if resp.status_code == 429:
            raise GroqQuotaExceeded(f"Groq quota exceeded (429). Details: {resp.text[:300]}")
        if resp.status_code in (500, 502, 503, 504):
            raise GroqTransientError(f"Groq overloaded ({resp.status_code}). Details: {resp.text[:300]}")
        if resp.status_code != 200:
            raise GroqTransientError(f"Groq failed ({resp.status_code}): {resp.text[:300]}")
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            return text
        except Exception as e:
            raise GroqTransientError(f"Groq parse failed: {e} - raw: {resp.text[:300]}")

    def test(self):
        return self.generate("Reply with exactly: OK", max_tokens=20)

    def review_draft(self, item, draft, archetype):
        prompt = f"Review this draft comment for tone and grounding. Return JSON only: {{\"reviewed_draft\": \"...\", \"what_changed\": \"...\", \"verdict\": \"keep/edit\"}}. Draft: {draft}"
        try:
            raw = self.generate(prompt, max_tokens=800)
            parsed = _parse_groq_json(raw)
            if parsed and parsed.get("reviewed_draft"):
                return parsed
            return {"reviewed_draft": draft, "what_changed": "Groq review parse failed, kept original", "verdict": "keep"}
        except Exception:
            return {"reviewed_draft": draft, "what_changed": "Groq review failed, kept original", "verdict": "keep"}
