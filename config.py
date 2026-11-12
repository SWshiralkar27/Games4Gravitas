# config.py - v4.9.3.4 - Pillar B & C Focus Update
# Root: config.py
# --- Book & Platform Constants ---
BOOK_TITLE = "Games for Gravitas"
BOOK_THEMES = [
    {"name": "Doubling Down on the Non-Automatable Human Edge", "detail": "AI absorbs analytical processing, data crunching, task automation. Advantage is human capabilities algorithms cannot replicate: ethical judgment, empathy, critical thinking, adaptability, creative problem-solving, resilience. 【entity-World Economic Forum¦canonical_name=World Economic Forum】 Future of Jobs confirms these as most sought-after."},
    {"name": "Transitioning from Passive Training to Experiential Fail-Safe Engines", "detail": "Lectures, mandatory reading, static e-learning yield retention 5% to 10%, fail to build adaptive behaviors. Game-based learning sits at base of Learning Pyramid, practice by doing, retention up to 80% to 90% through active participation and peer collaboration. Games create safe-to-fail environments, high-risk experiments, failure without operational fallout, rapid conversion of mistakes into insights."},
    {"name": "Leveraging Facilitation, Replay, and Guided Reflection for Behavioral Transfer", "detail": "Gameplay is only half. Facilitation and debriefing bridge play to on-the-job execution. Video replay lets participants observe strategic missteps and communication breakdowns objectively, without real-time overload. Structured reflection What? So What? Now What? guides commitment to concrete, measurable daily behavioral changes."},
    {"name": "Precision Prioritization of Workforce Transition Challenges", "detail": "Do not deploy gamification randomly. Use Strategic Implementation Framework, 3 tiers: Essential Priorities, highest ROI: team cohesion, digital literacy, cross-functional communication, change resistance, leadership adaptation. Differentiator Priorities: remote onboarding, culture preservation, informal knowledge sharing by blending games into broader programs. Opportunistic Priorities: targeted awareness challenges for compliance, time-zone alignment, wellness. Match specific playbooks to challenge, e.g. Virtual Treasure Hunt for system adoption, Blindfold Game for leadership vision under uncertainty."},
    {"name": "Demonstrating Hard Business ROI and Multi-Level Payoffs, PLAY-4-PAYOFFS", "detail": "Validate value across Kirkpatrick Model, Reaction, Learning, Behavior, Business Results, plus Social Return on Investment, SROI. Accelerated Tech Adoption: Petroleum Corporation Virtual Treasure Hunt, 20% to 30% faster time-to-proficiency on new IT systems, 10% to 15% reduction in traditional classroom training costs. Streamlined Skill Building: immersive simulations report up to 30% reduction in overall training time, while raising retention."},
]
BOOK_LINK = "https://www.amazon.com/Games-Gravitas-Playbook-Advantage-Intelligence/dp/B0FZBP13F8"  # Replace with your actual book URL or landing page
BOOK_NAME_YOUTUBE = "Games for Gravitas"
PLAIN_TEXT_PLATFORMS = ["facebook", "YouTube", "Reddit", "Web - Blog"]
# --- CEA Prompting & Idea Phrases ---
IDEA_PHRASES = [
    "corporate training methods",
    "human-ai collaboration",
    "interactive learning models",
    "serious games in L&D"
]
# --- Formatting & Keyword Constants ---
ABBREVIATIONS = ["L&D", "AI", "HR", "ROI", "CEO", "CTO"]
ITALIC_KEYWORDS = ["Games for Gravitas", "serious games", "human-ai teaming"]
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

# 2026-11-11: Stage 2 - Groq fallback (separate quota from Gemini). Reason: was already calling Groq API, only names said Grok.
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Alias for old code until Stage 4 - app.py still imports GROK_MODEL
GROK_MODEL = GROQ_MODEL
GROK_API_URL = GROQ_API_URL

# Fallback model suggestion when 3.8 Flash is out
QUOTA_FALLBACK_MODEL = "gemini-3.1-flash-lite"
