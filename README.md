# Leadership AI Daily Digest — v4.1 (Modular + Dual-Engine)

Workflow: discover → dedupe (URL + idea) → analyse → guardrails → draft (CEA) → review. Fail-closed. Human publishes manually.

## Run (GitHub → Streamlit Cloud)

- Main file: `app.py` — set it as the entry point in Streamlit Cloud (was `Comment_generator_V2.py`)
- Secrets: same names as v3.0 (`GEMINI_API_KEY`, `SERPER_API_KEY` or `BRAVE_API_KEY`, `YOUTUBE_API_KEY`, etc.)
- Files `seen_posts.txt` and `effectiveness.txt` are created on first run if missing. Keep `seen_posts.txt` from v3.0 for backward compatibility.

## Where each of 1-16 lives

| # | Modification | File |
|---|---|---|
| 1 | CEA + 3 archetypes (Insight Add, Curious Question, Play Invite) | `drafting/cea.py`, `drafting/generator.py` |
| 2 | Idea-seeding for B_ENGAGE (concept phrases, no book/link) | `config.py` IDEA_PHRASES, `drafting/cea.py` |
| 3 | Hook-first validation, ban generic openers | `drafting/validation.py` |
| 4 | Platform-native formatting | `drafting/formatting.py` |
| 5 | Thread openness + recency + saturation, Opportunity Score | `models.py` fields, `scoring/opportunity.py`, `scoring/selection.py` |
| 6 | Theme cap (max 2 Promote/theme) + diversity (min 3 themes) | `scoring/selection.py` enforce_theme_cap_and_diversity |
| 7 | Search terms: pain-point + upskilling / AI transformation | `config.py` SEARCH_TERMS |
| 8 | Semantic relevance via Gemini theme-fit, not keyword counting | `gemini_client.py` analyse_post, `scoring/relevance.py` fallback |
| 9 | Saturation + C_WAIT guardrails | `guardrails.py`, `models.py` C_WAIT |
| 10 | Book mention rotation (linked / plain / curiosity) | `drafting/formatting.py` book_mention_form, `drafting/generator.py` variant rotation |
| 11 | Repurpose flag | `models.py` repurpose_candidate, `gemini_client.py`, `exporters.py` |
| 12 | Low-cost effectiveness: 1 line/week | `effectiveness.py`, `app.py` section 2 |
| 13 | Dedupe by idea (title hash) + URL | `history.py` |
| 14 | Wider discovery: LinkedIn, X, Threads, Facebook, Instagram via web search | `discovery/web_search.py` detect_platform |
| 15 | Dynamic threshold 75 for open threads | `config.py` PROMOTION_THRESHOLD_OPEN, `guardrails.py` |
| 16 | Re-weighting: Book 25%, Context 30%, Engagement 25%, Audience 10%, Naturalness 10% | `config.py` SCORE_WEIGHTS, `gemini_client.py` |

## Notes

- No author fields by design (owner decision). All scoring is thread-level.
- Upload JSON can include `comment_count`, `hours_since_post`, `is_question` — if missing, defaults apply.
- C_WAIT items get no draft — hold 24h.
- Effectiveness: after posting a batch, enter replies in app → appends `date, comments_posted, replies, yield%` to `effectiveness.txt`.


## Dual-Engine v4.1 — Gemini + Grok
- Gemini = drafter + analyser (as before). Grok = independent reviewer.
- Flow: Gemini creates 3 CEA drafts -> Grok reviews ONLY the recommended draft -> you get Option A (Gemini) + Option B (Grok reviewed) with Copy buttons.
- Grok does NOT change the decision (A_PROMOTE/B_ENGAGE) or scores — it only improves wording. Same validation + book-rotation rules apply to both.
- Secrets to add in Streamlit Cloud: GROK_API_KEY, optional GROK_MODEL (default grok-4), GROK_BASE_URL (default https://api.x.ai/v1), GROK_ENABLED=true.
- Cost saver: 1 Grok call per Promote/Engage item, not per alternative. Toggle 'Dual-engine' off in sidebar to run Gemini-only.
- If Grok fails or no key, app falls back to Gemini-only — no crash.
