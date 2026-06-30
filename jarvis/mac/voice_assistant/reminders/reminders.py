"""Persistent reminders the always-on assistant announces out loud, repeatedly,
until you acknowledge them.

Each reminder is stored in a local JSON file (``../data/reminders.json``),
with a due time (ISO 8601 local) that the LLM resolved from your
phrasing. Jarvis's main loop polls :func:`due_to_announce`; once a reminder is
past due it gets spoken, and re-spoken every ``config.REMINDER_INTERVAL_MIN``
minutes during waking hours until it's acknowledged.

If ``config.ADD_TO_MAC_REMINDERS`` is on, each new reminder is also dropped into
the macOS Reminders app (via AppleScript), so it shows up on your iPhone through
iCloud. That's best-effort: it silently no-ops if the Automation permission
isn't granted, while the local nagging keeps working regardless.
"""
import datetime
import json
import re
import subprocess
from pathlib import Path

import config

_PATH = Path(__file__).resolve().parent.parent / "data" / "reminders.json"

_WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_LOCAL_DAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

# Matches recurrence phrases embedded in a sentence.
_RECUR_RE = re.compile(
    r"\b(?:"
    r"daily"
    r"|every\s+(?:single\s+)?(?:day|morning|night|evening)"
    r"|every\s+weekdays?"
    r"|weekdays?"
    r"|every\s+weekends?"
    r"|weekends?"
    r"|every\s+(?:single\s+)?"
    r"(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
    r"(?:\s+and\s+(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?))*"
    r")\b",
    re.I,
)

# Matches "at 10am", "at 10 a.m.", "at 10:30 pm", etc.
# Capture groups: 1=hour, 2=minutes (optional), 3='a' or 'p' meridiem (optional).
_TIME_RE = re.compile(
    r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(?:([ap])[\s.]?m\.?)?",
    re.I,
)


def _local_parse_recurrence(snippet):
    """Parse a recurrence phrase to {days, time} without using the LLM."""
    t = snippet.lower()
    if re.search(r"\b(?:daily|every\s+(?:single\s+)?(?:day|morning|night|evening))\b", t):
        return {"days": list(range(7))}
    if re.search(r"\b(?:weekdays?|every\s+weekdays?)\b", t):
        return {"days": [0, 1, 2, 3, 4]}
    if re.search(r"\b(?:weekends?|every\s+weekends?)\b", t):
        return {"days": [5, 6]}
    days = []
    for name, num in _LOCAL_DAY_MAP.items():
        if re.search(r"\b" + name + r"\b", t):
            days.append(num)
    if days:
        return {"days": sorted(set(days))}
    return None


def _try_set_reminder(text):
    """Parse a 'remind me' sentence locally -- no LLM needed.

    Works for any phrasing that contains a clear time ("at 10am", "at 8:30 pm",
    "at 10 a.m.") and an extractable subject. Falls back gracefully (returns
    None) for ambiguous cases so the brain can handle them instead.
    """
    t = text.lower().strip()

    # Must be a set-reminder request, not a list/cancel.
    if not re.search(r"\bremind\s+me\b", t):
        return None

    # Require a parseable time; without it we can't set a reliable reminder.
    time_m = _TIME_RE.search(t)
    if not time_m:
        return None

    h_raw = int(time_m.group(1))
    m_raw = int(time_m.group(2) or 0)
    ampm  = (time_m.group(3) or "").lower()

    # Convert 12-hour clock to 24-hour. The two special cases are noon and
    # midnight: 12pm stays 12, 12am becomes 0; everything else is +12 for pm.
    # With no meridiem given, take the hour at face value.
    if ampm == "p" and h_raw != 12:
        h = h_raw + 12
    elif ampm == "a" and h_raw == 12:
        h = 0
    else:
        h = h_raw

    if not (0 <= h <= 23 and 0 <= m_raw <= 59):
        return None  # nonsense time (e.g. "at 25") -> let the brain try instead

    # Parse recurrence if any.
    recur_m = _RECUR_RE.search(t)
    recurrence = _local_parse_recurrence(recur_m.group(0)) if recur_m else None

    # Strip known parts to isolate the reminder subject.
    what = t
    what = re.sub(r"\b(?:hey\s+)?(?:jarvis|jarvus|jervis)\b[,\s]*", "", what)
    what = re.sub(r"\bremind\s+me\b\s*", "", what)
    if recur_m:
        what = what.replace(recur_m.group(0).lower(), "")
    what = _TIME_RE.sub("", what)                          # remove "at 10am" etc.
    what = re.sub(r"^\s*(?:to|about)\s+", "", what.strip())
    what = re.sub(r"\s+", " ", what).strip(" ,.!?-")

    if len(what) < 2:
        return None

    # Compute first occurrence: today at the requested time, but if that moment
    # has already passed, roll to the same time tomorrow.
    now = _now()
    due = now.replace(hour=h, minute=m_raw, second=0, microsecond=0)
    if due <= now:
        due += datetime.timedelta(days=1)

    # For day-specific recurrence, advance to the first matching weekday.
    if recurrence:
        days = recurrence.get("days", list(range(7)))
        if days != list(range(7)):
            for _ in range(7):
                if due.weekday() in days:
                    break
                due += datetime.timedelta(days=1)
        recurrence["time"] = f"{h:02d}:{m_raw:02d}"

    rem = add(what, due.isoformat(timespec="minutes"), recurrence=recurrence)
    due_stored = parse_due(rem.get("due"))

    if recurrence:
        label = recurrence_label(recurrence)
        return (f"Done — I'll remind you to {what} {label}, "
                f"starting {speak_due(due_stored)}.", None)
    return (f"Reminder set for {speak_due(due_stored)}: {what}.", None)


def recurrence_label(rec):
    """Human-readable label for a recurrence dict, e.g. 'every Monday & Friday'."""
    if not rec:
        return ""
    days = sorted(rec.get("days", []))
    if days == list(range(7)):
        return "every day"
    if days == [0, 1, 2, 3, 4]:
        return "every weekday"
    if days == [5, 6]:
        return "every weekend"
    if len(days) == 1:
        return f"every {_WEEKDAY_LABELS[days[0]]}"
    return "every " + " & ".join(_WEEKDAY_LABELS[d] for d in days)


def _next_occurrence(r, from_dt=None):
    """Return the next due datetime for a recurring reminder, strictly after from_dt."""
    rec = r.get("recurrence")
    if not rec:
        return None
    from_dt = from_dt or _now()
    due = parse_due(r.get("due"))
    if due:
        h, m = due.hour, due.minute
    else:
        t = (rec.get("time") or "09:00")
        h, m = map(int, t.split(":"))
    days = rec.get("days", list(range(7)))
    # Start at the recurrence time today, stepping to tomorrow if it's already
    # past, then walk forward (at most a week) to the next allowed weekday.
    candidate = from_dt.replace(hour=h, minute=m, second=0, microsecond=0)
    if candidate <= from_dt:
        candidate += datetime.timedelta(days=1)
    for _ in range(7):
        if candidate.weekday() in days:
            return candidate
        candidate += datetime.timedelta(days=1)
    return None  # empty/invalid days list -> no next occurrence


def _now():
    """Current local time (wrapped so it can be mocked/overridden in one place)."""
    return datetime.datetime.now()


def _load():
    """Read the reminder list from disk; an empty/missing/corrupt file -> []."""
    try:
        return json.loads(_PATH.read_text())
    except Exception:
        return []


def _save(items):
    """Persist the reminder list. Writes to a temp file then renames over the
    real one so a crash mid-write can't leave a half-written (corrupt) file."""
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, indent=2))
    tmp.replace(_PATH)  # atomic, so a crash mid-write can't corrupt the file


def parse_due(iso):
    """Parse a stored/LLM-supplied ISO datetime; return a datetime or None."""
    if not iso:
        return None
    text = str(iso).strip().replace("Z", "")
    try:
        return datetime.datetime.fromisoformat(text)
    except Exception:
        # Tolerate a date with no time -> assume 9am that day.
        try:
            d = datetime.date.fromisoformat(text[:10])
            return datetime.datetime(d.year, d.month, d.day, 9, 0)
        except Exception:
            return None


def add(text, when_iso, recurrence=None):
    """Add a reminder due at ``when_iso``.

    ``recurrence`` is either None (one-time) or a dict like::

        {"days": [0, 2, 4], "time": "09:00"}   # Mon / Wed / Fri at 9 am

    where days uses Python's weekday() numbering (0=Mon … 6=Sun).
    Returns the stored reminder dict.
    """
    due = parse_due(when_iso)
    items = _load()
    rid = max((r.get("id", 0) for r in items), default=0) + 1
    rem = {
        "id": rid,
        "text": (text or "").strip(),
        "due": due.isoformat(timespec="minutes") if due else None,
        "created": _now().isoformat(timespec="seconds"),
        "acknowledged": False,
        "last_announced": None,
        "count": 0,
        "recurrence": recurrence,
    }
    items.append(rem)
    _save(items)
    if config.ADD_TO_MAC_REMINDERS:
        _add_to_mac_reminders(rem["text"], due)
    return rem


def pending():
    """All not-yet-acknowledged reminders, soonest due first."""
    items = [r for r in _load() if not r.get("acknowledged")]
    items.sort(key=lambda r: r.get("due") or "")
    return items


def due_to_announce(now=None):
    """Reminders that are past due, unacknowledged, inside waking hours, and
    whose nag interval has elapsed since they were last announced."""
    now = now or _now()
    if not (config.REMINDER_WAKE_START <= now.hour < config.REMINDER_WAKE_END):
        return []
    interval = config.REMINDER_INTERVAL_MIN * 60
    out = []
    for r in _load():
        if r.get("acknowledged"):
            continue
        due = parse_due(r.get("due"))
        if due is None or due > now:
            continue
        last = parse_due(r.get("last_announced"))
        if last is not None and (now - last).total_seconds() < interval:
            continue
        out.append(r)
    out.sort(key=lambda r: r.get("due") or "")
    return out


def mark_announced(rid, now=None):
    """Record that reminder ``rid`` was just spoken: stamp the time (so the nag
    interval can be measured) and bump its announce count."""
    now = now or _now()
    items = _load()
    for r in items:
        if r.get("id") == rid:
            r["last_announced"] = now.isoformat(timespec="seconds")
            r["count"] = r.get("count", 0) + 1
    _save(items)


def acknowledge(rid):
    """Mark a reminder done. Recurring reminders are rescheduled for their next
    occurrence instead of being permanently removed."""
    items = _load()
    for r in items:
        if r.get("id") == rid:
            if r.get("recurrence"):
                next_due = _next_occurrence(r)
                if next_due:
                    r["due"] = next_due.isoformat(timespec="minutes")
                    r["acknowledged"] = False
                    r["last_announced"] = None
                    # count keeps accumulating across recurrences
                else:
                    r["acknowledged"] = True  # bad recurrence data — just stop
            else:
                r["acknowledged"] = True
    _save(items)


def cancel(query):
    """Permanently cancel unacknowledged reminders whose text contains ``query``.
    Clears any recurrence so they don't come back. Returns how many were cancelled."""
    q = (query or "").strip().lower()
    if not q:
        return 0
    items = _load()
    n = 0
    for r in items:
        if not r.get("acknowledged") and q in r.get("text", "").lower():
            r["acknowledged"] = True
            r["recurrence"] = None
            n += 1
    _save(items)
    return n


def cancel_all():
    """Permanently cancel every pending reminder (including recurring ones).
    Returns how many were cancelled."""
    items = _load()
    n = 0
    for r in items:
        if not r.get("acknowledged"):
            r["acknowledged"] = True
            r["recurrence"] = None
            n += 1
    _save(items)
    return n


def clear_mac_reminders():
    """Delete all incomplete reminders from the macOS Reminders app via AppleScript.
    Returns the count deleted, or -1 if the Automation permission isn't granted."""
    script = (
        'tell application "Reminders"\n'
        '    set allItems to every reminder whose completed is false\n'
        '    set n to count of allItems\n'
        '    repeat with r in allItems\n'
        '        delete r\n'
        '    end repeat\n'
        '    return n\n'
        'end tell'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return int((result.stdout or "0").strip())
    except Exception:
        pass
    return -1


def speak_due(dt):
    """Human phrasing of a due datetime for confirmations, e.g. 'Saturday,
    June 7 at 8:00 PM'."""
    return dt.strftime("%A, %B %-d at %-I:%M %p")


def _spoken_list():
    """The pending reminders as a spoken sentence."""
    items = pending()
    if not items:
        return "You have no reminders set, sir."
    parts = []
    for r in items:
        due = parse_due(r.get("due"))
        when = speak_due(due) if due else "no set time"
        rec = r.get("recurrence")
        if rec:
            label = recurrence_label(rec)
            parts.append(f"{r['text']}, {label}, next on {when}")
        else:
            parts.append(f"{r['text']} on {when}")
    return "Your reminders: " + "; ".join(parts) + "."


def detect_command(text):
    """Handle reminder commands locally, with no LLM -- so listing or clearing
    reminders works instantly and even when the cloud brain is rate-limited.

    Returns ``(reply, action_or_None)`` for a reminder command, or ``None`` to
    let the brain handle it (setting a new reminder, or cancelling a specific
    one, still need the LLM to parse the details).

    Examples:
        "list my reminders"            -> speak the list (no action)
        "what are my reminders"        -> speak the list
        "mark all my reminders done"   -> acknowledge every pending reminder
        "clear all reminders"          -> acknowledge every pending reminder
        "list my reminders as done"    -> acknowledge every pending reminder
        "cancel my dentist reminder"   -> None (brain's cancel_reminder picks it)
        "remind me to call mom at 8pm" -> None (brain's set_reminder)
    """
    raw = text.lower().strip()
    t = raw.strip(" .!?,")
    if not re.search(r"\breminders?\b|\bremind\s+me\b", t):
        return None

    is_question = bool(re.match(
        r"^(are|is|do|did|does|have|has|how|what|which|when|why|can|could|should)\b", raw))
    clear_verb = re.search(
        r"\b(clear|cancel|delete|remove|dismiss|acknowledge|done|complete[d]?|finish(?:ed)?)\b", t)
    all_scope = (re.search(r"\b(all|everything|every)\b", t)
                 or "as done" in t
                 or re.search(r"\breminders\b.{0,10}\bdone\b", t))

    # Mark EVERY reminder done -- only for an explicit imperative, never a question.
    if clear_verb and all_scope and not is_question:
        # cancel_all() permanently removes recurring reminders too.
        local_n = cancel_all()
        mac_n = clear_mac_reminders()
        total = local_n + max(mac_n, 0)
        if total == 0:
            return ("You have no reminders to clear, sir.", None)
        return (f"Cleared {total} reminder{'s' if total != 1 else ''}, sir.", None)

    # A specific cancel ("cancel my dentist reminder") -- let the brain's
    # cancel_reminder tool match the right one.
    if clear_verb and not all_scope:
        return None

    # List them (read-only) -- safe to do locally.
    list_intent = (re.search(r"\b(list|show|read|tell)\b", t)
                   or re.search(r"\b(my|the|any)\s+reminders?\b", t)
                   or re.fullmatch(r"(?:my\s+)?reminders?", t))
    if list_intent and not re.search(r"\bremind\s+me\b", t):
        return (_spoken_list(), None)

    # Try to set a new reminder locally so it works even when the LLM is
    # rate-limited. Falls back to None (→ brain) for ambiguous phrasing.
    if re.search(r"\bremind\s+me\b", t) and not is_question:
        return _try_set_reminder(text)

    return None


# -- macOS Reminders app (best-effort, syncs to iPhone via iCloud) -----------
def _osa_str(s):
    """A safe AppleScript string literal."""
    return '"' + (s or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _add_to_mac_reminders(text, due):
    """Add to the macOS Reminders app. Dates are built component-by-component so
    it's locale-independent. Silently no-ops without osascript/permission."""
    name = _osa_str(text)
    if due is not None:
        script = (
            "set d to (current date)\n"
            "set day of d to 1\n"            # avoid month-length overflow first
            f"set year of d to {due.year}\n"
            f"set month of d to {due.month}\n"
            f"set day of d to {due.day}\n"
            f"set hours of d to {due.hour}\n"
            f"set minutes of d to {due.minute}\n"
            "set seconds of d to 0\n"
            'tell application "Reminders" to make new reminder with properties '
            f"{{name:{name}, remind me date:d}}"
        )
    else:
        script = ('tell application "Reminders" to make new reminder with '
                  f"properties {{name:{name}}}")
    try:
        subprocess.run(["osascript", "-e", script], timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # not macOS, or Automation permission not granted -- local nag still works
