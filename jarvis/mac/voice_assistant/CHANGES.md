# Jarvis — Session Changes (June 18, 2026)

## 1. Reminders nag every 5 minutes (was 60)

**File:** `config.py`

`REMINDER_INTERVAL_MIN` default changed from `60` to `5`. Any unacknowledged
reminder now repeats every 5 minutes during waking hours until you say "done"
(or "got it", "finished", "handled", etc.).

To override without touching code, set it in `.env`:
```
REMINDER_INTERVAL_MIN=10
```

---

## 2. "Remove all reminders" now clears the macOS Reminders app

**Files:** `reminders.py`, `tools.py`

### Problem
Saying "remove all reminders" returned *"You have no reminders to clear"*
because the check only looked at the local `reminders.json` file — it never
touched the macOS Reminders app.

### What was added

**`reminders.py` — new `clear_mac_reminders()` function**

Runs an AppleScript that deletes every incomplete reminder from the macOS
Reminders app and returns the count. Returns `-1` if the Automation permission
hasn't been granted.

**`reminders.py` — updated `cancel_all()` + `detect_command()`**

- Added `cancel_all()` function that marks all local reminders acknowledged.
- The "clear all" branch in `detect_command` (the fast local path that handles
  voice/typed "remove all reminders") now:
  - Clears local reminders synchronously
  - Calls `clear_mac_reminders()` to also delete from the Reminders app
  - Reports the combined total — no longer gates on local count being > 0

**`tools.py` — new `cancel_all_reminders` LLM tool**

Added as a callable tool the LLM brain can invoke when the user asks to
remove/clear/delete all reminders. It calls both `cancel_all()` and
`clear_mac_reminders()` and reports the combined count.

### Trigger phrases (voice or typed)
Any of these will work without needing the LLM:
- "remove all reminders"
- "clear all reminders"
- "delete all reminders"
- "cancel all reminders"
- "mark all my reminders done"
- "list my reminders as done"

The LLM tool also fires for phrasing the regex doesn't catch.

### Permission note
The first time "remove all reminders" is run, macOS will prompt for
**Automation → Reminders** permission. Grant it once and it works silently
from then on.

---

## Summary of file changes

| File | Change |
|------|--------|
| `config.py` | `REMINDER_INTERVAL_MIN` default: `60` → `5` |
| `reminders.py` | Added `cancel_all()`, `clear_mac_reminders()`; updated `detect_command` clear-all branch |
| `tools.py` | Added `cancel_all_reminders()` function, schema entry, and dispatch entry |
