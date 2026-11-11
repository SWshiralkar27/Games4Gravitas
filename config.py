# config.py - v4.9.3.4 - Pillar B & C Focus Update
# Root: config.py
# --- Book & Platform Constants ---
BOOK_TITLE = "Games for Gravitas"
BOOK_LINK = "https://www.amazon.com/dp/YOUR_BOOK_ID"  # Replace with your actual book URL or landing page
BOOK_NAME_YOUTUBE = "Games for Gravitas"
PLAIN_TEXT_PLATFORMS = ["X", "LinkedIn", "YouTube", "Reddit", "Web - Blog"]
# --- CEA Prompting & Idea Phrases ---
IDEA_PHRASES = [
    "corporate training methods",
    "human-ai collaboration",
    "interactive learning models",
    "serious games in L&D"
]
GEMINI_MODEL = "gemini-3.8-flash"

# Serper auto-detect - if SERPER_API_KEY is in Secrets, use Serper; else DuckDuckGo
import os as _os
SERPER_API_KEY = _os.getenv("SERPER_API_KEY", "")
SEARCH_PROVIDER = "serper" if SERPER_API_KEY else "duckduckgo"
YOUTUBE_API_KEY = _os.getenv("YOUTUBE_API_KEY", "")
# Missing imports that web_search.py / youtube.py need - empty is fine if you use Serper, just needs to exist
BRAVE_API_KEY = _os.getenv("BRAVE_API_KEY", "")
DAYS_BACK = 7
MAX_CONTEXT_CHARS = 2000

# Search terms - Updated to focus on Pillars B (Corporate L&D & Training Methods) & C (Human-AI Collaboration & Teaming)
SEARCH_TERMS = [
    # Pillar B: Corporate L&D & Training Methods
    "corporate training ROI",
    "why corporate training fails",
    "experiential learning corporate",
    "L&D strategy transformation",
    "employee training effectiveness",
    # Pillar C: Human-AI Collaboration & Teaming
    "human ai collaboration workplace",
    "future of work human skills",
    "preserving human judgment in AI",
    "blended workforce strategy",
    # Platform-specific targeted searches
    "corporate upskilling AI site:linkedin.com",
    "L&D AI training site:x.com",
    "experiential learning corporate site:threads.net",
]

MAX_POSTS_TO_ASSESS = 30
MAX_RESULTS_PER_SOURCE = 5

# --- Gemini quota limits (Free Tier, from AI Studio Rate Limits page) ---
# RPD = requests per day, RPM = requests per minute, TPM = tokens per minute
# Reset = midnight Pacific Time = 1:30 PM IST next day (Nov, PST)
MODEL_QUOTAS = {
    "gemini-3.8-flash": {
        "label": "Gemini 3.8 Flash",
        "rpd": 20,
        "rpm": 5,
        "tpm": 250000,
    },
    "gemini-3.6-flash": {
        "label": "Gemini 3.6 Flash",
        "rpd": 20,
        "rpm": 5,
        "tpm": 250000,
    },
    "gemini-3.1-flash-lite": {
        "label": "Gemini 3.1 Flash Lite",
        "rpd": 500,
        "rpm": 15,
        "tpm": 250000,
    },
    "gemini-3.5-flash-lite": {
        "label": "Gemini 3.5 Flash Lite",
        "rpd": 500,
        "rpm": 15,
        "tpm": 250000,
    },
    "gemini-3-flash-preview": {
        "label": "Gemini 3 Flash Preview",
        "rpd": 20,
        "rpm": 5,
        "tpm": 250000,
    },
}

# How many Gemini calls each action needs
QUOTA_ASSESS_NEEDS = 12    # Assess: max 12 posts to Gemini, rest heuristic
QUOTA_DRAFT_NEEDS = 1      # Generate draft: 1 call
QUOTA_TEST_NEEDS = 1       # Test Gemini now: 1 call

# --- Discovery providers ---
SERPER_API_KEY = _os.getenv("SERPER_API_KEY", "")
SEARCH_PROVIDER = "serper" if SERPER_API_KEY else "duckduckgo"
YOUTUBE_API_KEY = _os.getenv("YOUTUBE_API_KEY", "")

# Grok fallback (separate quota from Gemini)
GROK_MODEL = "openai/gpt-oss-20b"
GROK_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Fallback model suggestion when 3.8 Flash is out
QUOTA_FALLBACK_MODEL = "gemini-3.1-flash-lite"
