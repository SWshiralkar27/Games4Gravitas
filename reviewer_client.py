# reviewer_client.py - v1.0 - Independent reviewer + alternative draft (Option C)
# Root: reviewer_client.py  (NEW FILE - nothing else imports it except app.py)
# 2026-11-21: Added. Reason: Groq drafts were often not paste-ready, user had to paste them into
# Meta / Copilot / ChatGPT for a fitment check. This does that check inside the app.
# Rules: runs ONLY when the user clicks "Generate draft anyway". FAIL-OPEN - review() never raises.
# Never changes decision, score or theme. Human still copies and publishes manually.
# Providers (set REVIEWER_PROVIDER in Streamlit Secrets):
#   gemini    (default) - uses existing GEMINI_API_KEY, but a DIFFERENT model with its own free quota (gemini-3.1-flash-lite)
#   anthropic - needs REVIEWER_API_KEY, model defaults to claude-haiku-5-5
#   openai    - needs REVIEWER_API_KEY and REVIEWER_MODEL (no default, set it yourself)
import json, os, re

try:
    import requests
except Exception:
    requests = None

BOOK_TITLE_DEFAULT = "Games for Gravitas"

# Word limits per platform (Handover / Flow). Unknown platform -> default.
WORD_LIMITS = {
    "linkedin": (40, 80),
    "x": (20, 60),
    "medium": (60, 120),
    "youtube": (30, 90),
    "youtube shorts": (25, 70),
    "facebook": (40, 90),
    "instagram": (40, 90),
}
DEFAULT_LIMITS = (30, 90)
BANNED_OPENERS = ("great post", "thanks for sharing", "thank you for sharing", "great article", "love this")
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")


def _parse_json(raw):
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    for chunk in (text, text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""):
        if not chunk:
            continue
        try:
            d = json.loads(chunk)
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return None


def check_draft(text, platform, decision, book_title=BOOK_TITLE_DEFAULT):
    """Same rules as the other options. Returns a list of problems (empty = OK)."""
    problems = []
    t = (text or "").strip()
    if not t:
        return ["empty draft"]
    low = t.lower()
    if low.startswith(BANNED_OPENERS):
        problems.append("starts with a banned opener")
    if _EMOJI_RE.search(t):
        problems.append("contains an emoji")
    lo, hi = WORD_LIMITS.get((platform or "").strip().lower(), DEFAULT_LIMITS)
    n = len(t.split())
    if n < lo or n > hi:
        problems.append(f"{n} words, platform range is {lo}-{hi}")
    mentions = low.count(book_title.lower())
    if decision == "A_PROMOTE" and mentions != 1:
        problems.append(f"book title appears {mentions} times, must be exactly once")
    if decision != "A_PROMOTE":
        if mentions != 0 or "shiralkar" in low or "amazon." in low or "http" in low:
            problems.append("Engage draft must not mention the book, author or any link")
    return problems


class ReviewerClient:
    def __init__(self, provider=None, model=None, api_key=None, gemini_model=None):
        self.provider = (provider or os.getenv("REVIEWER_PROVIDER", "") or "gemini").strip().lower()
        self.model = (model or os.getenv("REVIEWER_MODEL", "") or "").strip()
        self.api_key = (api_key or os.getenv("REVIEWER_API_KEY", "") or "").strip()
        self._gem = None
        self._init_error = None
        if self.provider == "gemini":
            self.model = self.model or gemini_model or "gemini-3.1-flash-lite"
            try:
                from gemini_client import GeminiClient
                c = GeminiClient(api_key=os.getenv("GEMINI_API_KEY", ""), model=self.model)
                if c.is_ready():
                    self._gem = c
                    self.model = c.model
                else:
                    self._init_error = f"Gemini reviewer not ready: {c.init_error}"
            except Exception as e:
                self._init_error = f"Gemini reviewer import failed: {e}"
        elif self.provider == "anthropic":
            self.model = self.model or "claude-haiku-5-5"
            if not self.api_key:
                self._init_error = "No REVIEWER_API_KEY in Secrets (provider=anthropic)."
        elif self.provider == "openai":
            if not self.api_key:
                self._init_error = "No REVIEWER_API_KEY in Secrets (provider=openai)."
            elif not self.model:
                self._init_error = "No REVIEWER_MODEL in Secrets (provider=openai needs a model name)."
        else:
            self._init_error = f"Unknown REVIEWER_PROVIDER '{self.provider}'. Use gemini, anthropic or openai."
        if not self._init_error and self.provider != "gemini" and requests is None:
            self._init_error = "requests not installed."

    @property
    def init_error(self):
        return self._init_error

    def is_ready(self):
        return not self._init_error

    # ---- raw call, raises on failure (review() catches) ----
    def _call(self, prompt):
        if self.provider == "gemini":
            return self._gem.generate(prompt)
        if self.provider == "anthropic":
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": self.model, "max_tokens": 900, "messages": [{"role": "user", "content": prompt}]},
                timeout=60,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Anthropic {r.status_code}: {r.text[:300]}")
            parts = r.json().get("content") or []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
            if not text:
                raise RuntimeError(f"Anthropic returned empty content: {r.text[:300]}")
            return text
        if self.provider == "openai":
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "messages": [{"role": "user", "content": prompt}]},
                timeout=60,
            )
            if r.status_code != 200:
                raise RuntimeError(f"OpenAI {r.status_code}: {r.text[:300]}")
            text = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            if not text:
                raise RuntimeError(f"OpenAI returned empty content: {r.text[:300]}")
            return text
        raise RuntimeError("No provider")

    def test(self):
        if not self.is_ready():
            raise RuntimeError(self._init_error)
        return self._call("Reply with exactly: OK")

    def _prompt(self, post, draft, decision, platform, book_title, lo, hi, problems=None):
        text = " ".join(
            str(x) for x in (post.get("title") or "", post.get("snippet") or "", (post.get("_deep_text") or "")[:2000]) if x
        )[:3500]
        if decision == "A_PROMOTE":
            book_rule = f'Mention the book "{book_title}" exactly once, naturally, as a plain title. Never mention the author or a link.'
        else:
            book_rule = "Do NOT mention the book, its title, the author, or any link. You may seed ideas like purposeful rehearsal or human-AI teaming, in plain words."
        fix = f"\nYour previous alternative broke these rules, fix them: {'; '.join(problems)}.\n" if problems else ""
        return (
            "You are a careful editor helping a leadership author comment on someone else's social post.\n"
            f"PLATFORM: {platform}\nORIGINAL POST:\n{text}\n\nDRAFT COMMENT TO REVIEW:\n{draft}\n\n"
            "TASK 1: Judge fitment. Does the draft respond to a specific idea in the ORIGINAL POST, sound like a warm peer, "
            "and read as ready to paste? Verdict must be one of: Fits, Needs edit, Off-target. Give a one-line reason.\n"
            "TASK 2: Write your own ALTERNATIVE comment for the same post, ready to paste as is.\n"
            f"Alternative rules: {lo}-{hi} words. No emojis. Do not start with 'Great post' or 'Thanks for sharing'. "
            "Structure: genuine compliment tied to a specific point, expand with one new insight, end with a short open question. "
            f"{book_rule}\n{fix}"
            'Return ONLY JSON: {"verdict":"Fits|Needs edit|Off-target","reason":"one line","alternative":"the comment"}'
        )

    def review(self, post, draft, decision, platform, book_title=BOOK_TITLE_DEFAULT):
        """Never raises. Returns {verdict, reason, alternative, problems, error, provider, model}."""
        out = {"verdict": "", "reason": "", "alternative": "", "problems": [], "error": "",
               "provider": self.provider, "model": self.model}
        if not self.is_ready():
            out["error"] = self._init_error
            return out
        if not (draft or "").strip():
            out["error"] = "No Gemini or Groq draft to review."
            return out
        lo, hi = WORD_LIMITS.get((platform or "").strip().lower(), DEFAULT_LIMITS)
        problems = None
        try:
            for attempt in range(2):
                raw = self._call(self._prompt(post, draft, decision, platform, book_title, lo, hi, problems))
                d = _parse_json(raw)
                if not d or not str(d.get("alternative", "")).strip():
                    out["error"] = f"Reviewer returned no usable JSON: {str(raw)[:200]}"
                    return out
                out["verdict"] = str(d.get("verdict", "")).strip()
                out["reason"] = str(d.get("reason", "")).strip()
                alt = str(d.get("alternative", "")).strip()
                problems = check_draft(alt, platform, decision, book_title)
                if not problems:
                    out["alternative"] = alt
                    out["problems"] = []
                    out["error"] = ""
                    return out
                out["problems"] = problems
            out["error"] = "Alternative discarded after 2 tries, broke draft rules: " + "; ".join(out["problems"])
            return out
        except Exception as e:
            out["error"] = f"Reviewer failed: {str(e)[:300]}"
            return out
