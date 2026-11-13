"""Models — ContentItem + Digest. No author fields by design."""
from __future__ import annotations
import html, re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from config import MAX_CONTEXT_CHARS


class Decision(str, Enum):
    A_PROMOTE = "A_PROMOTE"
    B_ENGAGE = "B_ENGAGE"
    C_SENSITIVE = "C_SENSITIVE"
    D_SENSITIVE = "D_SENSITIVE"
    C_WAIT = "C_WAIT"
    D_SKIP = "D_SKIP"

class Sensitivity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

_WHITESPACE = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    return _WHITESPACE.sub(" ", text).strip()

def truncate_at_boundary(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"

@dataclass
class ContentItem:
    platform: str
    title: str
    url: str
    source: str = ""
    published: str = ""
    snippet: str = ""
    full_content: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    comment_count: int = 0
    hours_since_post: float = 9999.0
    is_question: bool = False
    is_breaking_news: bool = False
    relevance_score: float = 0.0
    opportunity_score: float = 0.0
    decision: Decision = Decision.D_SKIP
    decision_reason: str = ""
    context_summary: str = ""
    sensitivity: Sensitivity = Sensitivity.LOW
    sensitivity_reason: str = ""
    confidence: Confidence = Confidence.LOW
    book_theme: str = ""
    book_alignment_score: int = 0
    contextual_relevance_score: int = 0
    engagement_score: int = 0
    audience_alignment_score: int = 0
    promotion_naturalness_score: int = 0
    promotion_score: int = 0
    promotion_justification: str = ""
    comment: str = ""
    alternatives: list[str] = field(default_factory=list)
    draft_archetype: str = ""
    draft_variant: int = 0
    rejection_reason: str = ""
    analysis_error: str = ""
    repurpose_candidate: bool = False
    repurpose_reason: str = ""
    # Dual-engine: Gemini = Option A, Grok reviewed = Option B
    grok_comment: str = ""
    grok_note: str = ""
    grok_verdict: str = ""
    grok_available: bool = False

    @property
    def content_for_analysis(self) -> str:
        return clean_text(self.full_content or self.snippet)[:MAX_CONTEXT_CHARS]

@dataclass
class Digest:
    date: str
    total_items: int
    items_by_platform: dict[str, list[ContentItem]]
    summary: str
    generated_at: str
    version: str = "4.1"
    prompt_version: str = "4.1.0"
