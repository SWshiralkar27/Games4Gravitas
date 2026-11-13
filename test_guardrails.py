from scoring.selection import assess_heuristic_guarded, assess_from_scores
from drafting.generator import build_fallback_comment, generate_drafts

# Check 1 - Sensitive is blocked end-to-end
p1 = {"title": "suicide prevention discussion", "snippet": "suicide", "link": "https://example.com/1", "platform": "Web"}
h1 = assess_heuristic_guarded(p1)
print("Check 1a - heuristic Sensitive:", h1.get("decision"), "| PASS" if h1.get("decision") == "D_SENSITIVE" else "| FAIL")

p1b = {"title": "test", "snippet": "test", "link": "https://example.com/1b", "platform": "Web", "decision": "D_SENSITIVE"}
generate_drafts(None, p1b, variant=0, groq_client=None)
print("Check 1b - generator Sensitive:", p1b.get("comment", "")[:50], "| PASS" if "BLOCKED" in str(p1b.get("comment", "")) else "| FAIL")

# Check 2 - Locked D1 thresholds via assess_from_scores
p2 = {"title": "AI upskilling", "snippet": "upskilling", "link": "https://example.com/2", "platform": "Web"}
h2 = assess_from_scores(p2, 90, 90, 90, "upskilling", "test", source="gemini", flags={"sensitive": False, "is_breaking": False, "confidence": "HIGH"})
print("Check 2 - high scores ->", h2.get("decision"), "promo:", h2.get("promo"), "opp:", h2.get("opp"), "| PASS" if h2.get("decision") == "A_PROMOTE" else "| FAIL")

# Check 3 - Book only for Promote in fallback
f_promote = build_fallback_comment({"title": "AI upskilling | test", "link": "https://example.com/3", "decision": "A_PROMOTE"}, False, 0)
f_engage = build_fallback_comment({"title": "AI upskilling | test", "link": "https://example.com/3", "decision": "B_ENGAGE"}, False, 0)
print("Check 3a - Promote fallback has book:", "Games for Gravitas" in f_promote, "| PASS" if "Games for Gravitas" in f_promote else "| FAIL")
print("Check 3b - Engage fallback has NO book:", "Games for Gravitas" not in f_engage, "| PASS" if "Games for Gravitas" not in f_engage else "| FAIL")
print("Check 3c - Engage fallback:", f_engage[:120])
