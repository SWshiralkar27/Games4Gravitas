"""config.py — Leadership AI Digest v4.2
FIXES in this version:
- GEMINI_MODEL forced to gemini-3.8-flash. Any 2.0-flash / 1.5 value from
  Secrets or env is auto-upgraded. Never 2.0-flash.
- Quota + pruning constants added (were missing, caused silent failures).
- No secrets in code. All keys from env / Streamlit Secrets only.
"""
import os

# --- API keys (from env / Streamlit Secrets only) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "serper").lower()  # serper | brave

# --- Models: 2.0-flash is retired (404). Force 3.8-flash. ---
_raw_gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
if "2.0-flash" in _raw_gemini_model or "1.5" in _raw_gemini_model or "gemini-pro" in _raw_gemini_model:
    GEMINI_MODEL = "gemini-3.8-flash"
else:
    GEMINI_MODEL = _raw_gemini_model

GROK_MODEL = os.getenv("GROK_MODEL", "grok-4").strip() or "grok-4"
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1").strip()

# --- Book ---
BOOK_TITLE = "Games for Gravitas"
BOOK_FULL_TITLE = "Games for Gravitas: A Playbook to Build Human Advantage in the Hybrid Intelligence Era"
BOOK_LINK = os.getenv("BOOK_LINK", "")  # set in Secrets if you want it; never hard-code here
BOOK_AMAZON_LINK = BOOK_LINK

# Aliases used by older code — keep both so imports never break
BOOK_NAME = BOOK_TITLE
PROMOTION_THRESHOLD = 80

# --- Search / themes (editable in Step 1 for that run only) ---
SEARCH_TERMS = [
    "corporate upskilling AI",
    "AI upskilling program",
    "L&D AI training",
    "reskilling workforce AI",
    "AI transformation leadership",
    "HR leaders AI training",
    "AI leadership skills",
    "leading teams with AI",
    "AI adoption manager",
    "human advantage AI",
]

# Keep as plain strings. Older code expected tuples and crashed.
# BOOK_THEMES_DETAILED is the tuple form for any code that needs it.
BOOK_THEMES = [
    "purposeful rehearsal",
    "rehearse before you decide",
    "centaur leadership",
    "human advantage",
    "hybrid intelligence",
    "gravitas",
    "play at work",
    "leadership under AI pressure",
]
BOOK_THEMES_DETAILED = [(t, t) for t in BOOK_THEMES]

# --- Thresholds / scoring ---
A_PROMOTE = 80
B_ENGAGE = 60
DYNAMIC_THRESHOLD = 75  # open question + low comments -> promote at 75
SATURATION_COMMENTS = 80  # >80 comments: downgrade Promote -> Engage
MAX_CONTEXT_CHARS = 4000
THEME_CAP_PROMOTE = 2  # max 2 Promote per theme
MIN_THEMES_PER_RUN = 3

# Promotion Score weights: Book 25% + Context 30% + Engagement 25% + Audience 10% + Naturalness 10%
PROMO_WEIGHTS = {"book": 0.25, "context": 0.30, "engagement": 0.25, "audience": 0.10, "naturalness": 0.10}
# Opportunity Score weights: relevance 40% + conversation 35% + recency 25%
OPP_WEIGHTS = {"relevance": 0.40, "conversation": 0.35, "recency": 0.25}

# --- Discovery constants (these were missing -> ImportError -> Discovery 0) ---
MAX_RESULTS_PER_SOURCE = 5
MEDIUM_TAGS = "leadership,artificial-intelligence,ai,future-of-work,leadership-development"
DAYS_BACK = 30
MAX_DISCOVERY_RAW = 85

# --- NEW v4.2: pruning + quota ---
# Only this many posts ever go to Gemini. Rest use heuristic (0 API calls).
MAX_POSTS_TO_ASSESS = 30
MAX_GEMINI_CALLS_PER_RUN = 12
GEMINI_DELAY_SECONDS = 3.0
GROK_DELAY_SECONDS = 2.0

# Pruning: web articles are NOT threads. If we have real social posts, drop web.
MAX_WEB_ARTICLES_IF_SOCIAL_EXISTS = 0
MAX_WEB_ARTICLES_IF_SOME_SOCIAL = 5
MAX_WEB_ARTICLES_IF_ONLY_WEB = 15
MIN_SOCIAL_TO_DROP_WEB = 8

# Platforms that count as real threads (can reply / join conversation)
SOCIAL_PLATFORMS = {"LinkedIn", "X", "Threads", "Facebook", "Instagram"}
WEB_PLATFORMS = {"Medium", "YouTube"}

# --- Draft formatting (v4.2) ---
# Bold: book title only. Italics: these phrases (longest first at runtime).
ITALIC_KEYWORDS = [
    "rehearse before you decide",
    "purposeful rehearsal",
    "centaur leadership",
    "human advantage",
    "hybrid intelligence",
    "leadership under AI pressure",
    "gravitas",
    "rehearsal",
    "rehearse",
    "play",
]

SENSITIVE_KEYWORDS = [
    "war", "genocide", "terrorist", "terrorism", "sexual assault", "rape",
    "suicide", "self-harm", "election fraud", "assassination",
]
BREAKING_KEYWORDS = ["breaking", "just announced", "just in", "developing story"]

# Abbreviations protected when breaking after "."
ABBREVIATIONS = ["Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.", "vs.", "e.g.", "i.e.", "U.S.", "U.K."]
