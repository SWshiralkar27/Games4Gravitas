import os
from pathlib import Path

# --- API Keys: read from Streamlit Secrets / env vars. Never hard-code keys here ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_DELAY_SECONDS = float(os.getenv("GEMINI_DELAY_SECONDS", "3"))

GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4")
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")
GROK_ENABLED = os.getenv("GROK_ENABLED", "true").lower() == "true"
GROK_REVIEW_COUNT = int(os.getenv("GROK_REVIEW_COUNT", "1"))

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "serper").lower()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# Google CSE (optional, if you use it)
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")

# --- Search terms: your current list, comma-separated in one string ---
_DEFAULT_SEARCH = (
    "Leadership AI, Human-centered AI, hybrid intelligence, "
    "AI decision making, team judgment under pressure, AI and critical thinking, leaders struggling with AI, "
    "corporate upskilling AI, AI upskilling program organization, L&D AI training, future of work AI skills, "
    "AI transformation leadership, reskilling workforce AI, AI literacy for leaders, "
    "AI transformation upskilling program, HR leaders AI training, learning and development AI era"
)
SEARCH_TERMS = [t.strip() for t in os.getenv("SEARCH_TERMS", _DEFAULT_SEARCH).split(",") if t.strip()]

# --- Book themes: defined here so app.py never crashes on missing BOOK_THEMES ---
BOOK_THEMES = [
    "Human Judgment",
    "Purposeful Rehearsal",
    "Centaur Leadership",
    "Rehearse Before You Decide",
    "Human Advantage",
]
# Alias for any code that uses THEMES
THEMES = BOOK_THEMES

# --- Platform order and files ---
PLATFORM_ORDER = ["LinkedIn", "X", "Threads", "Facebook", "Instagram", "Medium", "YouTube"]
PLATFORM_LABEL = {
    "LinkedIn": "LinkedIn",
    "X": "X",
    "Threads": "Threads",
    "Facebook": "Facebook",
    "Instagram": "Instagram",
    "Medium": "Medium",
    "YouTube": "YouTube",
}

HISTORY_FILE = Path("seen_posts.txt")
HISTORY_DAYS = 90
EFFECTIVENESS_FILE = Path("effectiveness.txt")

# --- Thresholds (kept from v4) ---
PROMOTE_THRESHOLD = 80
ENGAGE_THRESHOLD = 60
DYNAMIC_PROMOTE_THRESHOLD = 75
SATURATION_HIGH = 80
RECENCY_BOOST_HOURS = 4
MAX_PROMOTE_PER_THEME = 2
MIN_THEMES_PER_RUN = 3

# --- Limits and chars: required by models.py and other modules ---
MAX_CONTEXT_CHARS = int(__import__("os").getenv("MAX_CONTEXT_CHARS", "6000"))
MAX_SNIPPET_CHARS = int(__import__("os").getenv("MAX_SNIPPET_CHARS", "2000"))
MAX_TITLE_CHARS = int(__import__("os").getenv("MAX_TITLE_CHARS", "300"))
MAX_COMMENT_CHARS = int(__import__("os").getenv("MAX_COMMENT_CHARS", "800"))
MAX_DRAFT_CHARS = int(__import__("os").getenv("MAX_DRAFT_CHARS", "800"))
MIN_SNIPPET_CHARS = int(__import__("os").getenv("MIN_SNIPPET_CHARS", "50"))
MAX_POSTS_PER_RUN = int(__import__("os").getenv("MAX_POSTS_PER_RUN", "30"))
DISCOVERY_LIMIT = int(__import__("os").getenv("DISCOVERY_LIMIT", "30"))
MAX_CANDIDATES = int(__import__("os").getenv("MAX_CANDIDATES", "30"))

# Aliases that older code sometimes uses
MAX_CONTENT_CHARS = MAX_CONTEXT_CHARS
MAX_TEXT_CHARS = MAX_CONTEXT_CHARS
CONTEXT_CHAR_LIMIT = MAX_CONTEXT_CHARS

# --- Scoring / guardrail constants that other modules may import ---
CEA_MAX_WORDS = int(__import__("os").getenv("CEA_MAX_WORDS", "120"))
COMMENT_MAX_WORDS = int(__import__("os").getenv("COMMENT_MAX_WORDS", "120"))
HOOK_MIN_WORDS = int(__import__("os").getenv("HOOK_MIN_WORDS", "3"))

