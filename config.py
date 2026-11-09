import os
from pathlib import Path

# --- API Keys: read from Streamlit Secrets / env vars. Never hard-code keys here ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
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

# --- Book info: required by gemini_client.py ---
BOOK_FULL_TITLE = "Games for Gravitas: A Playbook to Build Human Advantage in the Hybrid Intelligence Era"
BOOK_TITLE = "Games for Gravitas"
BOOK_SHORT_TITLE = "Games for Gravitas"
BOOK_AUTHOR = "Shreekant Shiralkar"
BOOK_LINK = "https://www.amazon.com/dp/B0DUMMY"
BOOK_URL = BOOK_LINK

# --- Scoring weights: required by gemini_client.py ---
# v4 re-weighting: Book 25%, Context 30%, Engagement 25%, Audience 10%, Naturalness 10% = 1.0
SCORE_WEIGHTS = {
    "book_alignment": 0.25,
    "contextual_relevance": 0.30,
    "engagement": 0.25,
    "audience_alignment": 0.10,
    "promotion_naturalness": 0.10,
}
# Aliases that other scoring code might use
PROMOTION_WEIGHTS = SCORE_WEIGHTS
WEIGHTS = SCORE_WEIGHTS

# --- Context minimums ---
MIN_CONTEXT_CHARS = int(__import__("os").getenv("MIN_CONTEXT_CHARS", "100"))
MIN_SNIPPET_CHARS = int(__import__("os").getenv("MIN_SNIPPET_CHARS", "50"))

# --- Grok delays / timeouts: required by grok_client.py ---
GROK_DELAY_SECONDS = float(__import__("os").getenv("GROK_DELAY_SECONDS", "2"))
GROK_TIMEOUT_SECONDS = float(__import__("os").getenv("GROK_TIMEOUT_SECONDS", "30"))
GEMINI_TIMEOUT_SECONDS = float(__import__("os").getenv("GEMINI_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(__import__("os").getenv("MAX_RETRIES", "3"))

# --- Guardrails aliases: guardrails.py uses different names for the same thresholds ---
# Original names in config.py: PROMOTE_THRESHOLD=80, ENGAGE_THRESHOLD=60, DYNAMIC_PROMOTE_THRESHOLD=75, SATURATION_HIGH=80
# guardrails.py expects: PROMOTION_THRESHOLD, PROMOTION_THRESHOLD_OPEN, ENGAGEMENT_THRESHOLD, MAX_COMMENT_COUNT_SATURATION
PROMOTION_THRESHOLD = PROMOTE_THRESHOLD
PROMOTION_THRESHOLD_OPEN = DYNAMIC_PROMOTE_THRESHOLD
ENGAGEMENT_THRESHOLD = ENGAGE_THRESHOLD
ENGAGE_THRESHOLD_OPEN = DYNAMIC_PROMOTE_THRESHOLD
MAX_COMMENT_COUNT_SATURATION = SATURATION_HIGH
SATURATION_THRESHOLD = SATURATION_HIGH
MAX_COMMENTS_SATURATION = SATURATION_HIGH
COMMENT_COUNT_SATURATION = SATURATION_HIGH
SATURATION_LIMIT = SATURATION_HIGH

# Other guardrails / scoring names that may be imported next
SENSITIVE_THRESHOLD = 0.7
CONFIDENCE_THRESHOLD = 0.5
MIN_OPPORTUNITY_SCORE = 0
MAX_THEME_COUNT = 5

