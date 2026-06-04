#!/bin/bash
# Jarvis startup wrapper — waits for the audio system to be ready, then runs.
# The LaunchAgent runs this instead of jarvis.py directly.

VOICE_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$VOICE_DIR/.venv/bin/python"
LOG="$VOICE_DIR/jarvis.log"

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

log "Jarvis wrapper started. Waiting for audio system..."

# Wait up to 30 s for the default audio input device to appear.
for i in $(seq 1 30); do
    if system_profiler SPAudioDataType 2>/dev/null | grep -q "Input Channels"; then
        break
    fi
    sleep 1
done

log "Audio ready (${i}s). Launching Jarvis..."

# Notify the user on the desktop.
osascript -e 'display notification "Say Hey Jarvis to wake me." with title "Jarvis" sound name "Glass"' 2>/dev/null

cd "$VOICE_DIR"
# Use the BUNDLED Python.app binary -- it carries the microphone entitlement so
# the permission prompt can actually appear (the bare venv python can't) -- but
# with the venv's installed packages via PYTHONPATH. Force arm64 because the
# .app may otherwise launch universal2 Python as x86_64.
BUNDLED_PY="/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python"
export PYTHONPATH="$VOICE_DIR/.venv/lib/python3.12/site-packages"
exec arch -arm64 "$BUNDLED_PY" -u jarvis.py >> "$LOG" 2>&1
