# gemini_client.py - v4.7 - Quota-guarded
# Root: gemini_client.py
# Fail-closed for Gemini. Never calls API if quota would be exceeded.
# Never uses google.generativeai. Only google.genai.
import re

try:
    from quota import can_afford, record_call, mark_quota_exhausted, get_usage, wait_for_rpm_slot
except Exception:
    # If quota.py missing, fail open to old behaviour but with safe stub
    def can_afford(model, needed=1):
        return True
    def record_call(model, n=1):
        return None
    def mark_quota_exhausted(model):
        return None
    def get_usage(model):
        return {"used": 0, "limit": 20, "remaining": 20, "label": model}
    def wait_for_rpm_slot(model, max_wait=15):
        return True

class GeminiQuotaExceeded(Exception):
    pass

class GeminiInitError(Exception):
    pass

def _normalize_model(model):
    m = (model or "gemini-3.8-flash").strip().lower()
    # Retired models -> auto-upgrade to 3.8 Flash
    if "2.0-flash" in m or "1.5" in m or m in ("gemini-pro", "gemini-1.0-pro", "gemini-pro-vision"):
        return "gemini-3.8-flash"
    # Keep Lite models as-is - they are valid fallbacks with 500/day
    if "3.1-flash-lite" in m:
        return "gemini-3.1-flash-lite"
    if "3.5-flash-lite" in m:
        return "gemini-3.5-flash-lite"
    if "3.6-flash" in m:
        return "gemini-3.6-flash"
    if "3.8-flash" in m:
        return "gemini-3.8-flash"
    if "3-flash-preview" in m:
        return "gemini-3-flash-preview"
    return m

class GeminiClient:
    def __init__(self, api_key=None, model="gemini-3.8-flash"):
        self.api_key = (api_key or "").strip()
        self.model = _normalize_model(model)
        self._client = None
        self._init_error = None
        if not self.api_key:
            self._init_error = "No GEMINI_API_KEY in Secrets."
            return
        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        except Exception as e:
            # google-generativeai shadows google-genai - this is the classic cause
            self._init_error = f"google-genai not installed: {e}"
            self._client = None

    @property
    def init_error(self):
        return self._init_error

    def is_ready(self):
        return self._client is not None and not self._init_error

    def generate(self, prompt, max_tokens=1200):
        """Single Gemini call, quota-guarded. Raises GeminiQuotaExceeded without calling API if out."""
        if not self.is_ready():
            raise GeminiInitError(self._init_error or "Gemini not initialised")
        # --- QUOTA GUARD: check BEFORE calling ---
        if not can_afford(self.model, 1):
            u = get_usage(self.model)
            raise GeminiQuotaExceeded(
                f"Gemini quota exceeded (Free Tier, {u['limit']} req/day for {u['label']}). "
                f"Used {u['used']}/{u['limit']} today. Resets {u.get('reset_label','midnight Pacific')}. "
                f"Use template / heuristic drafts, or switch GEMINI_MODEL to gemini-3.1-flash-lite (500/day)."
            )
        # RPM guard: wait a bit if we are at per-minute limit
        wait_for_rpm_slot(self.model, max_wait=10)
        try:
            resp = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            # Success - count it
            record_call(self.model, 1)
            text = ""
            try:
                text = (resp.text or "").strip()
            except Exception:
                # Fallback parsing for SDK variants
                try:
                    text = resp.candidates[0].content.parts[0].text.strip()
                except Exception:
                    text = ""
            return text
        except Exception as e:
            msg = str(e)
            # 429 = quota - mark exhausted so app stops hammering
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                mark_quota_exhausted(self.model)
                # Extract retry time if present, e.g. "Please retry in 2h6m22s" or retryDelay
                m = re.search(r"retry in ([0-9hms\.]+)", msg, re.I)
                retry = f" Please retry in {m.group(1)}." if m else ""
                raise GeminiQuotaExceeded(
                    f"Gemini quota exceeded (Free Tier, {self.model}).{retry} "
                    f"Do NOT keep clicking Generate - use template drafts below or wait."
                )
            raise

    def test(self):
        return self.generate("Reply with exactly: OK")
