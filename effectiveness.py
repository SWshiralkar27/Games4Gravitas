"""#12 Low-cost effectiveness — ONE line per week, no per-comment tracking."""
from __future__ import annotations
from datetime import datetime
from config import EFFECTIVENESS_FILE

def load_effectiveness() -> list[dict]:
    if not EFFECTIVENESS_FILE.exists():
        return []
    rows = []
    for line in EFFECTIVENESS_FILE.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            try:
                rows.append({"date": parts[0], "comments_posted": int(parts[1]), "replies": int(parts[2]), "yield": float(parts[3])})
            except Exception:
                pass
    return rows

def append_effectiveness(comments_posted: int, replies: int) -> dict:
    y = round((replies / comments_posted * 100) if comments_posted else 0, 1)
    rec = {"date": datetime.now().strftime("%Y-%m-%d"), "comments_posted": comments_posted, "replies": replies, "yield": y}
    try:
        with open(EFFECTIVENESS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{rec['date']}, {comments_posted}, {replies}, {y}\n")
    except OSError:
        pass
    return rec

def yield_label(y: float) -> str:
    if y < 10:
        return "Low — comments seen but not inviting replies. Fix draft endings."
    if y < 40:
        return "Healthy — typical for good commenters."
    return "Strong — this batch had a strong idea/timing. Do more of that theme."
