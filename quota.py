
# quota.py - v4.7 - Gemini quota guard
# Root: quota.py
# Tracks Gemini usage per model, per Pacific day (reset = midnight PT).
# No API call is made if it would exceed RPD. Sidebar shows warning before Assess/Draft.
import json
import os
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _PT = ZoneInfo("America/Los_Angeles")
    _IST = ZoneInfo("Asia/Kolkata")
except Exception:
    _PT = timezone(timedelta(hours=-8))
    _IST = timezone(timedelta(hours=5, minutes=30))

try:
    from config import MODEL_QUOTAS
except Exception:
    MODEL_QUOTAS = {
        "gemini-3.8-flash": {"label": "Gemini 3.8 Flash", "rpd": 20, "rpm": 5, "tpm": 250000},
        "gemini-3.1-flash-lite": {"label": "Gemini 3.1 Flash Lite", "rpd": 500, "rpm": 15, "tpm": 250000},
    }

_QUOTA_FILE = os.path.join(os.path.dirname(__file__) if "__file__" in globals() else ".", "quota_usage.json")
_MEMORY = {}  # fallback when Streamlit not available
_RPM_TIMESTAMPS = {}  # model -> list[float] timestamps in last 60s


def _today_pacific():
    return datetime.now(_PT).strftime("%Y-%m-%d")

def _next_reset_ist_label():
    # Next midnight PT, shown in IST
    now_pt = datetime.now(_PT)
    nxt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    nxt_ist = nxt.astimezone(_IST)
    return nxt_ist.strftime("%I:%M %p IST, %b %d")

def get_limits(model):
    m = (model or "gemini-3.8-flash").strip().lower()
    if m in MODEL_QUOTAS:
        return MODEL_QUOTAS[m]
    # Unknown model: be conservative, assume 20/day like 3.8 Flash
    return {"label": m, "rpd": 20, "rpm": 5, "tpm": 250000}

def _load_file():
    try:
        if os.path.exists(_QUOTA_FILE):
            with open(_QUOTA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _save_file(data):
    try:
        with open(_QUOTA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass

def _get_store():
    # Prefer Streamlit session_state when available, else in-memory + file
    try:
        import streamlit as st
        if hasattr(st, "session_state"):
            return st.session_state
    except Exception:
        pass
    return _MEMORY

def _ensure_day(model):
    store = _get_store()
    key = f"quota_{model}"
    today = _today_pacific()
    # File is source of truth across reruns
    fdata = _load_file()
    fentry = fdata.get(model, {})
    # Session / memory entry
    entry = store.get(key) if isinstance(store, dict) else getattr(store, "get", lambda k, d=None: None)(key, None) if hasattr(store, "get") else None
    # Normalise entry to dict
    if not isinstance(entry, dict):
        entry = {}
    # If file has newer date, use file; if session has newer, use session; take max used for same day
    if fentry.get("date") == today and entry.get("date") == today:
        used = max(int(fentry.get("used", 0)), int(entry.get("used", 0)))
        manual = max(int(fentry.get("manual", 0)), int(entry.get("manual", 0)))
    elif fentry.get("date") == today:
        used = int(fentry.get("used", 0)); manual = int(fentry.get("manual", 0))
    elif entry.get("date") == today:
        used = int(entry.get("used", 0)); manual = int(entry.get("manual", 0))
    else:
        used = 0; manual = 0
    # Manual is a floor: if user typed "I already used 24 in AI Studio", used is at least that
    used = max(used, manual)
    new_entry = {"date": today, "used": used, "manual": manual}
    # Write back to both stores
    try:
        if isinstance(store, dict):
            store[key] = new_entry
        else:
            store[key] = new_entry
    except Exception:
        _MEMORY[key] = new_entry
    fdata[model] = new_entry
    _save_file(fdata)
    return new_entry

def get_usage(model):
    m = (model or "gemini-3.8-flash").strip().lower()
    limits = get_limits(m)
    entry = _ensure_day(m)
    used = int(entry.get("used", 0))
    limit = int(limits.get("rpd", 20))
    remaining = max(0, limit - used)
    return {
        "model": m,
        "label": limits.get("label", m),
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "pct": (used / limit * 100) if limit else 0,
        "rpm": limits.get("rpm", 5),
        "reset_label": _next_reset_ist_label(),
        "date_pacific": entry.get("date", _today_pacific()),
    }

def can_afford(model, needed=1):
    u = get_usage(model)
    return u["remaining"] >= needed

def will_exceed(model, needed=1):
    u = get_usage(model)
    return u["remaining"] < needed

def quota_level(model, needed=1):
    """Returns: 'ok' | 'warn' | 'block'"""
    u = get_usage(model)
    if u["remaining"] <= 0:
        return "block"
    if u["remaining"] < needed:
        return "warn"
    return "ok"

def record_call(model, n=1):
    m = (model or "gemini-3.8-flash").strip().lower()
    entry = _ensure_day(m)
    entry["used"] = int(entry.get("used", 0)) + int(n)
    entry["date"] = _today_pacific()
    # Persist
    store = _get_store()
    try:
        store[f"quota_{m}"] = entry
    except Exception:
        _MEMORY[f"quota_{m}"] = entry
    fdata = _load_file()
    fdata[m] = entry
    _save_file(fdata)
    # RPM timestamps
    now = time.time()
    lst = _RPM_TIMESTAMPS.get(m, [])
    lst = [t for t in lst if now - t < 60]
    lst.extend([now]*int(n))
    _RPM_TIMESTAMPS[m] = lst
    return entry

def mark_quota_exhausted(model):
    """Called when API returns 429 - mark as fully used so we stop hammering."""
    m = (model or "gemini-3.8-flash").strip().lower()
    limits = get_limits(m)
    entry = _ensure_day(m)
    entry["used"] = int(limits.get("rpd", 20))
    entry["date"] = _today_pacific()
    store = _get_store()
    try:
        store[f"quota_{m}"] = entry
    except Exception:
        _MEMORY[f"quota_{m}"] = entry
    fdata = _load_file(); fdata[m] = entry; _save_file(fdata)
    return entry

def set_manual_used(model, n):
    """User typed how many they already used today in AI Studio (outside app)."""
    m = (model or "gemini-3.8-flash").strip().lower()
    try:
        n = int(n)
    except Exception:
        return get_usage(m)
    if n < 0:
        n = 0
    entry = _ensure_day(m)
    entry["manual"] = n
    entry["used"] = max(int(entry.get("used", 0)), n)
    entry["date"] = _today_pacific()
    store = _get_store()
    try:
        store[f"quota_{m}"] = entry
    except Exception:
        _MEMORY[f"quota_{m}"] = entry
    fdata = _load_file(); fdata[m] = entry; _save_file(fdata)
    return get_usage(m)

def wait_for_rpm_slot(model, max_wait=15):
    """If we are at RPM limit, wait a little. Returns True if slot available."""
    m = (model or "gemini-3.8-flash").strip().lower()
    limits = get_limits(m)
    rpm = int(limits.get("rpm", 5))
    waited = 0
    while waited < max_wait:
        now = time.time()
        lst = [t for t in _RPM_TIMESTAMPS.get(m, []) if now - t < 60]
        _RPM_TIMESTAMPS[m] = lst
        if len(lst) < rpm:
            return True
        time.sleep(1)
        waited += 1
    return False

def quota_message(model, needed=1):
    u = get_usage(model)
    if u["remaining"] <= 0:
        return f"Quota out for {u['label']}: {u['used']}/{u['limit']} used today. Resets {u['reset_label']}. Use heuristic / template drafts only, or switch to Gemini 3.1 Flash Lite."
    if u["remaining"] < needed:
        return f"Not enough quota for full action: need {needed}, have {u['remaining']} left on {u['label']} ({u['used']}/{u['limit']} used). Will use Gemini for {u['remaining']} and heuristic for the rest."
    return f"Quota OK: {u['used']}/{u['limit']} used, {u['remaining']} left on {u['label']}."


def quota_reboot_warning(model):
    """After a Streamlit reboot, local counter resets to 0 even if Google quota is already used.
    If used==0 but user may have used Gemini before reboot, warn to sync from AI Studio."""
    u = get_usage(model)
    # If file was just created today (used==0) we cannot know if Google is also 0.
    # Show a gentle reminder only when used==0 - user can ignore if truly 0.
    if u["used"] == 0:
        return "Counter reset on reboot? If you used Gemini today BEFORE this reboot (AI Studio / earlier Assess), enter that number in 'Already used in AI Studio' below, or the app will think you have 20 left when Google says 0."
    return ""

