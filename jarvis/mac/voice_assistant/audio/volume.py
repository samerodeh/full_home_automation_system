"""Mac system volume control via osascript.

Handles spoken commands like "volume up", "volume down 20", "mute",
"set volume to 50". Integrates with the deferred-action pattern so
Jarvis speaks the confirmation before the volume actually changes.
"""
import re
import subprocess

_STEP = 5  # default % change per "up" / "down"; levels snap to multiples of 5


# -- low-level helpers -------------------------------------------------------
def _round5(n: int) -> int:
    """Round to the nearest multiple of 5 (e.g. 37 -> 35, 38 -> 40)."""
    return int(round(n / 5.0)) * 5


def _snap(level: int) -> int:
    """Snap to the nearest multiple of 5 and clamp to 0-100."""
    return max(0, min(100, _round5(level)))


def _get() -> int:
    out = subprocess.check_output(
        ["osascript", "-e", "output volume of (get volume settings)"],
        text=True, stderr=subprocess.DEVNULL,
    ).strip()
    return int(out)


def _set(level: int) -> None:
    level = max(0, min(100, level))
    subprocess.run(
        ["osascript", "-e", f"set volume output volume {level}"],
        check=False,
    )


def _mute(on: bool) -> None:
    flag = "with" if on else "without"
    subprocess.run(
        ["osascript", "-e", f"set volume {flag} output muted"],
        check=False,
    )


# -- command detection -------------------------------------------------------
def detect(text: str):
    """Parse a spoken phrase for a volume command.

    Returns ``(reply_text, action_fn)`` if it's a volume command,
    or ``None`` if it isn't. The caller should speak reply_text first,
    then call action_fn() -- matching the deferred-action pattern used
    for lights and Quran.
    """
    t = text.lower().strip()

    # -- mute / unmute -------------------------------------------------------
    if re.search(r"\bunmute\b", t):
        return "Unmuted, sir.", lambda: _mute(False)

    if re.search(r"\b(mute|silence)\b", t):
        return "Muted, sir.", lambda: _mute(True)

    # Only act on a clear volume cue, so a stray number elsewhere ("I said 80
    # not 100") can't hijack the parser.
    about_volume = bool(re.search(
        r"\b(volume|sound|loud|louder|quiet|quieter|soft|softer|"
        r"turn (?:it |the |them )?(?:up|down)|raise|lower|increase|decrease)\b", t))
    if not about_volume:
        return None

    up   = bool(re.search(r"\b(volume\s+up|louder|turn\s+(?:it\s+|the\s+|them\s+)?up|(?:raise|increase)\s+(?:the\s+)?(?:volume|sound|it))\b", t))
    down = bool(re.search(r"\b(volume\s+down|quieter|softer|turn\s+(?:it\s+|the\s+|them\s+)?down|(?:lower|decrease)\s+(?:the\s+)?(?:volume|sound|it))\b", t))

    # -- explicit absolute target: "to 80", "volume 80", "80 percent" --------
    # A "to N" target WINS even when up/down is present, so "turn the volume up
    # to 80" sets 80 (not "increase by 80"). Relative amounts use "by N" or a
    # bare "N" with no "to".
    m_target = (re.search(r"\bto\s+(\d{1,3})\b", t)         # "...to 80"
                or re.search(r"\bvolume\s+(\d{1,3})\b", t)  # "volume 80"
                or re.search(r"\b(\d{1,3})\s*(?:percent|%)\b", t))  # "80 percent"
    if m_target:
        level = _snap(int(m_target.group(1)))
        return f"Setting volume to {level}, sir.", lambda l=level: _set(l)

    # -- special targets (need the volume cue above; no bare "100"/"zero") ----
    if re.search(r"\b(max|maximum|full)\b", t):
        return "Max volume, sir.", lambda: _set(100)
    if re.search(r"\b(min|minimum|silent|zero)\b", t):
        return "Volume at minimum, sir.", lambda: _set(0)

    if not up and not down:
        return None  # mentioned volume but gave no direction or target

    # -- relative up / down --------------------------------------------------
    # Explicit step ("up by 20", "up 20"); default 5. Snapped to a multiple of 5
    # (min 5 so a tiny "up 2" still nudges).
    m_step = re.search(r"\b(?:by\s+)?(\d{1,3})\b", t)
    step = max(5, _round5(int(m_step.group(1)))) if m_step else _STEP

    if up:
        new_level = min(100, _round5(_get()) + step)
        return f"Volume up to {new_level}, sir.", lambda l=new_level: _set(l)
    else:
        new_level = max(0, _round5(_get()) - step)
        return f"Volume down to {new_level}, sir.", lambda l=new_level: _set(l)
