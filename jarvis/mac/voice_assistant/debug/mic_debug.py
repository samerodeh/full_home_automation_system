#!/usr/bin/env python3
"""Microphone + VAD diagnostic.

Run it, say a few sentences, and it reports whether the *captured audio* is
healthy (level, clipping, length) and what both STT engines heard. This tells
a mic/VAD problem apart from a model problem.

    .venv/bin/python debug/mic_debug.py     # run from the voice/ directory
"""
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # add voice/ to sys.path

import numpy as np
import sounddevice as sd

import config
from audio import audio
from audio.listener import Listener


def describe(clip, sr):
    if clip.size == 0:
        return "EMPTY -- captured no audio (mic not heard, or threshold too high)"
    dur = clip.size / sr
    peak = float(np.max(np.abs(clip)))
    rms = float(np.sqrt(np.mean(clip.astype(np.float64) ** 2)))
    clip_pct = float(np.mean(np.abs(clip) > 0.98) * 100)
    notes = []
    if dur < 0.8:
        notes.append("SHORT (VAD may be cutting you off -> raise END_SILENCE_SEC)")
    if peak < 0.05:
        notes.append("VERY QUIET (mic gain low -> raise input volume / speak closer)")
    elif clip_pct > 1:
        notes.append(f"CLIPPING {clip_pct:.0f}% (too loud -> lower input volume)")
    verdict = "; ".join(notes) if notes else "looks healthy"
    return f"duration={dur:.2f}s  peak={peak:.3f}  rms={rms:.4f}  ->  {verdict}"


def main():
    try:
        dev = sd.query_devices(kind="input")
        print(f"Input device : {dev['name']} (native {dev['default_samplerate']:.0f} Hz)")
    except Exception as exc:
        print("Could not query input device:", exc)
    print(f"Capturing at {config.SAMPLE_RATE} Hz | VAD_SENSITIVITY={config.VAD_SENSITIVITY} "
          f"END_SILENCE_SEC={config.END_SILENCE_SEC}")

    listener = Listener().start()
    print("\nI'll capture 3 phrases. Press Enter, then say a full sentence.\n")
    try:
        for i in range(1, 4):
            input(f"[{i}/3] Press Enter, then speak: ")
            listener.flush()
            clip = listener.listen_utterance()
            print("   audio :", describe(clip, config.SAMPLE_RATE))
            with wave.open(f"/tmp/jarvis_debug_{i}.wav", "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(config.SAMPLE_RATE)
                w.writeframes((np.clip(clip, -1, 1) * 32767).astype("<i2").tobytes())
            print(f"   Groq  : {audio.transcribe(clip)!r}")
            print(f"   local : {audio._transcribe_local(clip)!r}\n")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        listener.stop()
    print("Done. Saved /tmp/jarvis_debug_*.wav")
    print("Tell me what you SAID each time vs what it printed.")


if __name__ == "__main__":
    main()
