# Jarvis — hands-free home voice assistant

A Tony-Stark-style voice assistant that runs on a Mac and lives in the bedroom.
Say **"Hey Jarvis"** and it listens, thinks, and replies out loud — and it
reaches into the real world: it flips room lights over MQTT, plays the Quran and
the athan at prayer times, sets spoken reminders, controls volume, and answers
anything else from an LLM with live tools (weather, web search, time, prayer
times). It can now also be driven **from your phone** anywhere in the world.

```
                 ┌─────────── speak ────────────┐
  mic ─► VAD ─► "Hey Jarvis" wake ─► Whisper STT ─► handle() router ─┐
  (Yealink)      (openWakeWord)        (local/Groq)                  │
                                                                     ├─► light command ─► MQTT ─► ESP32 servo   (local, offline)
  phone ─► Tailscale ─► mosquitto ─► remote.py ─────────────────────┤
  (iOS app, STT on-device)                                          ├─► volume / athan / Quran                  (local)
                                                                     └─► anything else  ─► LLM brain + tools ─► spoken answer
                                                                                          (Groq / Ollama / Gemini)
```

Almost everything is **free and local**: speech-to-text can run on-device
(Whisper), text-to-speech is macOS `say`, the wake word is detected locally
(openWakeWord), and the brain can run locally (Ollama) — no account, no quota.

---

## Features at a glance

| Capability | What you say | How it works |
|---|---|---|
| **Lights** | "turn off the bedroom light", "lights out", "door lights on" | Keyword-routed → MQTT → ESP32 servo (instant, offline) |
| **Q&A / chat** | "what's the capital of France?", "explain servos in one line" | LLM brain (Groq / Ollama / Gemini) |
| **Weather** | "will it rain in Tokyo?" | `get_weather` tool (Open-Meteo) |
| **Web search** | "who won the game?" | `web_search` tool (DuckDuckGo) |
| **Prayer times** | "when's the next athan?", "what time is Maghrib?" | `get_prayer_times` tool (Aladhan API) |
| **Athan** | *(automatic at each prayer time)* + "play the athan" | Full adhan via `mpg123`, interrupts everything |
| **Quran** | "play surah Al-Kahf", "pause", "next surah" | Streams mp3quran.net via `mpg123` |
| **Reminders** | "remind me to call mom at 8pm" | Local store + spoken re-nag + macOS Reminders sync |
| **Volume** | "volume up", "set volume to 50", "mute" | macOS `osascript` |
| **Phone control** | *(type or speak in the iOS app)* | MQTT bridge over Tailscale |

Design rules that are preserved throughout:

- **Speak then act.** Jarvis confirms first, *then* performs the physical action
  (so the light flips after you hear "Turning the light off"). Exception: while
  the Quran is playing, it acts first then speaks, out of respect.
- **Stop by voice.** Saying "stop" while Jarvis is talking cuts the TTS off
  mid-sentence.
- **Athan interrupts everything.** At a prayer time it kills TTS + Quran, plays
  the full adhan blocking, then resumes; nothing talks over it.
- **Daily clean slate.** At local midnight Jarvis cleanly restarts itself
  (fresh process) to reset accumulated state.

---

## Full feature list

Everything Jarvis can do, grouped by area.

### Wake & listening
- **"Hey Jarvis" wake word**, detected **locally/offline** via openWakeWord (ONNX).
- **Silero VAD gating** + minimum-audio-peak check to suppress false wakes on
  silence/noise.
- **Transcription-based wake fallback** if openWakeWord is unavailable.
- **Energy-based VAD** captures a whole utterance (starts on speech, ends after
  trailing silence) — no cloud, no ML model.
- **Adaptive noise floor** with **auto-recalibration every 30 min** so detection
  doesn't drift as room noise changes.
- **Follow-up window** — after a reply, keep talking for `FOLLOWUP_SEC` seconds
  with no wake word needed; falls back to wake-word mode on silence.
- **0.3 s pre-roll** kept before speech onset so the first word isn't clipped.
- **Mic device pinning** (`INPUT_DEVICE` substring match) regardless of the macOS
  default; **mic auto-retry** for ~3 min at startup if the device isn't ready.

### Speech in / out
- **Speech-to-text:** local **Whisper** (configurable size) **or** Groq cloud
  **Whisper-large-v3-turbo**, with **automatic fallback** to local on cloud
  failure.
- **Hallucination filtering** — drops Whisper's stock phantom phrases ("thanks
  for watching", "you", silence, etc.) so they aren't treated as commands.
- **Text-to-speech:** macOS `say` with configurable **voice** + **rate**.
- **Interruptible speech** — say **"stop"** to cut a reply off mid-sentence
  (uses the Yealink's hardware echo cancellation so Jarvis doesn't stop itself).

### Ways to talk to it
- **Hands-free** (default) — always listening for the wake word.
- **Type in the same terminal** while hands-free — text a command and press
  Enter; mic stays live (auto-enabled only on an interactive terminal).
- **Push-to-talk** (`--push`) — press Enter, then speak.
- **Text-only** (`--text`) — keyboard, no mic at all.
- **Self-test** (`--selftest`) — verify routing/wake/config without audio.
- **Remote from your phone** — the iOS app sends typed/spoken commands over
  MQTT (see below).

### The brain (LLM)
- **Swappable provider:** Ollama (local/offline), Groq (cloud), or Gemini.
- **Tool-calling** (Ollama + Groq) — the model decides when to use a live tool.
- **Rolling conversation memory**, capped (~20 turns) so calls stay fast forever.
- **Groq daily-cap (429) auto-fallback** from the 70B model to the 8B model.
- **`tool_use_failed` self-retry** (re-rolls a malformed tool call).
- **Time-aware system prompt** (current date/time injected) so "remind me
  tomorrow at 8" resolves to an absolute time.
- **Spoken-style answers** — short, no markdown, conversational.

### Live tools
- **Weather** — current + forecast (Open-Meteo); auto-locates by IP or uses
  `DEFAULT_CITY`; °C/°F.
- **Web search** — DuckDuckGo for news/scores/lookups.
- **Date / time** — from the Mac clock.
- **Prayer times** — next athan, a specific prayer's time, time-until, or the
  full day's schedule (Aladhan).
- **Reminders** — set / list / cancel.
- **Quran** — play / stop / pause / resume / next / previous.

### Lights & home automation
- **Offline keyword routing** — light commands are matched locally and fire
  instantly, even with no internet (only non-commands go to the brain).
- **Per-room control** — `bedroom`, `front_door`, `desk` (plus `kitchen` /
  `living_room` firmware); spoken room detection.
- **"All rooms" broadcast** when no room is named ("lights out").
- **Speak-then-act** — the switch flips *after* the confirmation is spoken.
- **Graceful degradation** — fail-fast broker probe; says "the home hub looks
  offline" instead of hanging if the broker is down.

### Athan (call to prayer)
- **Automatic** full adhan at each of the five prayer times (daily times from
  Aladhan, cached, with stale-cache fallback if offline).
- **Per-prayer audio** — independent recording for Fajr/Dhuhr/Asr/Maghrib/Isha.
- **Fajr special recording** including *"As-salatu khayrun minan nawm."*
- **Any source** — direct MP3 **or YouTube/any site** (downloaded once via
  `yt-dlp`, cached, **auto re-download when you change the URL**).
- **Interrupts everything** — kills TTS + Quran, plays blocking, then resumes;
  `speak()` stays silent during it.
- **Manual trigger** — "play the athan" / "play the Fajr athan", recognized in
  **English, romanized, and Arabic script** prayer names.

### Quran playback
- **Stream any surah** by name, number, or reciter (mp3quran.net via `mpg123`).
- **Fuzzy matching** of surah and reciter names; **default reciter** configurable.
- **Playback control** — pause / resume / next / previous / stop.
- **Cached reciter & surah list** (weekly TTL, offline fallback).
- **Respectful ordering** — while the Quran plays, Jarvis acts first, then speaks.

### Reminders
- **Persistent local store** (survives restarts).
- **Spoken announcements** with **hourly re-nag until acknowledged** ("done").
- **Quiet hours** — never nags before `REMINDER_WAKE_START` / after
  `REMINDER_WAKE_END`.
- **Cancel by description** — lists matches and asks if ambiguous.
- **macOS Reminders sync** — optionally also added to the Reminders app (→ iPhone
  via iCloud).

### Volume
- **Voice control** — up / down / set to a level / mute, via `osascript`
  (applied after the confirmation is spoken).

### Remote phone control (iOS app)
- **Type or speak** a command from your phone (**on-device STT**).
- **Full parity** — lights, Quran, athan, reminders, Q&A all work.
- **Acts "normally"** — Jarvis speaks the reply aloud + performs the action on
  the Mac, and sends the reply text back to the phone.
- **Works from anywhere** over **Tailscale** (cellular included), no public
  exposure; messages **correlated by id**; optional phone-side TTS.

### Reliability & operations
- **Self-healing** — the default loop restarts on any unexpected crash.
- **Daily midnight restart** — fresh process (`os.execv`) for a clean slate.
- **Run at login** — `deploy/com.samer.jarvis.plist` LaunchAgent + `deploy/start_jarvis.sh`,
  with `logs/jarvis.log` / `logs/jarvis.err.log`.
- **Offline-capable** — lights, local brain (Ollama), local STT/wake all work
  with no internet.
- **Timestamped, color-coded transcript** in the terminal.

### ESP32 firmware (the physical switches)
- **Servo presses the real wall rocker** — GPIO 27 = ON, GPIO 13 = OFF.
- **MOSFET servo power-gating** (GPIO 26) — zero idle current between presses.
- **WiFi light sleep** while idle to stretch battery life.
- **18650 battery** builds (~2-week runtime target) with USB charging.
- **Per-room MQTT topics** (`home/<room>/light/set`).

---

## Hardware

- **Mac** — runs the assistant (Python 3.12).
- **Yealink SP92** — USB speakerphone used as both mic and speaker. Full-duplex
  with hardware echo cancellation, which is what makes "say stop to interrupt"
  work without Jarvis hearing its own voice. Pinned via `INPUT_DEVICE=Yealink`.
- **ESP32 light switches** — one per room (`bedroom`, `front_door`, `desk`, plus
  `kitchen` / `living_room` firmware). Two micro-servos physically press the
  wall rocker: GPIO **27** = ON press, **13** = OFF press, neutral at 90°. A
  MOSFET on GPIO **26** gates servo power so they draw nothing between presses.
  Firmware lives in `../../<room>/firmware/`.
- **Power (battery builds)** — 2× 18650 in parallel + TP4056 charger; the
  firmware uses WiFi **light sleep** while idle and servo power-gating to stretch
  runtime to ~2 weeks. See the firmware `mqtt.cpp` / `servo.cpp`.

---

## Module map

| File | Purpose |
|------|---------|
| `jarvis.py` | Main entry point: wake → capture → `handle()` → speak; follow-ups, reminders, athan checker, midnight restart, and the remote bridge |
| `brain.py` | Swappable LLM brain (Ollama / Groq / Gemini) with tool-calling, rolling history, and Groq 429 → fallback model |
| `tools.py` | Tools the brain can call: weather, web search, date/time, prayer times, reminders, Quran controls |
| `config.py` | All settings, loaded from `.env` / environment |
| `home/home_control.py` | Light-command detection + MQTT publish to the ESP32s |
| `audio/audio.py` | Mic capture, Whisper STT (local or Groq), `say` TTS, interruptible speech |
| `audio/listener.py` | Always-on energy-based VAD; captures whole utterances, wake-word polling |
| `audio/wakeword.py` | Local "Hey Jarvis" detection (openWakeWord + Silero VAD gate) |
| `audio/volume.py` | macOS volume control via `osascript` |
| `media/athan.py` | Prayer times (Aladhan) + automatic full athan; per-prayer audio |
| `media/quran_player.py` | Surah streaming by reciter (mp3quran.net via `mpg123`) |
| `reminders/reminders.py` | Persistent reminders, spoken re-nagging, macOS Reminders sync |
| `remote/remote.py` | **MQTT bridge for the iOS app** — runs phone commands through `handle()` |
| `remote/server.py` | HTTP bridge (`POST /ask`) — the alternative, broker-free path for the iOS app |
| `data/` | Runtime state (gitignored): caches, `reminders.json`, cached athan audio |
| `deploy/` | `com.samer.jarvis.plist` (LaunchAgent) + `start_jarvis.sh` — run at login |
| `logs/` | `jarvis.log` / `jarvis.err.log` |
| `debug/mic_grant.py`, `debug/mic_debug.py`, `debug/wake_test.py` | Manual diagnostics — run from this directory as `.venv/bin/python debug/<script>.py` |

---

## The brain

Set `LLM_PROVIDER` in `.env`:

| Provider | What it is | Cost / account |
|----------|-----------|----------------|
| `groq` | Llama-3.3-70B on Groq's fast cloud (current setup) | free key, no card |
| `ollama` *(default)* | an LLM running **locally** on the Mac | free, no account, offline |
| `gemini` | Google Gemini | free key (region-limited) |

Ollama and Groq get **tool-calling**: the model decides when to call a tool, we
run it, feed the result back, and let the model phrase the spoken answer. Groq
auto-falls back from `llama-3.3-70b-versatile` to `llama-3.1-8b-instant` when the
primary hits its daily token cap (429), so it keeps working all day.

---

## Athan (call to prayer)

Prayer times are fetched daily from the free **Aladhan** API for your city. At
each prayer time a background thread interrupts everything and plays the full
adhan. **Fajr** uses a special recording that includes *"As-salatu khayrun minan
nawm"*; the other four use a configurable default.

Each prayer can have its **own** audio, set in `.env`. URLs may be **direct MP3
links** (e.g. Archive.org) **or YouTube / any site** — those are downloaded once
via `yt-dlp` and cached. Change a URL and Jarvis re-downloads automatically.

```
ATHAN_URL_FAJR=...           # Fajr (must include the Tatawwur phrase)
ATHAN_URL_DHUHR=https://www.youtube.com/watch?v=...
ATHAN_URL_ASR=...
ATHAN_URL_MAGHRIB=...
ATHAN_URL_ISHA=...
```

---

## Remote control from your phone

The iOS app **JarvisRemote** (`../../ios/JarvisRemote/`) lets you type or **speak**
(on-device STT) a command from anywhere; Jarvis runs it exactly as if you'd
spoken in the room — lights, Quran, reminders, Q&A — speaks the reply aloud, and
sends the text back to your phone.

It uses MQTT over **Tailscale**, so it works on cellular without exposing
anything to the internet:

```
Phone ─► jarvis/command {id,text} ─► Mac mosquitto ─► remote.py ─► handle()
Phone ◄─ jarvis/reply   {id,text} ◄─ Mac mosquitto ◄─ remote.py ◄─ reply
```

Setup (one time):

```bash
# Broker on the Mac
brew install mosquitto
mosquitto_passwd -c /opt/homebrew/etc/mosquitto/passwd jarvis      # set REMOTE_USERNAME/PASSWORD
mosquitto -c remote/mosquitto.conf     # or: brew services start mosquitto

# Reach the Mac from anywhere
brew install --cask tailscale          # sign in on Mac AND phone (same account)
tailscale ip -4                        # the 100.x.y.z the app connects to
```

Set `REMOTE_*` in `.env` (see below), restart Jarvis (look for
`[remote] phone bridge live`), then build the app — full steps in
`../../ios/JarvisRemote/README.md`. This broker is **separate** from the
home-automation broker (`MQTT_BROKER`, `192.168.2.38`) that drives the lights.

---

## Setup (one time)

```bash
cd jarvis/mac/voice_assistant

# 1. Python 3.12 venv (torch/whisper have no 3.14 wheels yet)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. System tools (Homebrew)
brew install mpg123            # Quran + athan playback
brew install yt-dlp            # athan audio from YouTube/other sites (optional)
brew install ollama            # only if LLM_PROVIDER=ollama
brew services start ollama
ollama pull llama3.2:3b
brew install mosquitto         # only for the phone app
brew install --cask tailscale  # only for the phone app

# 3. Config
cp .env.example .env           # then fill in keys / broker creds
```

> The first run downloads the Whisper model (~150 MB for `base`, in
> `~/.cache/whisper`) and the openWakeWord models (one time).

If the mic permission dialog never appears, run `python debug/mic_grant.py` once.

---

## Run

```bash
source .venv/bin/activate

python jarvis.py            # hands-free (default): always listening, wakes on "Hey Jarvis"
python jarvis.py --push     # push-to-talk: press Enter, then speak
python jarvis.py --text     # type instead of speaking (no mic needed)
python jarvis.py --selftest # check routing + wake word + config, no audio
```

**Hands-free** is the default: say **"Hey Jarvis, …"**; it captures until you
stop talking, answers, and stays awake ~12 s for a follow-up (no wake word
needed). It self-heals (restarts on crash) and restarts fresh at midnight.

**Run at login (background service):** `deploy/com.samer.jarvis.plist` (LaunchAgent) +
`deploy/start_jarvis.sh` start Jarvis at login and keep it alive; logs go to
`logs/jarvis.log` / `logs/jarvis.err.log`.

---

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` \| `groq` \| `gemini` |
| `OLLAMA_MODEL` / `OLLAMA_HOST` | `llama3.2:3b` / `localhost:11434` | local model + server |
| `GROQ_API_KEY` | — | free key at console.groq.com/keys |
| `GROQ_MODEL` / `GROQ_FALLBACK_MODEL` | `llama-3.3-70b-versatile` / `llama-3.1-8b-instant` | primary + 429 fallback |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-2.0-flash` | Gemini option |
| `MQTT_BROKER` / `MQTT_PORT` | `192.168.2.38` / `1883` | **light** broker (ESP32s) |
| `LIGHT_TOPIC_TEMPLATE` / `DEFAULT_LIGHT_ROOM` | `home/{room}/light/set` / `bedroom` | light topics |
| `STT_PROVIDER` | `whisper` | `whisper` (local) \| `groq` (cloud Whisper-large) |
| `WHISPER_MODEL` / `GROQ_STT_MODEL` | `base` / `whisper-large-v3-turbo` | STT models |
| `INPUT_DEVICE` | `EMEET` | mic substring match (set to `Yealink` here) |
| `WAKE_WORD` / `WAKE_MODEL` | `jarvis` / `hey_jarvis` | wake phrase + openWakeWord model |
| `WAKE_THRESHOLD` / `WAKE_VAD_THRESHOLD` | `0.5` / `0.5` | wake confidence + speech gate |
| `END_SILENCE_SEC` / `VAD_SENSITIVITY` | `0.8` / `3.0` | end-of-speech + trigger loudness |
| `FOLLOWUP_SEC` / `COMMAND_TIMEOUT_SEC` | `12` / `5` | follow-up window + command wait |
| `TTS_VOICE` / `TTS_RATE` | `Daniel` / `190` | macOS voice + words/min |
| `DEFAULT_CITY` / `WEATHER_UNITS` | auto-IP / `celsius` | weather |
| `DEFAULT_RECITER` | `Maher Al Meaqli` | default Quran reciter |
| `ATHAN_CITY` / `ATHAN_COUNTRY` / `ATHAN_METHOD` | `Montreal` / `Canada` / `2` | prayer times (2=ISNA) |
| `ATHAN_URL_FAJR` / `_DHUHR` / `_ASR` / `_MAGHRIB` / `_ISHA` | Archive.org / default | per-prayer athan audio |
| `REMINDER_INTERVAL_MIN` / `_WAKE_START` / `_WAKE_END` | `60` / `8` / `22` | re-nag cadence + quiet hours |
| `ADD_TO_MAC_REMINDERS` | `true` | also add to macOS Reminders (→ iPhone) |
| `REMOTE_ENABLED` | `true` | enable the phone bridge |
| `REMOTE_BROKER` / `REMOTE_PORT` | `127.0.0.1` / `1883` | **phone** broker (Mac mosquitto) |
| `REMOTE_CMD_TOPIC` / `REMOTE_REPLY_TOPIC` | `jarvis/command` / `jarvis/reply` | bridge topics |
| `REMOTE_USERNAME` / `REMOTE_PASSWORD` | — | mosquitto auth |

---

## Troubleshooting

- **Mic not working / no permission dialog** → `python debug/mic_grant.py`, then allow
  your terminal under System Settings → Privacy & Security → Microphone. Use
  `python debug/wake_test.py` to watch the live wake score, `python debug/mic_debug.py` to
  compare local vs. Groq transcription.
- **Lights say "home hub looks offline"** → the ESP32 broker `192.168.2.38`
  isn't reachable; check the broker device and `MQTT_BROKER`.
- **Phone app can't connect** → confirm `mosquitto` is running, both devices are
  on the same tailnet (`tailscale status`), and the app's host = the Mac's
  `tailscale ip -4`, with the right `mosquitto_passwd` credentials.
- **Groq quota** → it auto-falls back to the 8B model for the rest of the day;
  set `STT_PROVIDER=whisper` / `LLM_PROVIDER=ollama` to go fully local.
- **It triggers on noise / cuts you off** → raise `VAD_SENSITIVITY` or
  `WAKE_THRESHOLD`; adjust `END_SILENCE_SEC`.

---

## Project layout

```
jarvis/
├── mac/voice_assistant/  # this assistant (Python)
│   ├── jarvis.py, brain.py, tools.py, config.py, requirements.txt
│   ├── audio/            # mic capture, VAD, wake word, TTS, volume
│   ├── home/             # light-command detection + MQTT publish
│   ├── media/            # athan + Quran playback
│   ├── reminders/        # persistent reminders
│   ├── remote/           # iOS bridge: MQTT (remote.py) + HTTP (server.py), mosquitto.conf
│   ├── debug/            # manual mic/wake diagnostics
│   ├── data/             # runtime state (gitignored): caches, reminders.json, athan_audio/
│   ├── deploy/           # com.samer.jarvis.plist, start_jarvis.sh (run at login)
│   └── logs/             # jarvis.log, jarvis.err.log
└── ios/JarvisRemote/     # the iOS app (SwiftUI)
../<room>/firmware/       # per-room ESP32 firmware (bedroom, desk, door, kitchen, living room)
```
