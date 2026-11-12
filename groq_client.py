
# groq_client.py - v4.9.3.8 - Groq Cloud fallback generator (fail-open)
# Root: groq_client.py - replaces grok_client.py
# When Gemini quota is out / 503 / init failed, Groq takes over as generator.
# 2026-11-11: Stage 3 - Renamed from grok_client.py. Reason: file was already calling Groq API, only class names said Grok.
# 2026-11-12: FIX review_draft robust parse - was json.loads(raw) only, failed on ```json fences / leading text, returned original draft as fake review.
# 2026-11-12: FIX v4.9.3.8 - gpt-oss-20b empty content (raw=""). Reason: reasoning model burned all 900 tokens on reasoning, 0 left for content -> API returned 200 with content="".
# Fix: reasoning_effort=low for gpt-oss + bump max_tokens for long draft prompts + raise on empty content instead of returning "" silently.
# PRESERVED from v4.9.3.5 (do not remove): __init__(api_url=...), test(), review_draft fail-open, GROK_API_KEY fallback, _normalize_groq_model, _parse_groq_json, GroqInitError, requests-is-None guard, timeout=60.
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
    # PRESERVED signature from v4.9.3.5 + optional timeout/base_url for forward-compat. app.py may pass api_url=..., so keep that name.
    def __init__(self, api_key=None, model="openai/gpt-oss-20b", api_url="https://api.groq.com/openai/v1/chat/completions", timeout=60, base_url=None):
        import os
        self.api_key = (api_key or os.getenv("GROQ_API_KEY", "") or os.getenv("GROK_API_KEY", "")).strip()
        self.model = _normalize_groq_model(model)
        # base_url is alias for api_url - if caller passes base_url, it wins, else api_url. Preserves both call styles.
        self.api_url = (base_url or api_url or "https://api.groq.com/openai/v1/chat/completions")
        self.base_url = self.api_url
        self.timeout = timeout or 60
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
        # 2026-11-12 v4.9.3.8: Only bump for LONG draft prompts. Test prompt "Reply with exactly: OK" is short (21 chars) - must stay at 20 tokens, fast.
        # Draft prompt from cea.py is >1000 chars + asks for JSON. For gpt-oss, 900/1200 is too low - reasoning eats it all, content="".
        # Bump 900/1200 -> 2600 only when prompt is long. Review prompt (~150 chars) also gets bump to 1600 below in review_draft, not here.
        _is_long_draft = isinstance(prompt, str) and len(prompt) > 500
        if _is_long_draft and max_tokens < 2000:
            max_tokens = 2600
        # Build payload - PRESERVED messages format (user-only) from v4.9.3.5, plus new fields for gpt-oss
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        # 2026-11-12 v4.9.3.8: Send max_completion_tokens too - Groq OpenAI-compat uses it for newer models. Harmless if ignored.
        payload["max_completion_tokens"] = max_tokens
        # 2026-11-12 v4.9.3.8: gpt-oss is reasoning model. Default reasoning_effort=medium burns tokens on reasoning.
        # low leaves tokens for content. Only for gpt-oss, not for llama/gemma.
        if "gpt-oss" in self.model.lower():
            payload["reasoning_effort"] = "low"
        try:
            resp = requests.post(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
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
            # 2026-11-12 v4.9.3.8: Never return "" silently. Old code: text = ...strip(); return text -> "" on empty content, generator saw raw="".
            # Now: if content empty, raise with finish_reason + usage so generator shows real reason.
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            text = (msg.get("content") or "").strip()
            if not text:
                finish = choice.get("finish_reason", "")
                reasoning = msg.get("reasoning") or ""
                usage = data.get("usage") or {}
                raise GroqTransientError(
                    f"Groq returned empty content (finish_reason={finish}, reasoning_chars={len(str(reasoning))}, usage={usage}, max_tokens={max_tokens}). "
                    f"Likely reasoning consumed all tokens."
                )
            return text
        except GroqTransientError:
            raise
        except Exception as e:
            raise GroqTransientError(f"Groq parse failed: {e} - raw: {resp.text[:300]}")

    def test(self):
        # PRESERVED from v4.9.3.5 - Test Groq Now calls this. Must stay at max_tokens=20, fast. generate() will NOT bump it because prompt is short.
        return self.generate("Reply with exactly: OK", max_tokens=20)

    def review_draft(self, item, draft, archetype):
        # PRESERVED fail-open from v4.9.3.5 - NEVER raises. Always returns dict with reviewed_draft=draft on any failure.
        # This is intentional: review failure must not kill the draft, only generation failure does.
        prompt = f"Review this draft comment for tone and grounding. Return JSON only: {{\"reviewed_draft\": \"...\", \"what_changed\": \"...\", \"verdict\": \"keep/edit\"}}. Draft: {draft}"
        try:
            # Review prompt is short, but still needs reasoning + JSON. 800 was too low for gpt-oss (same empty-content bug). Use 1600 for review.
            raw = self.generate(prompt, max_tokens=1600)
            parsed = _parse_groq_json(raw)
            if parsed and parsed.get("reviewed_draft"):
                return parsed
            return {"reviewed_draft": draft, "what_changed": "Groq review parse failed, kept original", "verdict": "keep"}
        except Exception as e:
            # PRESERVED: include real error in what_changed for debugging, but still return original draft (fail-open).
            return {"reviewed_draft": draft, "what_changed": f"Groq review failed, kept original: {str(e)[:200]}", "verdict": "keep"}

# Backwards-compat alias - old app.py imports GrokClient
GrokClient = GroqClient

