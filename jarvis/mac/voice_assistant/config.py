"""Central configuration for the Jarvis voice assistant.

All settings come from environment variables, with sensible defaults. A local
``.env`` file (see ``.env.example``) is loaded automatically so secrets like the
Gemini API key never get committed to git.
"""
import os
import re
from pathlib import Path


def _load_dotenv() -> None:
    """Minimal .env loader (no external dependency).

    Real environment variables always win over .env values.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        # Drop an inline comment (whitespace followed by '#'), then quotes.
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv()

# --- LLM brain: pick a provider --------------------------------------------
# ollama = local, free, no account (default); gemini / groq = cloud, free key
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()

# Ollama (runs the model locally; install from https://ollama.com)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b").strip()
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip()

# Groq (free key, no credit card, at https://console.groq.com/keys)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
# Fallback model used automatically when the primary hits its daily token cap
# (free tier: llama-3.3-70b = 100k TPD; llama-3.1-8b-instant = 500k TPD).
GROQ_FALLBACK_MODEL = os.environ.get("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant").strip()

# Google Gemini (free key at https://aistudio.google.com/apikey)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()

# --- Home automation (ESP32 light switch over MQTT) -------------------------
MQTT_BROKER = os.environ.get("MQTT_BROKER", "192.168.2.38").strip()
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
LIGHT_TOPIC = os.environ.get("LIGHT_TOPIC", "home/bedroom/light/set").strip()
# Per-room light switches share a topic pattern; the room key is detected from
# speech ("door lights on" -> front_door). Each ESP32 subscribes to its filled-in
# topic, e.g. home/front_door/light/set. Unspecified room -> DEFAULT_LIGHT_ROOM.
LIGHT_TOPIC_TEMPLATE = os.environ.get("LIGHT_TOPIC_TEMPLATE", "home/{room}/light/set").strip()
DEFAULT_LIGHT_ROOM = os.environ.get("DEFAULT_LIGHT_ROOM", "bedroom").strip()

# --- Speech to text ---------------------------------------------------------
# whisper = local & free; groq = cloud Whisper-large (needs GROQ_API_KEY, more accurate)
STT_PROVIDER = os.environ.get("STT_PROVIDER", "whisper").strip().lower()
GROQ_STT_MODEL = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo").strip()
# Primes the transcriber with likely vocabulary so names land (Jarvis, Groq, etc.)
STT_PROMPT = os.environ.get("STT_PROMPT", "").strip()  # off by default; priming can echo into output
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base").strip()
SAMPLE_RATE = 16000
# Pin the microphone to this device (substring match) regardless of the macOS
# default input. Blank = system default.
INPUT_DEVICE = os.environ.get("INPUT_DEVICE", "EMEET").strip()
RECORD_SECONDS = float(os.environ.get("RECORD_SECONDS", "4"))

# --- Hands-free wake word + voice-activity detection (VAD) -------------------
WAKE_WORD = os.environ.get("WAKE_WORD", "jarvis").strip().lower()
END_SILENCE_SEC = float(os.environ.get("END_SILENCE_SEC", "0.8"))    # trailing quiet = you're done talking
MAX_UTTERANCE_SEC = float(os.environ.get("MAX_UTTERANCE_SEC", "15"))  # safety cap per utterance
COMMAND_TIMEOUT_SEC = float(os.environ.get("COMMAND_TIMEOUT_SEC", "5"))  # wait this long for the command to start after the wake word
# After Jarvis finishes a reply, stay awake for this many seconds waiting for a
# follow-up (no "Hey Jarvis" needed). If you stay silent the whole window, goes
# back to requiring "Hey Jarvis". 0 = always require wake word.
FOLLOWUP_SEC = float(os.environ.get("FOLLOWUP_SEC", "10"))
VAD_SENSITIVITY = float(os.environ.get("VAD_SENSITIVITY", "3.0"))    # higher = needs louder speech to trigger

# Local wake-word engine (openWakeWord): listens for "Hey Jarvis" WITHOUT
# transcribing other audio. Falls back to transcription matching if unavailable.
USE_OPENWAKEWORD = os.environ.get("USE_OPENWAKEWORD", "true").strip().lower() in ("1", "true", "yes")
WAKE_MODEL = os.environ.get("WAKE_MODEL", "hey_jarvis").strip()
WAKE_THRESHOLD = float(os.environ.get("WAKE_THRESHOLD", "0.5"))
# Gate wake detection on real speech (kills false-fires on silence/noise). 0 = off.
WAKE_VAD_THRESHOLD = float(os.environ.get("WAKE_VAD_THRESHOLD", "0.5"))
WAKE_MIN_PEAK = float(os.environ.get("WAKE_MIN_PEAK", "0.04"))  # ignore wake hits when audio is this quiet

# --- Text to speech (macOS `say`, free & built-in) --------------------------
TTS_VOICE = os.environ.get("TTS_VOICE", "Daniel").strip()  # British, Jarvis-like
TTS_RATE = int(os.environ.get("TTS_RATE", "190"))  # words per minute

# --- Live tools (weather, web search) ---------------------------------------
DEFAULT_CITY = os.environ.get("DEFAULT_CITY", "").strip()  # blank = auto-detect by IP
WEATHER_UNITS = os.environ.get("WEATHER_UNITS", "celsius").strip()  # celsius | fahrenheit

# --- Quran playback (mp3quran.net) ------------------------------------------
# Reciter used when you don't name one ("play surah Al-Kahf"). Any substring of
# a reciter's name works; full list comes from the API.
DEFAULT_RECITER = os.environ.get("DEFAULT_RECITER", "Maher Al Meaqli").strip()

# --- Athan (Islamic call to prayer) -----------------------------------------
# Prayer times are fetched daily from aladhan.com for ATHAN_CITY / ATHAN_COUNTRY.
# ATHAN_METHOD: 2=ISNA (North America), 3=MWL (Europe), 15=Moon Sighting Committee
ATHAN_CITY    = os.environ.get("ATHAN_CITY",    "Montreal").strip()
ATHAN_COUNTRY = os.environ.get("ATHAN_COUNTRY", "Canada").strip()
ATHAN_METHOD  = int(os.environ.get("ATHAN_METHOD", "2"))
# Per-prayer athan audio URLs. Accepts direct MP3 links (Archive.org etc.)
# OR any YouTube / other site URL -- yt-dlp will download it automatically.
# Fajr must include "As-salatu khayrun minan nawm" (the Tatawwur phrase).
# If a per-prayer var is not set it falls back to ATHAN_URL_DEFAULT.
# To swap a recording: set the new URL in .env -- the old cached file is
# deleted automatically and the new one is downloaded on the next athan.
ATHAN_URL_FAJR    = os.environ.get(
    "ATHAN_URL_FAJR",
    # Makkah/Haram Fajr athan -- Sheikh Ali Ahmed Mullah (includes
    # "As-salatu khayrun minan nawm"). Hosted on Archive.org.
    "https://archive.org/download/MakkahFajrAdhan6913SheikhAliMullah/"
    "Makkah%20Fajr%20Adhan%206-9-13%20Sheikh%20Ali%20Mullah.mp3",
).strip()
ATHAN_URL_DEFAULT = os.environ.get(
    "ATHAN_URL_DEFAULT",
    # Standard Makkah athan for Dhuhr, Asr, Maghrib, Isha.
    "https://archive.org/download/31813MakkahAsrAdhanSheikhYunisKhoja/"
    "31-8-13%20Makkah%20Asr%20Adhan%20Sheikh%20Yunis%20Khoja.mp3",
).strip()
ATHAN_URL_DHUHR   = os.environ.get("ATHAN_URL_DHUHR",   ATHAN_URL_DEFAULT).strip()
ATHAN_URL_ASR     = os.environ.get("ATHAN_URL_ASR",     ATHAN_URL_DEFAULT).strip()
ATHAN_URL_MAGHRIB = os.environ.get("ATHAN_URL_MAGHRIB", ATHAN_URL_DEFAULT).strip()
ATHAN_URL_ISHA    = os.environ.get("ATHAN_URL_ISHA",    ATHAN_URL_DEFAULT).strip()

# --- Iqama (second call, played automatically after each athan) --------------
# After an athan finishes, the iqama is played automatically a configurable
# number of minutes later, matching the masjid convention:
#   Fajr 45m, Dhuhr 20m, Asr 20m, Maghrib 0m (right after), Isha 10m.
# Each delay is overridable from .env, e.g. IQAMA_DELAY_FAJR=40.
IQAMA_ENABLED = os.environ.get("IQAMA_ENABLED", "true").strip().lower() in ("1", "true", "yes")
IQAMA_DELAY_MINUTES = {
    "Fajr":    int(os.environ.get("IQAMA_DELAY_FAJR",    "45")),
    "Dhuhr":   int(os.environ.get("IQAMA_DELAY_DHUHR",   "20")),
    "Asr":     int(os.environ.get("IQAMA_DELAY_ASR",     "20")),
    "Maghrib": int(os.environ.get("IQAMA_DELAY_MAGHRIB", "0")),
    "Isha":    int(os.environ.get("IQAMA_DELAY_ISHA",    "10")),
}
# The iqama wording is identical for all five prayers, so one recording serves
# all of them. Accepts a direct MP3 link or any YouTube/other URL (yt-dlp).
IQAMA_URL = os.environ.get(
    "IQAMA_URL",
    # Makkah iqama -- Sheikh Ahmad Basnawi (~1 min). Hosted on Archive.org.
    "https://archive.org/download/IqamaMakkahFajr3111434SheikhAhmadBasnawi/"
    "Iqama%20-%20Makkah%20Fajr%20%5B3-11-1434%5D%20Sheikh%20Ahmad%20Basnawi.mp3",
).strip()

# --- Persona ----------------------------------------------------------------
ASSISTANT_NAME = os.environ.get("ASSISTANT_NAME", "Jarvis").strip()

# --- Terminal transcript colors (ANSI) --------------------------------------
# Color the printed conversation. Color names: black, red, green, yellow, blue,
# magenta, cyan, white, gray, bright_red (and bright_* variants). Set
# USE_COLOR=false to disable -- e.g. if your terminal theme makes one hard to
# read (black is meant for a light/white background like Terminal's default).
USE_COLOR = os.environ.get("USE_COLOR", "true").strip().lower() in ("1", "true", "yes")
USER_COLOR = os.environ.get("USER_COLOR", "white").strip().lower()          # your input
ASSISTANT_COLOR = os.environ.get("ASSISTANT_COLOR", "red").strip().lower()  # Jarvis's replies

# --- Reminders --------------------------------------------------------------
# Jarvis stores reminders locally and announces them out loud, re-nagging an
# unacknowledged one every REMINDER_INTERVAL_MIN minutes during waking hours
# (REMINDER_WAKE_START..REMINDER_WAKE_END) until you say "done".
REMINDER_INTERVAL_MIN = int(os.environ.get("REMINDER_INTERVAL_MIN", "5"))
REMINDER_WAKE_START = int(os.environ.get("REMINDER_WAKE_START", "8"))    # don't nag before this hour
REMINDER_WAKE_END = int(os.environ.get("REMINDER_WAKE_END", "22"))       # ...or at/after this hour
REMINDER_CHECK_SEC = int(os.environ.get("REMINDER_CHECK_SEC", "30"))     # how often the idle loop polls for due reminders
# Also add each reminder to the macOS Reminders app (syncs to iPhone via iCloud).
ADD_TO_MAC_REMINDERS = os.environ.get("ADD_TO_MAC_REMINDERS", "true").strip().lower() in ("1", "true", "yes")

# --- Remote (phone app over MQTT) -------------------------------------------
# Lets the iOS app (JarvisRemote) chat with Jarvis over MQTT. The phone reaches
# the Mac via Tailscale; a small mosquitto broker runs ON the Mac, so Jarvis
# subscribes locally at 127.0.0.1. This is a SEPARATE broker from the home-
# automation one (MQTT_BROKER, 192.168.2.38) that drives the ESP32 light
# switches -- light control is unchanged.
#   Phone -> publishes  {id,text}  to REMOTE_CMD_TOPIC
#   Jarvis -> runs it through handle(), speaks + acts, then
#             publishes {id,text} reply to REMOTE_REPLY_TOPIC
REMOTE_ENABLED = os.environ.get("REMOTE_ENABLED", "true").strip().lower() in ("1", "true", "yes")
REMOTE_BROKER = os.environ.get("REMOTE_BROKER", "127.0.0.1").strip()
REMOTE_PORT = int(os.environ.get("REMOTE_PORT", "1883"))
REMOTE_CMD_TOPIC = os.environ.get("REMOTE_CMD_TOPIC", "jarvis/command").strip()
REMOTE_REPLY_TOPIC = os.environ.get("REMOTE_REPLY_TOPIC", "jarvis/reply").strip()
# Broker auth (created with `mosquitto_passwd`). Blank = anonymous (only safe if
# the broker itself is firewalled to localhost + Tailscale).
REMOTE_USERNAME = os.environ.get("REMOTE_USERNAME", "").strip()
REMOTE_PASSWORD = os.environ.get("REMOTE_PASSWORD", "").strip()
REMOTE_CLIENT_ID = os.environ.get("REMOTE_CLIENT_ID", "jarvis-mac").strip()
