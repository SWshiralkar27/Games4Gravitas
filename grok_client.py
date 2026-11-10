
# grok_client.py - v4.9.2 - Grok fallback generator (fail-open)
# Root: grok_client.py - NEW file
# When Gemini quota is out / 503 / init failed, Grok takes over as generator.
# Grok has its own quota, separate from Gemini 20/day, so it still works when Gemini is out.
# Dual-engine advantage is lost (no Gemini + Grok review), but a single-engine Grok draft
# is far better than a template draft. If Grok also fails, fall back to template.
import json

try:
    import requests
except Exception:
    requests = None

class GrokQuotaExceeded(Exception):
    pass
class GrokTransientError(Exception):
    pass
class GrokInitError(Exception):
    pass

def _normalize_grok_model(m):
    m = (m or "grok-3-mini").strip().lower()
    # Keep as-is if it already looks like a grok model
    if "grok" in m:
        return m
    return "grok-3-mini"

class GrokClient:
    def __init__(self, api_key=None, model="grok-3-mini", api_url="https://api.x.ai/v1/chat/completions"):
        self.api_key = (api_key or "").strip()
        self.model = _normalize_grok_model(model)
        self.api_url = api_url or "https://api.x.ai/v1/chat/completions"
        self._init_error = None
        if not self.api_key:
            self._init_error = "No GROK_API_KEY in Secrets."
        elif requests is None:
            self._init_error = "requests not installed (add requests to requirements.txt)."

    @property
    def init_error(self):
        return self._init_error
    def is_ready(self):
        return not self._init_error and bool(self.api_key) and requests is not None

    def generate(self, prompt, max_tokens=1200):
        if not self.is_ready():
            raise GrokInitError(self._init_error or "Grok not initialised")
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
                timeout=20,
            )
        except Exception as e:
            raise GrokTransientError(f"Grok request failed (network/timeout): {e}")
        # Handle status codes
        if resp.status_code == 429:
            raise GrokQuotaExceeded(f"Grok quota exceeded (429). Details: {resp.text[:300]}")
        if resp.status_code in (500, 502, 503, 504):
            raise GrokTransientError(f"Grok overloaded ({resp.status_code}). Details: {resp.text[:300]}")
        if resp.status_code != 200:
            # Fail-open: treat as transient, caller will fall back to template
            raise GrokTransientError(f"Grok failed ({resp.status_code}): {resp.text[:300]}")
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            return text
        except Exception as e:
            raise GrokTransientError(f"Grok parse failed: {e} - raw: {resp.text[:300]}")

    def test(self):
        return self.generate("Reply with exactly: OK", max_tokens=20)

