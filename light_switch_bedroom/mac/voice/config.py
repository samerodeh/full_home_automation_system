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

# Google Gemini (free key at https://aistudio.google.com/apikey)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()

# --- Home automation (ESP32 light switch over MQTT) -------------------------
MQTT_BROKER = os.environ.get("MQTT_BROKER", "192.168.2.38").strip()
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
LIGHT_TOPIC = os.environ.get("LIGHT_TOPIC", "home/bedroom/light/set").strip()

# --- Speech to text ---------------------------------------------------------
# whisper = local & free; groq = cloud Whisper-large (needs GROQ_API_KEY, more accurate)
STT_PROVIDER = os.environ.get("STT_PROVIDER", "whisper").strip().lower()
GROQ_STT_MODEL = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo").strip()
# Primes the transcriber with likely vocabulary so names land (Jarvis, Groq, etc.)
STT_PROMPT = os.environ.get("STT_PROMPT", "").strip()  # off by default; priming can echo into output
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base").strip()
SAMPLE_RATE = 16000
RECORD_SECONDS = float(os.environ.get("RECORD_SECONDS", "4"))

# --- Hands-free wake word + voice-activity detection (VAD) -------------------
WAKE_WORD = os.environ.get("WAKE_WORD", "jarvis").strip().lower()
END_SILENCE_SEC = float(os.environ.get("END_SILENCE_SEC", "0.8"))    # trailing quiet = you're done talking
MAX_UTTERANCE_SEC = float(os.environ.get("MAX_UTTERANCE_SEC", "15"))  # safety cap per utterance
FOLLOWUP_SEC = float(os.environ.get("FOLLOWUP_SEC", "12"))           # stay awake this long for follow-ups
COMMAND_TIMEOUT_SEC = float(os.environ.get("COMMAND_TIMEOUT_SEC", "5"))  # wait this long for the command to start after the wake word
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

# --- Persona ----------------------------------------------------------------
ASSISTANT_NAME = os.environ.get("ASSISTANT_NAME", "Jarvis").strip()
