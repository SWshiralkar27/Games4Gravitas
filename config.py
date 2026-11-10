
# config.py - v4.7.5 - Grok fallback
# Root: config.py

GEMINI_MODEL = "gemini-3.8-flash"

# Search terms - same as v4.6, do not use parenthesised OR / Serper queries
SEARCH_TERMS = [
    "corporate upskilling AI",
    "AI upskilling program",
    "L&D AI training",
    "reskilling workforce AI",
    "corporate upskilling AI site:linkedin.com",
    "AI upskilling program site:x.com",
    "L&D AI training site:threads.net",
    "reskilling workforce AI site:linkedin.com",
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
QUOTA_ASSESS_NEEDS = 12   # Assess: max 12 posts to Gemini, rest heuristic
QUOTA_DRAFT_NEEDS = 1     # Generate draft: 1 call
QUOTA_TEST_NEEDS = 1      # Test Gemini now: 1 call

# Grok fallback (separate quota from Gemini)
GROK_MODEL = "grok-3-mini"
GROK_API_URL = "https://api.x.ai/v1/chat/completions"

# Fallback model suggestion when 3.8 Flash is out
QUOTA_FALLBACK_MODEL = "gemini-3.1-flash-lite"

