"""Config — single source of truth for v4. All values overridable via env / Streamlit Secrets."""
from __future__ import annotations
import os
from pathlib import Path

VERSION = "4.1"
PROMPT_VERSION = "4.1.0"

AUTHOR_NAME = os.getenv("AUTHOR_NAME", "Shreekant Shiralkar")
BOOK_TITLE = "Games for Gravitas"
BOOK_SUBTITLE = "A Playbook to Build Human Advantage in the Hybrid Intelligence Era"
BOOK_FULL_TITLE = f"{BOOK_TITLE}: {BOOK_SUBTITLE}"
BOOK_URL = os.getenv("BOOK_URL", "https://www.amazon.in/Games-Gravitas-Playbook-Advantage-Intelligence-ebook/dp/B0FYNLLZ32")
BOOK_NAME_YOUTUBE = BOOK_TITLE

PROMOTION_THRESHOLD = int(os.getenv("PROMOTION_THRESHOLD", "80"))
PROMOTION_THRESHOLD_OPEN = int(os.getenv("PROMOTION_THRESHOLD_OPEN", "75"))
ENGAGEMENT_THRESHOLD = int(os.getenv("ENGAGEMENT_THRESHOLD", "60"))
MIN_CONTEXT_CHARS = int(os.getenv("MIN_CONTEXT_CHARS", "180"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "12000"))
MAX_COMMENT_COUNT_SATURATION = int(os.getenv("MAX_COMMENT_COUNT_SATURATION", "80"))
MAX_PROMOTE_PER_THEME = int(os.getenv("MAX_PROMOTE_PER_THEME", "2"))
MIN_THEMES_PER_RUN = int(os.getenv("MIN_THEMES_PER_RUN", "3"))

HISTORY_FILE = Path(os.getenv("HISTORY_FILE", "seen_posts.txt"))
EFFECTIVENESS_FILE = Path(os.getenv("EFFECTIVENESS_FILE", "effectiveness.txt"))
HISTORY_DAYS = int(os.getenv("HISTORY_DAYS", "90"))
IGNORE_HISTORY = os.getenv("IGNORE_HISTORY", "false").lower() == "true"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_DELAY_SECONDS = float(os.getenv("GEMINI_DELAY_SECONDS", "3"))

# Dual-engine: Grok reviews Gemini drafts. Optional — if no key, Gemini-only mode.
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4")
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")
GROK_DELAY_SECONDS = float(os.getenv("GROK_DELAY_SECONDS", "1.5"))
GROK_ENABLED = os.getenv("GROK_ENABLED", "true").lower() == "true"
# How many Gemini drafts Grok reviews per item: 1 = only recommended draft (saves cost/latency)
GROK_REVIEW_COUNT = int(os.getenv("GROK_REVIEW_COUNT", "1"))

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "serper").strip().lower()
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

_DEFAULT_SEARCH = (
    "Leadership AI, Human-centered AI, hybrid intelligence, "
    "AI decision making, team judgment under pressure, AI and critical thinking, leaders struggling with AI, "
    "corporate upskilling AI, AI upskilling program organization, L&D AI training, future of work AI skills, "
    "AI transformation leadership, reskilling workforce AI, AI literacy for leaders, "
    "AI transformation upskilling program, HR leaders AI training, learning and development AI era"
)
SEARCH_TERMS = [t.strip() for t in os.getenv("SEARCH_TERMS", _DEFAULT_SEARCH).split(",") if t.strip()]
MEDIUM_TAGS = [t.strip() for t in os.getenv("MEDIUM_TAGS", "leadership-ai, artificial-intelligence, technology, future-of-work, learning-and-development").split(",") if t.strip()]
MAX_RESULTS_PER_SOURCE = int(os.getenv("MAX_RESULTS_PER_SOURCE", "5"))
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.1"))
DAYS_BACK = int(os.getenv("DAYS_BACK", "7"))

PROMPTS_DIR = Path(os.getenv("PROMPTS_DIR", Path(__file__).parent / "prompts"))

BOOK_THEMES = [
    ("Centaur leadership", "Humans and AI together out-think either one alone."),
    ("Purposeful rehearsal", "Structured games let leaders rehearse high-stakes decisions safely."),
    ("Playbook over theory", "Modular exercises that leaders actively apply."),
    ("Non-automatable skills", "Judgment, intuition, empathy, ethics and creativity."),
    ("Hybrid Intelligence Era", "AI as a strategic collaborator; humans and AI co-evolve."),
    ("Structured human-AI teaming", "The 7-Phase Model for blended human-AI teams."),
]

IDEA_PHRASES = [
    "purposeful rehearsal",
    "rehearse before you decide",
    "centaur leadership",
    "hybrid intelligence",
    "structured human-AI teaming",
]

PLAIN_TEXT_PLATFORMS = {"YouTube", "YouTube Shorts"}
PLATFORM_ORDER = ["LinkedIn", "X", "Threads", "Medium", "YouTube", "YouTube Shorts", "Facebook", "Instagram"]
PLATFORM_LABEL = {"LinkedIn": "LinkedIn", "X": "X / Twitter", "Threads": "Threads", "Medium": "Medium", "YouTube": "YouTube", "YouTube Shorts": "YouTube Shorts", "Facebook": "Facebook", "Instagram": "Instagram"}
PLATFORM_ICON = {"LinkedIn": "in", "X": "X", "Threads": "@", "Medium": "M", "YouTube": "▶", "YouTube Shorts": "▶", "Facebook": "f", "Instagram": "IG"}

KEYWORDS = ("ai", "artificial", "intelligence", "leadership", "leader", "hybrid", "centaur", "judgment", "rehearsal", "playbook", "team", "human", "automat", "empathy", "ethics", "upskilling", "reskilling", "training", "learning", "transformation")

RECENCY_GOLD_HOURS = 4
RECENCY_GOOD_HOURS = 24
COMMENT_SWEET_MIN = 5
COMMENT_SWEET_MAX = 30

SCORE_WEIGHTS = {
    "book_alignment_score": 0.25,
    "contextual_relevance_score": 0.30,
    "engagement_score": 0.25,
    "audience_alignment_score": 0.10,
    "promotion_naturalness_score": 0.10,
}
