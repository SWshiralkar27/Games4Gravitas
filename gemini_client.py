# gemini_client.py - v4.9.2 - 503 vs 429 separated
# Root: gemini_client.py
# FIX: 503 UNAVAILABLE (model overloaded) is NOT quota. Do NOT mark quota exhausted, do NOT abort whole Assess.
# 429 RESOURCE_EXHAUSTED is quota. Mark exhausted, show reset time.
import re, time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout

try:
    from quota import can_afford, record_call, mark_quota_exhausted, get_usage, wait_for_rpm_slot
except Exception:
    def can_afford(model, needed=1): return True
    def record_call(model, n=1): return None
    def mark_quota_exhausted(model): return None
    def get_usage(model): return {"used": 0, "limit": 20, "remaining": 20, "label": model}
    def wait_for_rpm_slot(model, max_wait=15): return True

class GeminiQuotaExceeded(Exception):
    pass

class GeminiTransientError(Exception):
    # 503 / 500 / overloaded - retry later, do NOT count as quota out
    pass

class GeminiInitError(Exception):
    pass

def _normalize_model(model):
    m = (model or "gemini-3.8-flash").strip().lower()
    if "2.0-flash" in m or "1.5" in m or m in ("gemini-pro", "gemini-1.0-pro", "gemini-pro-vision"):
        return "gemini-3.8-flash"
    if "3.1-flash-lite" in m: return "gemini-3.1-flash-lite"
    if "3.5-flash-lite" in m: return "gemini-3.5-flash-lite"
    if "3.6-flash" in m: return "gemini-3.6-flash"
    if "3.8-flash" in m: return "gemini-3.8-flash"
    if "3-flash-preview" in m: return "gemini-3-flash-preview"
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
            self._init_error = f"google-genai not installed: {e}"
            self._client = None

    @property
    def init_error(self): return self._init_error
    def is_ready(self): return self._client is not None and not self._init_error

    def generate(self, prompt, max_tokens=1200):
        if not self.is_ready():
            raise GeminiInitError(self._init_error or "Gemini not initialised")
        if not can_afford(self.model, 1):
            u = get_usage(self.model)
            raise GeminiQuotaExceeded(
                f"Gemini quota exceeded (Free Tier, {u['limit']} req/day for {u['label']}). "
                f"Used {u['used']}/{u['limit']} today. Resets {u.get('reset_label','midnight Pacific')}. "
                f"Use template / heuristic drafts, or switch GEMINI_MODEL to gemini-3.1-flash-lite (500/day)."
            )
        wait_for_rpm_slot(self.model, max_wait=10)
        try:
            # v4.9.2: 30s timeout - never hang 15 mins. If Gemini stalls, treat as transient, fall back.
            try:
                with ThreadPoolExecutor(max_workers=1) as _ex:
                    _fut = _ex.submit(self._client.models.generate_content, model=self.model, contents=prompt)
                    resp = _fut.result(timeout=30)
            except _FutTimeout:
                raise GeminiTransientError("Gemini timed out after 30s (server stalled). Treated as 503 - will use heuristic / Grok for this post.")
            record_call(self.model, 1)
            text = ""
            try:
                text = (resp.text or "").strip()
            except Exception:
                try:
                    text = resp.candidates[0].content.parts[0].text.strip()
                except Exception:
                    text = ""
            return text
        except Exception as e:
            msg = str(e)
            # --- 503 / 500 / UNAVAILABLE = overload, NOT quota ---
            if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower() or "high demand" in msg.lower() or "500" in msg:
                # Do NOT mark quota exhausted, do NOT record as quota call - it did not succeed
                raise GeminiTransientError(
                    f"Gemini overloaded (503 - model is busy, temporary). Please try that one post again in a few minutes. "
                    f"Details: {msg[:250]}"
                )
            # --- 429 = real quota ---
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                mark_quota_exhausted(self.model)
                m = re.search(r"retry in ([0-9hms\.]+)", msg, re.I)
                # Also try retryDelay: 4119s style
                if not m:
                    m2 = re.search(r"retryDelay[^0-9]*([0-9]+)s", msg, re.I)
                    if m2:
                        secs = int(m2.group(1))
                        retry = f"{secs//3600}h{(secs%3600)//60}m{secs%60}s"
                        m = None
                        raise GeminiQuotaExceeded(
                            f"Gemini quota exceeded (Free Tier, {self.model}). Please retry in {retry}. "
                            f"Resets at 1:30 PM IST. Do NOT keep clicking Generate - use template drafts below or wait."
                        )
                retry = f" Please retry in {m.group(1)}." if m else ""
                raise GeminiQuotaExceeded(
                    f"Gemini quota exceeded (Free Tier, {self.model}).{retry} "
                    f"Do NOT keep clicking Generate - use template drafts below or wait."
                )
            raise

    def test(self):
        return self.generate("Reply with exactly: OK")
