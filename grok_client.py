# grok_client.py - v4.9.3 - Groq Cloud fallback generator (fail-open)
# Root: grok_client.py
# When Gemini quota is out / 503 / init failed, Groq takes over as generator.
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
    m = (m or "llama-3.3-70b-versatile").strip().lower()
    if "llama" in m or "mixtral" in m or "gemma" in m:
        return m
    return "llama-3.3-70b-versatile"

class GrokClient:
    def __init__(self, api_key=None, model="llama-3.3-70b-versatile", api_url="https://api.groq.com/openai/v1/chat/completions"):
        # Check both GROQ_API_KEY and fallback to legacy GROK_API_KEY if needed
        import os
        self.api_key = (api_key or os.getenv("GROQ_API_KEY", "") or os.getenv("GROK_API_KEY", "")).strip()
        self.model = _normalize_grok_model(model)
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
            raise GrokInitError(self._init_error or "Groq not initialised")
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
            raise GrokTransientError(f"Groq request failed (network/timeout): {e}")
        
        # Handle status codes
        if resp.status_code == 429:
            raise GrokQuotaExceeded(f"Groq quota exceeded (429). Details: {resp.text[:300]}")
        if resp.status_code in (500, 502, 503, 504):
            raise GrokTransientError(f"Groq overloaded ({resp.status_code}). Details: {resp.text[:300]}")
        if resp.status_code != 200:
            raise GrokTransientError(f"Groq failed ({resp.status_code}): {resp.text[:300]}")
        
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            return text
        except Exception as e:
            raise GrokTransientError(f"Groq parse failed: {e} - raw: {resp.text[:300]}")

    def test(self):
        return self.generate("Reply with exactly: OK", max_tokens=20)
