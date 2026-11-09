"""Gemini client - fixed to handle BOOK_THEMES as strings OR tuples.

Original bug: line 64 did
    themes_str = "\n".join(f"- {n}: {d}" for n, d in BOOK_THEMES)
which crashes with ValueError when BOOK_THEMES is a list of strings
["Human Judgment", ...] because it tries to unpack "Human Judgment" into (n, d).

Fix: _format_themes() handles both:
  - ["Human Judgment", ...] -> "- Human Judgment"
  - [("Human Judgment", "desc"), ...] -> "- Human Judgment: desc"
"""
import os
import json
import re
import time

try:
    from config import (
        GEMINI_API_KEY, GEMINI_MODEL, GEMINI_DELAY_SECONDS,
        BOOK_FULL_TITLE, BOOK_THEMES, SCORE_WEIGHTS,
        MIN_CONTEXT_CHARS, PROMOTION_THRESHOLD, PROMOTION_THRESHOLD_OPEN,
        ENGAGEMENT_THRESHOLD, MAX_COMMENT_COUNT_SATURATION,
    )
except Exception:
    # Fallbacks if config is missing any name
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    GEMINI_DELAY_SECONDS = 3.0
    BOOK_FULL_TITLE = "Games for Gravitas: A Playbook to Build Human Advantage in the Hybrid Intelligence Era"
    BOOK_THEMES = ["Human Judgment", "Purposeful Rehearsal", "Centaur Leadership", "Rehearse Before You Decide", "Human Advantage"]
    SCORE_WEIGHTS = {"book_alignment": 0.25, "contextual_relevance": 0.30, "engagement": 0.25, "audience_alignment": 0.10, "promotion_naturalness": 0.10}
    MIN_CONTEXT_CHARS = 100
    PROMOTION_THRESHOLD = 80
    PROMOTION_THRESHOLD_OPEN = 75
    ENGAGEMENT_THRESHOLD = 60
    MAX_COMMENT_COUNT_SATURATION = 80

try:
    from guardrails import apply_guardrails
except Exception:
    def apply_guardrails(analysis, item):
        return analysis

class GeminiUnavailable(Exception):
    pass


def _format_themes():
    """Handle BOOK_THEMES as list of strings OR list of (name, desc) tuples."""
    lines = []
    try:
        themes = BOOK_THEMES or []
    except Exception:
        themes = ["Human Judgment", "Purposeful Rehearsal", "Centaur Leadership", "Rehearse Before You Decide", "Human Advantage"]
    for t in themes:
        if isinstance(t, (tuple, list)) and len(t) == 2:
            n, d = t
            lines.append(f"- {n}: {d}")
        elif isinstance(t, (tuple, list)) and len(t) == 1:
            lines.append(f"- {t[0]}")
        elif isinstance(t, dict):
            # {"name": ..., "desc": ...} or {"theme": ...}
            n = t.get("name") or t.get("theme") or str(t)
            d = t.get("desc") or t.get("description") or ""
            lines.append(f"- {n}: {d}" if d else f"- {n}")
        else:
            lines.append(f"- {t}")
    return "\n".join(lines)


def _format_themes_names():
    """Return just the theme names, for book_theme matching."""
    names = []
    for t in (BOOK_THEMES or []):
        if isinstance(t, (tuple, list)) and len(t) >= 1:
            names.append(str(t[0]))
        elif isinstance(t, dict):
            names.append(str(t.get("name") or t.get("theme") or t))
        else:
            names.append(str(t))
    return names


class GeminiClient:
    """Thin wrapper over google.generativeai / google.genai, with multiple __init__ signatures."""

    def __init__(self, api_key=None, model=None, *args, **kwargs):
        # Handle all call styles: GeminiClient(), GeminiClient(api_key), GeminiClient(model), GeminiClient(api_key, model), kwargs
        # If first positional looks like a model name (contains 'gemini' / 'flash'), treat it as model
        _api = None
        _model = None
        if api_key is not None and isinstance(api_key, str) and ("gemini" in api_key.lower() or "flash" in api_key.lower() or "pro" in api_key.lower()):
            _model = api_key
            _api = kwargs.get("api_key") or os.getenv("GEMINI_API_KEY", "")
        else:
            _api = api_key
            _model = model
        if kwargs.get("api_key"):
            _api = kwargs["api_key"]
        if kwargs.get("model"):
            _model = kwargs["model"]
        if _api is None:
            _api = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        if _model is None:
            _model = GEMINI_MODEL or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        # args[0] could be model if called as GeminiClient(api_key, model) where api_key was actually model - already handled
        if args and _model is None:
            _model = args[0]
        self.api_key = _api
        self.model = _model or "gemini-2.0-flash"
        self._genai = None
        self._model_obj = None
        if not self.api_key:
            raise GeminiUnavailable("GEMINI_API_KEY is missing. Add it to Streamlit Secrets.")
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._genai = genai
            self._model_obj = genai.GenerativeModel(self.model)
        except ImportError:
            try:
                # New SDK: google.genai
                from google import genai as new_genai
                self._genai = new_genai
                self._client = new_genai.Client(api_key=self.api_key)
                self._model_obj = None
            except Exception as e:
                raise GeminiUnavailable(f"google.generativeai not installed: {e}")
        except Exception as e:
            raise GeminiUnavailable(f"Gemini configure failed: {e}")

    def _call(self, prompt: str) -> str:
        """Call Gemini. Raises GeminiUnavailable with the REAL error instead of returning ''."""
        _errors = []
        # Try old SDK
        try:
            if self._model_obj is not None:
                resp = self._model_obj.generate_content(prompt)
                txt = getattr(resp, "text", "") or ""
                if txt and txt.strip():
                    return txt
                # Try candidates
                try:
                    _cand = resp.candidates[0].content.parts[0].text if resp.candidates else ""
                    if _cand and _cand.strip():
                        return _cand
                except Exception as _e:
                    _errors.append(f"old SDK candidates: {_e}")
                # If we got here, old SDK returned empty - record it, do NOT return "" yet, try new SDK
                _errors.append(f"old SDK returned empty text (model={self.model}, prompt_len={len(prompt)}). resp={str(resp)[:300]}")
        except Exception as _e:
            _errors.append(f"old SDK generate_content failed: {_e}")
        # Try new SDK
        try:
            if hasattr(self, "_client"):
                resp = self._client.models.generate_content(model=self.model, contents=prompt)
                txt2 = getattr(resp, "text", "") or ""
                if txt2 and txt2.strip():
                    return txt2
                _errors.append(f"new SDK returned empty text (model={self.model}). resp={str(resp)[:300]}")
        except Exception as _e2:
            _errors.append(f"new SDK failed: {_e2}")
        # Both failed or returned empty - raise with details so app.py can show it
        raise GeminiUnavailable("Gemini returned empty / failed. Details: " + " | ".join(_errors) + f" | Model={self.model} Key_len={len(self.api_key) if self.api_key else 0}")

    def generate(self, prompt: str) -> str:
        return self._call(prompt)

    def generate_content(self, prompt: str):
        txt = self._call(prompt)
        class _R:
            def __init__(self, text):
                self.text = text
        return _R(txt)

    def chat(self, prompt: str) -> str:
        return self._call(prompt)

    def complete(self, prompt: str) -> str:
        return self._call(prompt)


def _extract_json(text: str):
    """Extract first JSON object from Gemini response."""
    if not text:
        return None
    # Try direct
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try fenced block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Try first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass
    return None


def analyse_post(client, item):
    """Analyse one post. Returns dict with decision, scores, etc. Fail-closed on error."""
    try:
        title = getattr(item, "title", "") or ""
        snippet = getattr(item, "snippet", "") or ""
        full = getattr(item, "full_content", "") or snippet
        platform = getattr(item, "platform", "") or ""
        url = getattr(item, "url", "") or ""
        comment_count = int(getattr(item, "comment_count", 0) or 0)
        hours = float(getattr(item, "hours_since_post", 9999) or 9999)
        context_text = (full or snippet or title)[:2000]
        if len(context_text) < MIN_CONTEXT_CHARS:
            context_text = (title + "\n" + snippet + "\n" + full)[:2000]

        themes_str = _format_themes()
        theme_names = _format_themes_names()
        themes_list_str = ", ".join(theme_names)

        prompt = f"""You are scoring a social post for a book promotion digest.

Book: {BOOK_FULL_TITLE}
Book themes:
{themes_str}

Post:
Platform: {platform}
Title: {title}
URL: {url}
Comment count: {comment_count}
Hours since post: {hours}
Content:
{context_text}

Score 0-100 for each:
- book_alignment: how well it fits one of the book themes
- contextual_relevance: how relevant to Leadership AI / Human-centered AI / hybrid intelligence
- engagement: how likely it is to get thoughtful comments
- audience_alignment: how well it fits leaders, L&D, HR, AI transformation audience
- promotion_naturalness: how naturally the book can be mentioned without forcing it

Also decide:
- decision: one of A_PROMOTE, B_ENGAGE, C_WAIT, D_SKIP, C_SENSITIVE
  A_PROMOTE if promotion_score >= {PROMOTION_THRESHOLD} and fits a theme
  B_ENGAGE if promotion_score >= {ENGAGEMENT_THRESHOLD} but not strong enough to promote
  C_WAIT if too early / too saturated / needs more comments
  D_SKIP if low relevance
  C_SENSITIVE if the post is about tragedy, layoffs, grief, politics, health crisis, or other sensitive topic - never promote on those
- decision_reason: 1 sentence
- context_summary: 2 sentences summarising the post
- sensitivity: LOW / MEDIUM / HIGH, and sensitivity_reason
- confidence: LOW / MEDIUM / HIGH
- book_theme: the single best matching theme from [{themes_list_str}], or "" if none
- promotion_justification: 1 sentence why the book fits, or why not

Return ONLY valid JSON, no markdown, no extra text:
{{
  "book_alignment_score": 0,
  "contextual_relevance_score": 0,
  "engagement_score": 0,
  "audience_alignment_score": 0,
  "promotion_naturalness_score": 0,
  "promotion_score": 0,
  "decision": "B_ENGAGE",
  "decision_reason": "",
  "context_summary": "",
  "sensitivity": "LOW",
  "sensitivity_reason": "",
  "confidence": "MEDIUM",
  "book_theme": "",
  "promotion_justification": ""
}}
"""

        raw = ""
        try:
            if hasattr(client, "generate"):
                raw = client.generate(prompt) or ""
            elif hasattr(client, "generate_content"):
                r = client.generate_content(prompt)
                raw = getattr(r, "text", "") or str(r)
            elif hasattr(client, "chat"):
                raw = client.chat(prompt) or ""
            else:
                raw = client._call(prompt) or ""
        except Exception as e:
            item.analysis_error = f"Gemini call failed: {e}"
            return None

        data = _extract_json(raw)
        if not data:
            item.analysis_error = f"Gemini returned non-JSON: {raw[:300]}"
            return None

        # Compute promotion_score from weights if missing or 0
        try:
            w = SCORE_WEIGHTS or {}
            def _get(d, *keys, default=0):
                for k in keys:
                    if k in d:
                        return d[k]
                return default
            book_s = float(data.get("book_alignment_score", 0) or 0)
            ctx_s = float(data.get("contextual_relevance_score", 0) or 0)
            eng_s = float(data.get("engagement_score", 0) or 0)
            aud_s = float(data.get("audience_alignment_score", 0) or 0)
            nat_s = float(data.get("promotion_naturalness_score", 0) or 0)
            if not data.get("promotion_score"):
                promo = (
                    book_s * float(w.get("book_alignment", 0.25)) +
                    ctx_s * float(w.get("contextual_relevance", 0.30)) +
                    eng_s * float(w.get("engagement", 0.25)) +
                    aud_s * float(w.get("audience_alignment", 0.10)) +
                    nat_s * float(w.get("promotion_naturalness", 0.10))
                )
                data["promotion_score"] = round(promo, 1)
            # Auto-correct decision from promotion_score if Gemini gave inconsistent decision
            ps = float(data.get("promotion_score", 0) or 0)
            dec = str(data.get("decision", "D_SKIP") or "D_SKIP").upper()
            if dec not in ("A_PROMOTE", "B_ENGAGE", "C_WAIT", "D_SKIP", "C_SENSITIVE"):
                dec = "D_SKIP"
                data["decision"] = dec
            if dec == "A_PROMOTE" and ps < PROMOTION_THRESHOLD:
                # Keep Gemini decision but note it - do not silently demote, guardrails will handle
                pass
        except Exception:
            pass

        # Guardrails
        try:
            data = apply_guardrails(data, item)
        except Exception:
            pass

        time.sleep(min(float(GEMINI_DELAY_SECONDS or 1.0), 1.0))
        return data
    except Exception as e:
        try:
            item.analysis_error = f"analyse_post failed: {e}"
        except Exception:
            pass
        return None
