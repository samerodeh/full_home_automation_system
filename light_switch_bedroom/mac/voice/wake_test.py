#!/usr/bin/env python3
"""Live wake-word monitor. Shows the mic level and the "Hey Jarvis" score in
real time, so you can SEE whether the mic is heard and whether the wake fires.

    .venv/bin/python wake_test.py

Watch the two numbers while you speak:
  - mic_peak  : how loud the mic hears you. If it stays ~0.000 while you talk,
                the mic isn't being delivered -> a permission problem.
  - wake_score: rises toward 1.0 when you say "Hey Jarvis".
"""
import numpy as np
import sounddevice as sd

import config
from wakeword import WakeWord


def main():
    try:
        dev = sd.query_devices(kind="input")
        print(f"Mic: {dev['name']} (native {dev['default_samplerate']:.0f} Hz)")
    except Exception as exc:
        print("Could not query mic:", exc)

    print("Loading openWakeWord...")
    ww = WakeWord()
    print(f'Ready. Say "Hey Jarvis" a few times. Ctrl-C to stop.\n')

    stream = sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1,
                            dtype="float32", blocksize=1280)
    stream.start()
    loudest = 0.0
    try:
        while True:
            data, _ = stream.read(1280)
            frame = data[:, 0]
            peak = float(np.max(np.abs(frame)))
            loudest = max(loudest, peak)
            fired = ww.detect(frame)  # uses the silence guard
            bar = "#" * int(ww.last_score * 40)
            print(f"\r mic_peak={peak:5.3f}   raw_score={ww.last_score:4.2f} {bar:<40}",
                  end="", flush=True)
            if fired:
                print(f"\n  >>> WAKE DETECTED\n")
                ww.reset()  # clear model state so it doesn't keep firing on silence
    except KeyboardInterrupt:
        print(f"\n\nStopped. Loudest mic peak while running: {loudest:.3f}")
        if loudest < 0.02:
            print("  -> Mic delivered (near) silence. It's a MIC PERMISSION problem,")
            print("     not the code: this process can't actually hear the microphone.")
        else:
            print("  -> Mic audio is flowing fine.")
    finally:
        stream.stop()
        stream.close()


if __name__ == "__main__":
    main()
