"""Automatic athan (Islamic call to prayer) at actual prayer times.

Prayer times are fetched daily from the free Aladhan API (aladhan.com) for
the configured city. At each prayer time a background thread:
  1. Kills any running TTS (say) or Quran (mpg123) immediately.
  2. Plays the FULL athan audio, blocking until it finishes.

Fajr uses the special Makkah/Haram recording that includes
"As-salatu khayrun minan nawm". All other prayers use a standard athan.

After each athan, the IQAMA is played automatically a per-prayer number of
minutes later (config.IQAMA_DELAY_MINUTES -- Fajr 45, Dhuhr 20, Asr 20,
Maghrib 0, Isha 10). The same background loop schedules it, so the iqama only
fires once the athan for that prayer has actually played today.

The is_playing() guard lets audio.speak() stay silent while athan is active,
so Jarvis never talks over the adhan.
"""
import json
import shutil
import subprocess
import threading
import time
from datetime import datetime, date, timedelta
from pathlib import Path

import requests

import config
from . import quran_player

_API       = "https://api.aladhan.com/v1/timingsByCity"
_DATA_DIR  = Path(__file__).resolve().parent.parent / "data"
_CACHE     = _DATA_DIR / "athan_cache.json"
_AUDIO_DIR = _DATA_DIR / "athan_audio"
_MPG       = shutil.which("mpg123") or "/opt/homebrew/bin/mpg123"
_YTDLP     = shutil.which("yt-dlp")
_UA        = {"User-Agent": "JarvisVoice/1.0"}

_AUDIO_DIR.mkdir(exist_ok=True)

# Only the five daily prayers (skip sunrise, midnight, etc.)
_PRAYERS = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")

# Per-prayer URL map — resolved from config at import time
_PRAYER_URLS: dict[str, str] = {
    "Fajr":    config.ATHAN_URL_FAJR,
    "Dhuhr":   config.ATHAN_URL_DHUHR,
    "Asr":     config.ATHAN_URL_ASR,
    "Maghrib": config.ATHAN_URL_MAGHRIB,
    "Isha":    config.ATHAN_URL_ISHA,
}

# Set of "YYYY-MM-DD:Prayer" keys whose athan we've already played today
_played: set[str] = set()

# Set of "YYYY-MM-DD:Prayer" keys whose iqama we've already played today
_iqama_played: set[str] = set()

# Flag while athan audio is actively playing
_playing = threading.Event()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_playing() -> bool:
    """True while athan audio is playing; used by audio.speak() to stay silent."""
    return _playing.is_set()


def due_to_play() -> str | None:
    """Return prayer name if its athan is due right now, else None.

    Fires within a 90-second window after the scheduled minute so a brief
    busy period (brain request, reminder) won't cause a miss."""
    now   = datetime.now()
    today = now.date().isoformat()
    times = _load_times()
    for prayer in _PRAYERS:
        t_str = times.get(prayer)
        if not t_str:
            continue
        key = f"{today}:{prayer}"
        if key in _played:
            continue
        try:
            h, m = map(int, t_str.split(":"))
            prayer_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            diff = (now - prayer_dt).total_seconds()
            if 0 <= diff <= 90:
                return prayer
        except Exception:
            pass
    return None


def iqama_due_to_play() -> str | None:
    """Return prayer name if its iqama is due right now, else None.

    The iqama is due once we're at/past (prayer time + that prayer's delay)
    AND the prayer's athan has already played today. There is no upper window:
    Maghrib's 0-minute iqama must still fire *after* the multi-minute athan
    audio finishes, and the per-day _iqama_played guard prevents repeats."""
    if not config.IQAMA_ENABLED:
        return None
    now   = datetime.now()
    today = now.date().isoformat()
    times = _load_times()
    for prayer in _PRAYERS:
        t_str = times.get(prayer)
        if not t_str:
            continue
        # Only after this prayer's athan actually played today.
        if f"{today}:{prayer}" not in _played:
            continue
        key = f"{today}:{prayer}:iqama"
        if key in _iqama_played:
            continue
        delay = config.IQAMA_DELAY_MINUTES.get(prayer, 0)
        try:
            h, m = map(int, t_str.split(":"))
            prayer_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            iqama_dt  = prayer_dt + timedelta(minutes=delay)
            if (now - iqama_dt).total_seconds() >= 0:
                return prayer
        except Exception:
            pass
    return None


def _local_path(name: str) -> Path:
    return _AUDIO_DIR / f"athan_{name.lower()}.mp3"


def _url_sidecar(name: str) -> Path:
    """Stores the URL the cached file was downloaded from, for change detection."""
    return _AUDIO_DIR / f"athan_{name.lower()}.url"


def _is_direct_mp3(url: str) -> bool:
    return url.lower().split("?")[0].endswith(".mp3")


def _ensure_audio(name: str, url: str) -> "Path | None":
    """Return path to local cached MP3 for *name*, downloading as needed.

    *name* is the cache key (a prayer name, or "iqama"); *url* is where the
    audio comes from. Accepts direct MP3 URLs (Archive.org etc.) or any
    YouTube/other site URL (requires yt-dlp). Re-downloads automatically if
    the configured URL changed.
    """
    path     = _local_path(name)
    sidecar  = _url_sidecar(name)

    # Cache hit: file exists, large enough, and URL hasn't changed since download
    cached_url = sidecar.read_text().strip() if sidecar.exists() else ""
    if path.exists() and path.stat().st_size > 100_000 and cached_url == url:
        return path

    # URL changed or file missing — remove stale file
    if path.exists():
        path.unlink()
        print(f"  [athan] URL changed for {name} — re-downloading...")
    else:
        print(f"  [athan] Downloading {name} audio (one-time)...")

    if _is_direct_mp3(url):
        try:
            resp = requests.get(url, headers=_UA, timeout=60, stream=True)
            resp.raise_for_status()
            with open(path, "wb") as f:
                for chunk in resp.iter_content(65536):
                    f.write(chunk)
            sidecar.write_text(url)
            print(f"  [athan] Saved {path.stat().st_size // 1024} KB to {path.name}")
            return path
        except Exception as exc:
            print(f"  [athan] Download failed ({exc}); will stream directly.")
            return None
    else:
        # YouTube or any other site — use yt-dlp to download as MP3
        if not _YTDLP:
            print("  [athan] yt-dlp not installed. Run: brew install yt-dlp")
            return None
        try:
            output_tpl = str(_AUDIO_DIR / f"athan_{name.lower()}.%(ext)s")
            result = subprocess.run(
                [_YTDLP, "-x", "--audio-format", "mp3", "--audio-quality", "0",
                 "--no-playlist", "-o", output_tpl, url],
                capture_output=True, text=True, timeout=180,
            )
            if path.exists() and path.stat().st_size > 100_000:
                sidecar.write_text(url)
                print(f"  [athan] Saved {path.stat().st_size // 1024} KB to {path.name}")
                return path
            print(f"  [athan] yt-dlp failed: {result.stderr[-300:]}")
            return None
        except subprocess.TimeoutExpired:
            print("  [athan] yt-dlp timed out.")
            return None
        except Exception as exc:
            print(f"  [athan] yt-dlp error: {exc}")
            return None


def _resolve_source(name: str, url: str) -> "str | None":
    """Local cached file if available, else the URL if it's a directly
    streamable MP3, else None (YouTube URLs must be cached first)."""
    local = _ensure_audio(name, url)
    if local:
        return str(local)
    if _is_direct_mp3(url):
        return url
    return None


def _play_source(source: str, label: str) -> None:
    """Interrupt TTS/Quran, then play *source* (file path or URL) to the end.

    Blocks until mpg123 finishes. *label* is shown in the transcript line."""
    # 1. Stop TTS
    subprocess.run(["pkill", "-x", "say"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 2. Stop Quran / any running mpg123
    quran_player.stop()
    time.sleep(0.3)

    _ts_str = datetime.now().strftime("%H:%M:%S | %B %-d, %Y")
    print(f"\n\033[90m[{_ts_str}]\033[0m   [athan] *** {label} ***")

    # 3. Play to completion -- proc.wait() blocks until mpg123 finishes
    try:
        proc = subprocess.Popen(
            [_MPG, "-q", source],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        proc.wait()
    except FileNotFoundError:
        print("  [athan] mpg123 not installed -- cannot play audio.")


def play(prayer: str) -> None:
    """Interrupt everything and play the full athan for *prayer*.

    Blocks until the audio finishes. Audio is cached locally after the first
    download so subsequent plays work even without internet."""
    _playing.set()
    try:
        url    = _PRAYER_URLS.get(prayer, config.ATHAN_URL_DEFAULT)
        source = _resolve_source(prayer, url)
        if source is None:
            print(f"  [athan] Cannot play {prayer} athan — no cached file and URL is not a direct MP3.")
            return
        _play_source(source, f"{prayer} athan")
        # Mark as played for today
        _played.add(f"{date.today().isoformat()}:{prayer}")
        print(f"  [athan] {prayer} athan done.")
    finally:
        _playing.clear()


def play_iqama(prayer: str) -> None:
    """Interrupt everything and play the iqama for *prayer*.

    The iqama wording is identical for every prayer, so a single cached
    recording (config.IQAMA_URL) is reused for all five."""
    _playing.set()
    try:
        source = _resolve_source("iqama", config.IQAMA_URL)
        if source is None:
            print("  [athan] Cannot play iqama — no cached file and URL is not a direct MP3.")
            return
        delay = config.IQAMA_DELAY_MINUTES.get(prayer, 0)
        _play_source(source, f"{prayer} iqama (+{delay}m after athan)")
        # Mark as played for today so it fires only once
        _iqama_played.add(f"{date.today().isoformat()}:{prayer}:iqama")
        print(f"  [athan] {prayer} iqama done.")
    finally:
        _playing.clear()


# ---------------------------------------------------------------------------
# Prayer times (Aladhan API + daily cache)
# ---------------------------------------------------------------------------

def _load_times() -> dict:
    """Return today's prayer times dict {name: "HH:MM"}, cached on disk."""
    today_str = date.today().isoformat()
    try:
        c = json.loads(_CACHE.read_text())
        if c.get("date") == today_str:
            return c["times"]
    except Exception:
        pass
    try:
        times = _fetch_times()
        try:
            _CACHE.write_text(json.dumps({"date": today_str, "times": times}))
        except Exception:
            pass
        return times
    except Exception as exc:
        print(f"  [athan] Could not fetch prayer times: {exc}")
        # Return stale cache rather than nothing
        try:
            return json.loads(_CACHE.read_text()).get("times", {})
        except Exception:
            return {}


def _fetch_times() -> dict:
    """Fetch today's prayer times from the Aladhan API."""
    today = date.today().strftime("%d-%m-%Y")
    resp  = requests.get(
        f"{_API}/{today}",
        params={
            "city":    config.ATHAN_CITY,
            "country": config.ATHAN_COUNTRY,
            "method":  config.ATHAN_METHOD,
        },
        headers=_UA, timeout=15,
    )
    resp.raise_for_status()
    raw = resp.json()["data"]["timings"]
    # Strip trailing timezone annotation: "05:23 (EDT)" -> "05:23"
    return {p: raw[p].split()[0] for p in _PRAYERS if p in raw}


def next_prayer() -> "tuple[str, str, int] | None":
    """Return (name, 'HH:MM', minutes_away) for the next upcoming prayer today.

    Returns None if all five prayers have already passed for today."""
    times = _load_times()
    now = datetime.now()
    for prayer in _PRAYERS:
        t_str = times.get(prayer)
        if not t_str:
            continue
        h, m = map(int, t_str.split(":"))
        prayer_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        diff_sec = (prayer_dt - now).total_seconds()
        if diff_sec > 0:
            return prayer, t_str, int(diff_sec / 60)
    return None


def all_prayer_times() -> dict:
    """Return today's five prayer times as {name: 'HH:MM'}."""
    return _load_times()


# ---------------------------------------------------------------------------
# Voice command detection
# ---------------------------------------------------------------------------

import re as _re

_PRAYER_WORDS = {
    # ---- English / romanized ------------------------------------------------
    "fajr":       "Fajr",
    "dhuhr":      "Dhuhr",   "zuhr":      "Dhuhr",   "dhohr":    "Dhuhr",
    "duhr":       "Dhuhr",   "duhur":     "Dhuhr",
    "asr":        "Asr",     "asar":      "Asr",      "aser":     "Asr",
    "maghrib":    "Maghrib", "magrib":    "Maghrib",  "maghreb":  "Maghrib",
    "isha":       "Isha",    "ishaa":     "Isha",     "esha":     "Isha",
    "isha'a":     "Isha",
    # ---- al- prefix romanized (Whisper often outputs these) -----------------
    "al-fajr":    "Fajr",   "alfajr":    "Fajr",
    "al-dhuhr":   "Dhuhr",  "aldhuhr":   "Dhuhr",   "al-zuhr":  "Dhuhr",
    "al-asr":     "Asr",    "alasr":     "Asr",
    "al-maghrib": "Maghrib","almaghrib": "Maghrib",
    "al-isha":    "Isha",   "alisha":    "Isha",
    # ---- Arabic script (Whisper-large-v3 outputs these for Arabic speech) ---
    "فجر":        "Fajr",   "الفجر":    "Fajr",
    "ظهر":        "Dhuhr",  "الظهر":    "Dhuhr",   "الضهر":    "Dhuhr",
    "عصر":        "Asr",    "العصر":    "Asr",
    "مغرب":       "Maghrib","المغرب":   "Maghrib",
    "عشاء":       "Isha",   "العشاء":   "Isha",    "العشا":    "Isha",
    "عشا":        "Isha",
}


def detect_command(text: str) -> "tuple[str,str] | None":
    """Return (reply, prayer) if the phrase is a manual athan request, else None.

    Matches English: 'play athan', 'play the adhan', 'play fajr athan', 'adhan', ...
    Matches Arabic:  'شغل الأذان', 'أذان المغرب', 'اقرأ أذان الفجر', ...
    """
    t = text.lower().strip()
    # Arabic أذان / آذان / اذان don't have ASCII word boundaries -- check separately.
    has_athan = (
        _re.search(r"\b(athan|adhan|azan|azaan)\b", t)
        or _re.search(r"أذان|آذان|اذان|الأذان", text)   # use original text (not lowercased) for Arabic
    )
    if not has_athan:
        return None

    # Check if a specific prayer is mentioned (works for both Latin and Arabic keys)
    for word, canonical in _PRAYER_WORDS.items():
        if word in t or word in text:
            return (f"Playing the {canonical} athan, sir.", canonical)

    # No specific prayer -- use Fajr audio as the "full/default" athan
    return ("Playing the athan, sir.", "Fajr")


# ---------------------------------------------------------------------------
# Background thread
# ---------------------------------------------------------------------------

def _checker_loop(stop: threading.Event) -> None:
    """Check for due athans (and iqamas) every 20 s; play when one is due."""
    while not stop.wait(20):          # wait(20) returns True when stop is set
        try:
            prayer = due_to_play()
            if prayer:
                play(prayer)
            # After (or in the same tick as) the athan, fire the iqama when due.
            iqama = iqama_due_to_play()
            if iqama:
                play_iqama(iqama)
        except Exception as exc:
            print(f"  [athan] checker error: {exc}")


def start(stop_event: threading.Event) -> threading.Thread:
    """Start the athan background thread. Pass the same stop_event to stop()."""
    t = threading.Thread(
        target=_checker_loop, args=(stop_event,),
        name="athan-checker", daemon=True,
    )
    t.start()
    return t
