#!/usr/bin/env python3
"""Jarvis -- a hands-free bedroom voice assistant. It controls the light and
answers any question, with live tools for weather, web search, and time.

Modes:
    python jarvis.py            # hands-free: always listening, wakes on "Jarvis"
    python jarvis.py --push     # push-to-talk: press Enter, then speak
    python jarvis.py --text     # type instead of speaking (no mic needed)
    python jarvis.py --selftest # check routing + config + brain, no audio

Hands-free flow:
    mic -> VAD (captures a whole utterance, ending when you stop talking)
        -> Whisper -> if it heard the wake word "Jarvis", run the command
        -> speak the reply. After replying it stays awake briefly so you can
           follow up without saying "Jarvis" again.
"""
import re
import sys
import time

import config
import audio
from brain import Brain
from home_control import LightController, detect_light_command

_WAKE_RE = re.compile(r"\b(?:hey\s+)?(jarvis|jarvus|jervis|jarviss|jarvi)\b", re.I)


def handle(text, brain, lights, speak=True):
    """Route one utterance and (optionally) speak the reply."""
    text = text.strip()
    if not text:
        return None
    command = detect_light_command(text)
    reply = lights.set_light(command) if command else brain.ask(text)
    if speak:
        audio.speak(reply)
    return reply


def _has_wake(text):
    return bool(_WAKE_RE.search(text))


def _strip_wake(text):
    """Remove the wake word, leaving just the command."""
    out = _WAKE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", out).strip(" ,.:;!?-").strip()


# -- hands-free wake-word mode ----------------------------------------------
def _make_detector():
    """Load the openWakeWord engine, or None to fall back to transcription wake."""
    if not config.USE_OPENWAKEWORD:
        return None
    try:
        from wakeword import WakeWord
        return WakeWord()
    except Exception as exc:
        print(f"  [wake] openWakeWord unavailable ({exc}).")
        print("        Falling back to transcription-based wake word.")
        return None


def _ask_followup(listener):
    """User said only the wake word -> prompt and capture the next utterance."""
    audio.speak("Yes?")
    time.sleep(0.3)
    listener.flush()
    return audio.transcribe(listener.listen_utterance())


def _transcription_wake(listener):
    """Fallback wake: transcribe each utterance, returning a command only if it
    contained the wake word. (Less efficient -- transcribes ambient audio.)"""
    while True:
        clip = listener.listen_utterance()
        if clip.size < int(0.25 * config.SAMPLE_RATE):
            continue
        text = audio.transcribe(clip)
        if not text:
            continue
        if _has_wake(text):
            return _strip_wake(text) or _ask_followup(listener)
        print(f"  (ignored) {text!r}")


def wake_loop(brain, lights):
    from listener import Listener

    audio.prepare()
    listener = None
    for attempt in range(1, 20):  # retry for up to ~3 min
        try:
            listener = Listener().start()
            break
        except Exception as exc:
            print(f"  [mic] attempt {attempt}: {exc}. Retrying in 10s...")
            time.sleep(10)
    if listener is None:
        print("  [mic] Could not open microphone after retries.")
        print("        Grant access: System Settings > Privacy & Security > Microphone")
        return

    detector = _make_detector()
    phrase = f"Hey {config.ASSISTANT_NAME}" if detector else config.WAKE_WORD
    print(f'\n{config.ASSISTANT_NAME} is listening. Say "{phrase}". Ctrl-C to quit.\n')
    audio.speak(f"{config.ASSISTANT_NAME} standing by.")
    listener.flush()
    try:
        while True:
            if detector is not None:
                listener.wait_for_wake(detector)  # local, cheap; ignores other audio
                audio.chime()
                time.sleep(0.4)   # let "Hey Jarvis" tail clear before listening
                listener.flush()
                command = audio.transcribe(
                    listener.listen_utterance(start_timeout_sec=config.COMMAND_TIMEOUT_SEC)
                )
                detector.reset()
            else:
                command = _transcription_wake(listener)

            if not command:
                continue
            print(f"  You: {command}")
            reply = handle(command, brain, lights)
            print(f"  {config.ASSISTANT_NAME}: {reply}\n")
            time.sleep(0.3)   # let the spoken reply echo decay before listening again
            listener.flush()  # drop our own TTS that the mic may have caught
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        listener.stop()


# -- push-to-talk mode ------------------------------------------------------
def voice_loop(brain, lights):
    audio.prepare()
    print(f"\n{config.ASSISTANT_NAME} (push-to-talk). Press Enter and speak, Ctrl-C to quit.\n")
    audio.speak(f"{config.ASSISTANT_NAME} online.")
    while True:
        try:
            input("[ Press Enter to speak ] ")
            print(f"  recording {config.RECORD_SECONDS:.0f}s... ", end="", flush=True)
            clip = audio.record()
            print("transcribing...")
            text = audio.transcribe(clip)
            if not text:
                print("  (heard nothing)\n")
                continue
            print(f"  You: {text}")
            reply = handle(text, brain, lights)
            print(f"  {config.ASSISTANT_NAME}: {reply}\n")
        except (KeyboardInterrupt, EOFError):
            break


# -- text mode --------------------------------------------------------------
def text_loop(brain, lights):
    print(f"\n{config.ASSISTANT_NAME} (text mode). Type a question or a command "
          "like 'turn off the light'. Ctrl-C to quit.\n")
    while True:
        try:
            text = input("You: ")
            reply = handle(text, brain, lights, speak=True)
            if reply:
                print(f"{config.ASSISTANT_NAME}: {reply}\n")
        except (KeyboardInterrupt, EOFError):
            break


def selftest():
    """Verify routing and config without touching audio hardware or network."""
    cases = {
        "turn on the light": "ON",
        "turn the lights off please": "OFF",
        "light on": "ON",
        "lights out": "OFF",
        "what is the capital of France": None,
        "what's the weather like": None,
        "tell me a joke": None,
        "what is a light year": None,
    }
    print("Routing self-test:")
    ok = True
    for text, expected in cases.items():
        got = detect_light_command(text)
        if got != expected:
            ok = False
        print(f"  [{'OK ' if got == expected else 'FAIL'}] {text!r:42} -> {got or 'brain'}")

    # wake-word matching sanity check
    print("\nWake-word self-test:")
    for text, should in [("jarvis what's the weather", True),
                         ("turn off the light", False),
                         ("hey Jarvis, lights out", True)]:
        got = _has_wake(text)
        if got != should:
            ok = False
        print(f"  [{'OK ' if got == should else 'FAIL'}] {text!r:34} wake={got}")

    print(f"\nConfig: provider={config.LLM_PROVIDER}  wake={config.WAKE_WORD!r}  "
          f"broker={config.MQTT_BROKER}  voice={config.TTS_VOICE}")
    brain = Brain()
    status = "ready" if brain.ready else f"not ready ({brain.error})"
    print(f"Brain:  provider={brain.provider}, {status}")
    print("\n" + ("All checks passed." if ok else "Some checks FAILED."))
    sys.exit(0 if ok else 1)


def main():
    if "--selftest" in sys.argv:
        selftest()

    if "--text" in sys.argv or "-t" in sys.argv:
        _run_once(text_loop)
    elif "--push" in sys.argv:
        _run_once(voice_loop)
    else:
        # Default hands-free mode is self-healing, for autonomous background use:
        # any unexpected crash is logged and the loop restarts after a pause.
        while True:
            try:
                _run_once(wake_loop)
                break  # clean exit (Ctrl-C)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                print(f"  [fatal] {exc!r} -- restarting in 5s...", flush=True)
                time.sleep(5)
    print(f"\n{config.ASSISTANT_NAME} offline. Goodbye.")


def _run_once(loop):
    brain = Brain()
    lights = LightController()
    if not brain.ready:
        print(f"  [warn] Brain offline: {brain.error}.")
    try:
        loop(brain, lights)
    finally:
        lights.close()


if __name__ == "__main__":
    main()
