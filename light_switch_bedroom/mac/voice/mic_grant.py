"""Runs as Python.app (foreground) to trigger the macOS mic permission dialog.
Run with:
    open -a /Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app \
         --args /path/to/mic_grant.py
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

import sounddevice as sd
import numpy as np

print("Requesting microphone access for Python.app...")
try:
    stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=1600)
    stream.start()
    data, _ = stream.read(1600)
    peak = float(np.max(np.abs(data)))
    stream.stop()
    stream.close()
    os.system(f'osascript -e \'display dialog "Microphone granted! Peak={peak:.3f}\\nYou can close this. Jarvis will now work in the background." buttons {{"OK"}} default button "OK" with title "Jarvis Mic Setup"\'')
except Exception as e:
    os.system(f'osascript -e \'display dialog "Mic error: {e}\\nPlease check System Settings > Privacy > Microphone and allow Python." buttons {{"OK"}} default button "OK" with title "Jarvis Mic Setup"\'')
