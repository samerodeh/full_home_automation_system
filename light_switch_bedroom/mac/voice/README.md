# Jarvis — voice assistant for the bedroom light

A voice assistant that does two things:

1. **Controls the bedroom light** — say "turn off the light" and it publishes
   to the ESP32 over MQTT (instant, works even with no internet).
2. **Answers any question** — anything that isn't a light command goes to an
   LLM and comes back as a spoken answer, like talking to ChatGPT/Claude.
3. **Reaches the real world** — live tools let it tell you the weather, search
   the web, and give the date/time, not just frozen training knowledge.

```
microphone → Whisper (speech→text) → router
    router → light command  → MQTT          (local, offline)
           ↘ anything else  → LLM brain     → spoken answer (macOS `say`)
```

Everything is **free**: Whisper runs locally, macOS `say` is built in, and the
brain runs locally too (Ollama) — no account, no API key, no quota.

## The brain is swappable

Set `LLM_PROVIDER` in `.env`:

| Provider | What it is | Cost / account |
|----------|-----------|----------------|
| `ollama` *(default)* | LLM running **locally** on your Mac | free, no account, offline |
| `groq` | Llama 3.3 70B on Groq's fast cloud | free key (no card) |
| `gemini` | Google Gemini | free key (region-restricted) |

## Live abilities (tools)

Anything needing current, real-world info makes the brain call a tool — all
free, no API keys:

- 🌤️ **Weather** — "what's the weather?", "will it rain in Tokyo?" (Open-Meteo).
  No city given → your location by IP, or set `DEFAULT_CITY` in `.env`.
- 🔎 **Web search** — "who won the game?", "look up X" (DuckDuckGo).
- 🕐 **Date / time** — "what time is it?" (your Mac's clock).

## Files

| File | Purpose |
|------|---------|
| `jarvis.py` | Main entry point — the listen → think → speak loop |
| `brain.py` | Swappable LLM brain (Ollama / Groq / Gemini), with conversation memory + tool-calling |
| `tools.py` | Live tools the brain can call: weather, web search, date/time |
| `home_control.py` | MQTT light control + "is this a light command?" routing |
| `audio.py` | Mic recording, Whisper transcription, `say` text-to-speech |
| `config.py` | All settings, loaded from `.env` / environment |

## Setup (one time)

```bash
cd light_switch_bedroom/mac/voice

# 1. Python environment  (use Python 3.12 — torch/whisper have no 3.14 wheels yet)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. The local brain (Ollama)
brew install ollama
brew services start ollama        # start the server (auto-starts at login)
ollama pull llama3.2:3b           # download the model (~2 GB, one time)

# 3. Config
cp .env.example .env              # defaults are fine; LLM_PROVIDER=ollama
```

> The first run also downloads the Whisper model (~150 MB for `base`), cached
> under `~/.cache/whisper`.

## Run

```bash
source .venv/bin/activate

python jarvis.py            # hands-free: always listening, wakes on "Jarvis"
python jarvis.py --push     # push-to-talk: press Enter, then speak
python jarvis.py --text     # type instead of speaking (no mic needed)
python jarvis.py --selftest # check routing + wake word + config, no audio
```

**Hands-free** is the default: say **"Jarvis, …"** and it captures until you stop
talking, then answers — staying awake ~12 s for follow-ups. The first run asks
for **microphone access** (System Settings → Privacy & Security → Microphone);
allow it for your terminal. Tune `VAD_SENSITIVITY` / `END_SILENCE_SEC` in `.env`
if it triggers on noise or cuts you off.

**Try saying** (prefix with "Jarvis,") **/ typing:**

- "turn on the light" / "lights out" → flips the switch over MQTT
- "what's the capital of France?" → the brain answers, spoken aloud
- "explain how a servo motor works in one sentence" → spoken answer
- "what's the weather like?" → live forecast, spoken
- "who won the last World Cup?" → web search, summarized aloud

## Configuration (`.env`)

- `LLM_PROVIDER` — `ollama` (default), `groq`, or `gemini`
- `OLLAMA_MODEL` — `llama3.2:3b` (default). For better answers:
  `ollama pull llama3.1:8b` then set `OLLAMA_MODEL=llama3.1:8b`
- `WHISPER_MODEL` — `tiny`/`base`/`small`/`medium` (bigger = slower, more accurate)
- `TTS_VOICE` — any macOS voice (`say -v "?"` to list); defaults to `Daniel` (British)
- `MQTT_BROKER` / `LIGHT_TOPIC` — match your ESP32 setup
- `DEFAULT_CITY` — default weather location (blank = auto-detect by IP)
- `WEATHER_UNITS` — `celsius` (default) or `fahrenheit`

To use Groq instead of local: get a free key at <https://console.groq.com/keys>,
put it in `.env` as `GROQ_API_KEY=...`, and set `LLM_PROVIDER=groq`.

## Notes

- Light commands are matched locally by keyword, so they're instant and work
  offline. Only non-command speech is sent to the brain.
- This supersedes the earlier `listen.py` (on/off only) and `../voice_servo.py`
  (Google STT + HTTP). They're left in place for reference.
```
