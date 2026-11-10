
"""gemini_client.py — Leadership AI Digest v4.6
FIX for: google-genai not installed: cannot import name 'genai' from 'google'

Root cause is requirements.txt, not code:
- Streamlit Cloud installs ONLY what is in requirements.txt on every reboot.
- If requirements.txt is missing google-genai, or has google-generativeai
  instead, `from google import genai` fails with (unknown location).
- google-generativeai creates a `google` namespace that shadows google-genai.

Fix in this file: clearer error that tells you exactly what to fix in
requirements.txt, plus a second import attempt via importlib.
Fix in requirements.txt (v4.6, upload to root):
  google-genai>=1.0.0  present, google-generativeai REMOVED.

Model: never 2.0-flash, always gemini-3.8-flash.
"""
import json
import os
import re

_genai_import_error = None
genai = None
try:
    from google import genai
except Exception as e:
    _genai_import_error = e
    # Second attempt: importlib sometimes resolves when `from google import` hits a broken namespace
    try:
        import importlib
        genai = importlib.import_module("google.genai")
        _genai_import_error = None
    except Exception as e2:
        genai = None
        _genai_import_error = e2

from config import GEMINI_API_KEY, GEMINI_MODEL


class GeminiUnavailable(Exception):
    pass


class QuotaExceeded(Exception):
    def __init__(self, message, retry_after_seconds=None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _parse_retry_after(text):
    if not text:
        return None
    m = re.search(r"retry in\s+((?:\d+h)?(?:\d+m)?(?:\d+(?:\.\d+)?s)?)", text, re.I)
    if not m:
        m2 = re.search(r"retry_delay\s*[:=]\s*(\d+)", text)
        return int(m2.group(1)) if m2 else None
    part = m.group(1)
    total = 0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)([hms])", part):
        total += float(num) * (3600 if unit == "h" else 60 if unit == "m" else 1)
    return int(total) if total else None


def _is_quota_error(text):
    t = (text or "").lower()
    return "429" in t or "quota" in t or "exceeded your current quota" in t or "generate_content_free_tier" in t


def _normalise_model(model):
    m = (model or GEMINI_MODEL or "gemini-3.8-flash").strip()
    if "2.0-flash" in m or "1.5" in m or "gemini-pro" in m:
        return "gemini-3.8-flash"
    return m


class GeminiClient:
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        self.model = _normalise_model(model or GEMINI_MODEL)
        if not self.api_key:
            raise GeminiUnavailable("GEMINI_API_KEY missing in Secrets.")
        if genai is None:
            raise GeminiUnavailable(
                f"google-genai not installed: {_genai_import_error}. "
                "Fix requirements.txt in repo root: add line `google-genai>=1.0.0`, "
                "delete any line `google-generativeai`, commit, then Streamlit Manage app > Reboot. "
                "Streamlit installs only from requirements.txt."
            )
        self.client = genai.Client(api_key=self.api_key)

    def _call(self, prompt):
        try:
            resp = self.client.models.generate_content(model=self.model, contents=prompt)
            text = (getattr(resp, "text", "") or "").strip()
            if not text:
                raise GeminiUnavailable(f"Gemini returned empty / failed. Model: {self.model}. No text in response.")
            return text
        except QuotaExceeded:
            raise
        except GeminiUnavailable:
            raise
        except Exception as e:
            msg = str(e)
            if _is_quota_error(msg):
                raise QuotaExceeded(
                    f"Gemini quota exceeded (Free Tier, 20 req/day for {self.model}). Details: {msg}",
                    retry_after_seconds=_parse_retry_after(msg),
                )
            if "404" in msg and "2.0-flash" in msg:
                raise GeminiUnavailable(
                    "Config still points to retired gemini-2.0-flash. "
                    "Set GEMINI_MODEL=gemini-3.8-flash in Streamlit Secrets and reboot. "
                    f"Details: {msg}"
                )
            raise GeminiUnavailable(f"Gemini call failed (model={self.model}). Details: {msg}")

    def test_connection(self):
        return self._call("Reply with exactly: OK")

    def analyse_post(self, post):
        title = post.get("title", "")[:500]
        snippet = post.get("snippet", "")[:1500]
        platform = post.get("platform", "Web")
        prompt = (
            "You assess a social post for a Leadership + AI digest. "
            "Return ONLY valid JSON: "
            '{"relevance":0-100,"conversation":0-100,"recency":0-100,'
            '"theme":"one of the book themes or other","sensitive":true/false,'
            '"is_breaking":true/false,"reason":"short reason"}.\n\n'
            f"Platform: {platform}\nTitle: {title}\nSnippet: {snippet}"
        )
        raw = self._call(prompt)
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                raise GeminiUnavailable(f"Gemini returned non-JSON analysis: {raw[:300]}")
            data = json.loads(m.group(0))
        return data

    def generate_draft(self, post, analysis=None, archetype="Insight Add"):
        title = post.get("title", "")[:500]
        snippet = post.get("snippet", "")[:1200]
        prompt = (
            "Write ONE comment in CEA structure: Compliment (1 sentence) - "
            "Expand (1-2 sentences adding an idea) - Ask (1 open question). "
            f"Archetype: {archetype}. Do NOT start with 'Great post' or 'Thanks for sharing'. "
            "Do NOT mention the book title or a link. You may use one idea phrase "
            "like 'purposeful rehearsal' or 'centaur leadership' if natural. "
            "Max 70 words. Plain text, one paragraph per CEA part.\n\n"
            f"Post: {title}\n{snippet}"
        )
        draft = self._call(prompt)
        try:
            from drafting.formatting import format_draft
            draft = format_draft(draft)
        except Exception:
            pass
        return draft


def get_gemini_client(api_key=None, model=None):
    return GeminiClient(api_key=api_key, model=model)

