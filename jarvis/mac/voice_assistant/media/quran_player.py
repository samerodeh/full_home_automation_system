"""Quran playback -- streams any surah by any reciter from mp3quran.net.

Audio URL pattern: ``{moshaf.server}{surah:03d}.mp3``, e.g.
    https://server12.mp3quran.net/maher/018.mp3   (Maher Al Meaqli, Al-Kahf)

Streams with mpg123 so even a long surah starts instantly (no full download).
One surah plays at a time; pause/resume via process signals, next/previous step
the surah number. Reciter and surah names are fuzzy-matched from spoken text, so
"play al kahf by mishary" or "play surah 18" both work. Default reciter and the
full reciter/surah lists come from the same API the user's website uses.
"""
import json
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import requests

import config

_API = "https://mp3quran.net/api/v3"
_UA = {"User-Agent": "JarvisVoice/1.0"}
_CACHE = Path(__file__).resolve().parent.parent / "data" / "quran_cache.json"
_CACHE_TTL = 7 * 24 * 3600  # refresh the reciter/surah lists weekly
_MPG = shutil.which("mpg123") or "/opt/homebrew/bin/mpg123"

# Spoken nickname -> a distinctive substring of the official reciter name as it
# appears in the API (verified against the real spellings, e.g. "Alsudaes",
# "Abdulbasit", "Al-Hussary").
_RECITER_ALIASES = {
    "maher": "meaqli", "muaqly": "meaqli", "muaiqly": "meaqli", "muaiqli": "meaqli", "meaqli": "meaqli",
    "mishary": "alafas", "mishari": "alafas", "afasy": "alafas", "alafasi": "alafas", "alafasy": "alafas",
    "sudais": "sudaes", "sudays": "sudaes", "sudaes": "sudaes",
    "basit": "basit", "abdulbasit": "basit", "abdel basset": "basit", "abdul basset": "basit",
    "husary": "hussary", "hosary": "hussary", "husari": "hussary",
    "ghamdi": "ghamdi", "ghamidi": "ghamdi", "minshawi": "minshawi", "menshawi": "minshawi",
    "shuraim": "shuraim", "shraim": "shuraim",
}
# Common surah names that don't transliterate cleanly to the API spelling.
_SURAH_ALIASES = {
    "yaseen": 36, "yasin": 36, "ya sin": 36, "taha": 20, "ta ha": 20, "mulk": 67,
    "rahman": 55, "kahf": 18, "fatiha": 1, "fatihah": 1, "ikhlas": 112, "nas": 114,
    "falaq": 113, "baqara": 2, "baqarah": 2, "waqia": 56, "waqiah": 56, "sajda": 32,
    "sajdah": 32, "kawthar": 108, "mary": 19, "cave": 18, "opening": 1, "cow": 2,
}

_DATA = None  # cached {"surahs": {str(num): name}, "reciters": [...], "ts": float}


# -- data loading -----------------------------------------------------------
def _pick_moshaf(moshafs):
    """Prefer a full 114-surah Hafs Murattal recording."""
    full = [m for m in moshafs if m.get("surah_total") == 114] or moshafs
    for m in full:
        if "hafs" in m.get("name", "").lower():
            return m
    return full[0] if full else None


def _fetch():
    """Pull the surah and reciter catalogues from the API into our own compact
    shape: {num: name} for surahs, and per reciter the audio server base URL plus
    the list of surahs they actually have recorded."""
    suwar = requests.get(f"{_API}/suwar?language=eng", headers=_UA, timeout=15).json()["suwar"]
    recs = requests.get(f"{_API}/reciters?language=eng", headers=_UA, timeout=15).json()["reciters"]
    surahs = {str(s["id"]): s["name"].strip() for s in suwar}
    reciters = []
    for r in recs:
        # Each reciter has one or more "moshaf" recordings; pick the best one.
        m = _pick_moshaf(r.get("moshaf") or [])
        if not m or not m.get("server"):
            continue  # no usable audio server for this reciter -> skip them
        # surah_list is a comma-separated string of available surah numbers;
        # assume the full 1-114 set if it's missing or malformed.
        try:
            slist = {int(x) for x in m["surah_list"].split(",") if x.strip()}
        except Exception:
            slist = set(range(1, 115))
        reciters.append({"display": r["name"].strip(), "server": m["server"], "surahs": sorted(slist)})
    return {"surahs": surahs, "reciters": reciters, "ts": time.time()}


def _load():
    global _DATA
    if _DATA:
        return _DATA
    try:  # fresh cache?
        c = json.loads(_CACHE.read_text())
        if time.time() - c.get("ts", 0) < _CACHE_TTL:
            _DATA = c
            return _DATA
    except Exception:
        pass
    try:  # fetch + cache
        _DATA = _fetch()
        try:
            _CACHE.write_text(json.dumps(_DATA))
        except Exception:
            pass
    except Exception:  # offline: fall back to any (even stale) cache
        try:
            _DATA = json.loads(_CACHE.read_text())
        except Exception:
            _DATA = None
    return _DATA


# -- fuzzy matching ---------------------------------------------------------
def _norm(s):
    """Normalize spoken/API text for fuzzy matching: lowercase, strip
    punctuation, and drop filler words ("surah", "the", "by", ...) and the
    article "al" so "Surah Al-Kahf" and "kahf" compare equal."""
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(surah|surat|sura|chapter|the|of|by|please|recited|reciter)\b", " ", s)
    s = re.sub(r"\bal\b", " ", s)  # drop the article "al"
    return re.sub(r"\s+", " ", s).strip()


def _match_surah(text):
    """Resolve spoken text to a surah number (1-114), or None. Tries, in order:
    an explicit number, a hand-curated alias, a fuzzy name match, then substring."""
    import difflib
    t = (text or "").lower()
    # 1) An explicit surah number anywhere in the text ("surah 18").
    m = re.search(r"\b(\d{1,3})\b", t)
    if m and 1 <= int(m.group(1)) <= 114:
        return int(m.group(1))
    nt = _norm(text)
    if not nt:
        return None
    # 2) A known alias / English name ("yaseen", "the cave").
    for alias, num in _SURAH_ALIASES.items():
        if alias in nt:
            return num
    data = _load()
    if not data:
        return None
    # 3) Fuzzy-match the normalized name against the full API surah list.
    norm_to_num = {_norm(v): int(k) for k, v in data["surahs"].items()}
    cand = difflib.get_close_matches(nt, list(norm_to_num), n=1, cutoff=0.6)
    if cand:
        return norm_to_num[cand[0]]
    # 4) Last resort: containment either direction (catches partial names).
    for nn, num in norm_to_num.items():  # substring either way
        if nn and (nt in nn or nn in nt):
            return num
    return None


def _match_reciter(text):
    import difflib
    recs = (_load() or {}).get("reciters") or []
    if not recs:
        return None
    nt = _norm(text)
    if not nt:
        return _default_reciter(recs)
    norms = [(r, _norm(r["display"])) for r in recs]
    # 1) spoken nickname -> a known substring of the real name
    for key, sub in _RECITER_ALIASES.items():
        if key in nt:
            for r, nm in norms:
                if sub in nm:
                    return r
    # 2) the spoken text appears verbatim in a reciter's name
    for r, nm in norms:
        if nt in nm:
            return r
    # 3) every spoken word (3+ chars) appears in the name (handles "abdul basit")
    toks = [w for w in nt.split() if len(w) >= 3]
    if toks:
        for r, nm in norms:
            if all(w in nm for w in toks):
                return r
    # 4) fuzzy, but only a confident match so we never pick an unrelated name
    cand = difflib.get_close_matches(nt, [nm for _, nm in norms], n=1, cutoff=0.8)
    if cand:
        for r, nm in norms:
            if nm == cand[0]:
                return r
    return _default_reciter(recs)


def _default_reciter(recs):
    want = config.DEFAULT_RECITER.lower()
    for r in recs:
        if want in r["display"].lower() or "meaqli" in r["display"].lower():
            return r
    return recs[0] if recs else None


# -- playback (one mpg123 process at a time) --------------------------------
class _Player:
    def __init__(self):
        self._proc = None
        self.surah = None       # current surah number
        self.reciter = None     # reciter dict
        self.paused = False

    @property
    def playing(self):
        return self._proc is not None and self._proc.poll() is None

    def stream(self, url):
        # Guarantee a single playback even across a Jarvis restart (orphaned mpg123).
        subprocess.run(["pkill", "-x", "mpg123"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self._proc = subprocess.Popen(
                [_MPG, "-q", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.paused = False
            return True
        except FileNotFoundError:
            self._proc = None
            return False

    def pause(self):
        if not self.playing:
            return "Nothing is playing, sir."
        if self.paused:
            return "It's already paused, sir."
        self._proc.send_signal(signal.SIGSTOP)
        self.paused = True
        return "Paused."

    def resume(self):
        if self._proc is None or not self.paused:
            return "Nothing is paused, sir."
        self._proc.send_signal(signal.SIGCONT)
        self.paused = False
        return "Resuming."

    def stop(self):
        had = self.playing
        if self._proc is not None:
            try:
                self._proc.send_signal(signal.SIGCONT)  # in case it was paused
                self._proc.terminate()
            except Exception:
                pass
        subprocess.run(["pkill", "-x", "mpg123"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._proc, self.paused = None, False
        return "Stopped the Quran." if had else "Nothing is playing, sir."


_P = _Player()


def _surah_name(num):
    return (_load() or {}).get("surahs", {}).get(str(num), f"number {num}")


def _start(num, rec):
    # Audio URL is the reciter's server base + zero-padded surah number, e.g.
    # ".../maher/018.mp3". {num:03d} produces the 3-digit "018" the host expects.
    url = f"{rec['server']}{num:03d}.mp3"
    if not _P.stream(url):
        return "I can't play audio -- mpg123 isn't installed."
    _P.surah, _P.reciter = num, rec
    return f"Playing Surah {_surah_name(num)}, recited by {rec['display']}."


def play(surah="", reciter=""):
    """Play a surah by a reciter (defaults to config.DEFAULT_RECITER)."""
    if not _load():
        return "I couldn't reach the Quran service right now, sir."
    rec = _match_reciter(reciter)
    if not rec:
        return "I couldn't find that reciter, sir."
    num = _match_surah(surah)
    if num is None:
        return "Which surah, sir? Say a name or number -- like Al-Kahf, or surah 18."
    if rec.get("surahs") and num not in rec["surahs"]:
        return f"Sorry sir, {rec['display']} doesn't have surah {num} available."
    return _start(num, rec)


def plan_play(surah="", reciter=""):
    """Validate playback intent without starting audio.

    Returns ``(reply_text, action_fn)`` on success so the caller can speak
    the reply first and then call action_fn() to actually start mpg123.
    Returns ``(error_text, None)`` when the request can't be fulfilled."""
    if not _load():
        return "I couldn't reach the Quran service right now, sir.", None
    rec = _match_reciter(reciter)
    if not rec:
        return "I couldn't find that reciter, sir.", None
    num = _match_surah(surah)
    if num is None:
        return "Which surah, sir? Say a name or number -- like Al-Kahf, or surah 18.", None
    if rec.get("surahs") and num not in rec["surahs"]:
        return f"Sorry sir, {rec['display']} doesn't have surah {num} available.", None
    url = f"{rec['server']}{num:03d}.mp3"
    reply = f"Playing Surah {_surah_name(num)}, recited by {rec['display']}."
    # The actual launch is wrapped in a closure (args bound now) so jarvis.py can
    # speak the reply first and only then start mpg123. Values are captured as
    # defaults so they aren't affected by later state changes.
    def _action(url=url, num=num, rec=rec):
        subprocess.run(["pkill", "-x", "mpg123"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            _P._proc = subprocess.Popen(
                [_MPG, "-q", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _P.paused = False
            _P.surah, _P.reciter = num, rec
        except FileNotFoundError:
            pass
    return reply, _action


def plan_step(delta):
    """Validate next/previous-surah intent without starting audio.

    Same return contract as plan_play: ``(reply_text, action_fn)`` or
    ``(error_text, None)``."""
    if not _P.reciter or not _P.surah:
        return "Nothing is playing, sir.", None
    # Walk in the +1/-1 direction, skipping surahs this reciter lacks (see _step).
    avail = _P.reciter.get("surahs") or list(range(1, 115))
    num = _P.surah + delta
    while 1 <= num <= 114 and num not in avail:
        num += delta
    if not (1 <= num <= 114):
        return "That's the " + ("last" if delta > 0 else "first") + " surah, sir.", None
    url = f"{_P.reciter['server']}{num:03d}.mp3"
    reply = f"Playing Surah {_surah_name(num)}."
    def _action(url=url, num=num, rec=_P.reciter):
        subprocess.run(["pkill", "-x", "mpg123"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            _P._proc = subprocess.Popen(
                [_MPG, "-q", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _P.paused = False
            _P.surah, _P.reciter = num, rec
        except FileNotFoundError:
            pass
    return reply, _action


def _step(delta):
    # delta is +1 (next) or -1 (previous). Step from the current surah in that
    # direction, skipping any the current reciter hasn't recorded, until we land
    # on an available one or run past the 1-114 bounds.
    if not _P.reciter or not _P.surah:
        return "Nothing is playing, sir."
    avail = _P.reciter.get("surahs") or list(range(1, 115))
    num = _P.surah + delta
    while 1 <= num <= 114 and num not in avail:
        num += delta
    if not (1 <= num <= 114):
        return "That's the " + ("last" if delta > 0 else "first") + " surah, sir."
    return _start(num, _P.reciter)


def next_surah():
    return _step(1)


def prev_surah():
    return _step(-1)


def pause():
    return _P.pause()


def resume():
    return _P.resume()


def stop():
    return _P.stop()
