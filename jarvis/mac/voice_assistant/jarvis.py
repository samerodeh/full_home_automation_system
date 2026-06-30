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
import datetime
import os
import re
import sys
import time
import threading

import config
from audio import audio
from reminders import reminders
import tools as _tools
from audio import volume as _volume
from media import quran_player as _quran
from media import athan as _athan
from remote import remote as _remote
from remote import server as _server
from brain import Brain
from home.home_control import LightController, detect_light_command

_WAKE_RE = re.compile(r"\b(?:hey\s+)?(jarvis|jarvus|jervis|jarviss|jarvi)\b", re.I)

# Set at local midnight by the watcher thread; the hands-free loop notices it,
# tears down cleanly, and main() re-execs a fresh process for the new day.
_RESTART = threading.Event()

# Serializes a full conversation turn (route -> speak -> act). The mic loop and
# the remote phone bridge both run turns; without this they could interleave and
# corrupt shared state (brain history, the single deferred-action slot in tools).
_TURN_LOCK = threading.Lock()

# --- transcript colors ------------------------------------------------------
# ANSI codes applied to the printed conversation: your input and Jarvis's
# replies each get their own color (config.USER_COLOR / config.ASSISTANT_COLOR).
_ANSI = {
    "black": "30", "red": "31", "green": "32", "yellow": "33", "blue": "34",
    "magenta": "35", "cyan": "36", "white": "37", "default": "39",
    "gray": "90", "grey": "90", "bright_red": "91", "bright_green": "92",
    "bright_yellow": "93", "bright_blue": "94",
}
_RESET = "\033[0m"


def _start(color):
    """ANSI escape that *begins* a color (no reset), or '' if disabled/unknown.
    Used for the input() prompt so the typed text inherits the color too."""
    code = _ANSI.get(color) if config.USE_COLOR else None
    return f"\033[{code}m" if code else ""


def _paint(text, color):
    """Wrap a complete printed line in a color (begin + reset)."""
    start = _start(color)
    return f"{start}{text}{_RESET}" if start else text


def _ts():
    """Gray timestamp prefix: '[HH:MM:SS | Month D, YYYY]  '"""
    now = datetime.datetime.now()
    stamp = now.strftime("%H:%M:%S | %B %-d, %Y")
    return _paint(f"[{stamp}]", "gray") + "  "


def _speak_and_act(reply, listener=None):
    """Speak a reply and run any deferred action, respecting Quran playback.

    Normal (no Quran): speak FIRST → then act.
    Quran playing: act FIRST → then speak (out of respect).

    When a listener is supplied, speech is interruptible: saying 'stop'
    kills the TTS mid-sentence. Deferred actions are skipped if interrupted.
    """
    action = _tools.pop_pending()
    if _quran._P.playing:
        if action:
            action()
        audio.speak(reply)
    else:
        if listener is not None:
            interrupted = audio.speak_interruptible(reply, listener)
        else:
            audio.speak(reply)
            interrupted = False
        if not interrupted and action:
            action()


def process_turn(text, brain, lights, listener=None):
    """Run one full turn: route the text, print + speak the reply, and perform
    any deferred physical action. Returns the reply string (or None).

    This is the single entry point shared by the mic loops and the remote phone
    bridge. _TURN_LOCK keeps the two from interleaving -- they share the brain's
    rolling history and the one-slot deferred action in tools, so a concurrent
    turn would cross wires (e.g. the wrong light firing after the wrong reply)."""
    with _TURN_LOCK:
        reply = handle(text, brain, lights)
        if reply:
            print(_ts() + _paint(f"  {config.ASSISTANT_NAME}: {reply}",
                                 config.ASSISTANT_COLOR) + "\n")
            _speak_and_act(reply, listener)
        return reply


def handle(text, brain, lights):
    """Route one utterance to the lights or the brain and return the reply text.

    Speaking is the caller's job, so the reply can be printed the instant it's
    ready and then spoken. Physical side-effects (MQTT, Quran audio) are
    registered as a deferred action via tools.defer(); the caller must call
    tools.pop_pending() after speak() so the action fires AFTER confirmation."""
    text = text.strip()
    if not text:
        return None
    command = detect_light_command(text)
    if command:
        room, state = command
        reply = lights.light_reply(room, state)
        # Defer the actual MQTT publish so the servo fires AFTER Jarvis speaks.
        if lights.connected:
            _tools.defer(lambda r=room, s=state: lights.publish(r, s))
        # Record it in the brain's memory so a follow-up like "off" has context.
        brain.remember(text, reply)
        return reply

    vol = _volume.detect(text)
    if vol:
        reply, action = vol
        # Volume is the exception to "speak then act": change it NOW, before the
        # confirmation is spoken, so you hear the reply at the new level.
        action()
        return reply

    athan_cmd = _athan.detect_command(text)
    if athan_cmd:
        reply, prayer = athan_cmd
        # Play athan in a background thread so the main loop stays responsive.
        # The athan module's _playing flag keeps audio.speak() silent during it.
        import threading
        threading.Thread(
            target=_athan.play, args=(prayer,), daemon=True,
        ).start()
        return reply

    # Listing / clearing reminders is handled locally so it works instantly and
    # even when the cloud brain is rate-limited. (Setting a new reminder, or
    # cancelling a specific one, returns None here and falls through to the brain.)
    rem_cmd = reminders.detect_command(text)
    if rem_cmd:
        reply, action = rem_cmd
        if action:
            _tools.defer(action)
        return reply

    return brain.ask(text)


def _has_wake(text):
    return bool(_WAKE_RE.search(text))


def _strip_wake(text):
    """Remove the wake word, leaving just the command."""
    out = _WAKE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", out).strip(" ,.:;!?-").strip()


# -- reminders --------------------------------------------------------------
# Acknowledgment phrases meaning "I've handled this, stop nagging." Kept clear
# of the words audio.transcribe() filters as Whisper hallucinations ("ok",
# "thanks", "yes", "bye") so an ack actually registers.
_ACK_WORDS = ("done", "got it", "i did it", "i've done it", "i did", "finished",
              "complete", "completed", "handled", "taken care", "all done",
              "acknowledge", "dismiss", "stop reminding")


def _is_ack(text):
    t = _strip_wake(text).lower().strip(" .!?,")
    return any(w in t for w in _ACK_WORDS)


def _announce_due_reminders(listener):
    """Speak one due reminder and briefly listen for the user to say 'done'.
    Returns True if a reminder was announced (so the caller can reset the wake
    detector). Re-nags happen on later ticks until acknowledged."""
    due = reminders.due_to_announce()
    if not due:
        return False
    r = due[0]  # one per tick, so several due at once don't stack into a barrage
    # Mark announced FIRST (with the current time) so the hourly gate prevents
    # any re-fire while we're still speaking / listening for the ack reply.
    reminders.mark_announced(r["id"])
    name = config.ASSISTANT_NAME
    print(_ts() + _paint(f"  {name} (reminder): {r['text']}", config.ASSISTANT_COLOR))
    audio.speak(f"Reminder, sir: {r['text']}. Say done when you've taken care of it.")
    time.sleep(0.3)
    listener.flush()  # drop our own announcement before listening for the reply
    # Listen for up to 8 seconds; transcribe only if something was captured.
    clip = listener.listen_utterance(start_timeout_sec=8)
    reply = audio.transcribe(clip) if clip.size else ""
    if reply and _is_ack(reply):
        rec = r.get("recurrence")
        reminders.acknowledge(r["id"])
        print(_ts() + _paint(f"  You: {reply}", config.USER_COLOR))
        if rec:
            label = reminders.recurrence_label(rec)
            audio.speak(f"Done, sir. I'll remind you again {label}.")
        else:
            audio.speak("Done, sir. I won't remind you about that again.")
    elif reply:
        # User said something but it wasn't an ack -- print it so they can see
        # what was heard, but don't acknowledge.
        print(_ts() + _paint(f"  You: {reply}", config.USER_COLOR))
    listener.flush()
    return True


# -- hands-free wake-word mode ----------------------------------------------
def _make_detector():
    """Load the openWakeWord engine, or None to fall back to transcription wake."""
    if not config.USE_OPENWAKEWORD:
        return None
    try:
        from audio.wakeword import WakeWord
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


def _schedule_midnight_restart():
    """Sleep until the next local midnight, then raise the restart flag.

    Runs as a daemon thread. A daily restart gives Jarvis a clean slate: it
    resets the played-athan set, the rolling conversation history, and any slow
    mic/MQTT resource drift from being up for days. Sleeps in short chunks so a
    laptop sleep/wake or clock change can't overshoot the target by hours."""
    now = datetime.datetime.now()
    target = datetime.datetime.combine(
        (now + datetime.timedelta(days=1)).date(), datetime.time.min)
    while datetime.datetime.now() < target:
        remaining = (target - datetime.datetime.now()).total_seconds()
        time.sleep(min(300, max(1, remaining)))
    _RESTART.set()


def _keyboard_loop(brain, lights):
    """Read typed commands from this terminal and run them, so you can text
    Jarvis instead of (or alongside) speaking. Runs as a daemon thread; only
    started when stdin is an interactive TTY (under the LaunchAgent there's no
    keyboard, so it never starts). Typed turns go through the same thread-safe
    process_turn() as voice, so they can't collide with a spoken command."""
    while not _RESTART.is_set():
        try:
            text = input().strip()
        except (EOFError, KeyboardInterrupt):
            return  # stdin closed (e.g. piped/early exit) -- stop reading
        if not text:
            continue
        print(_ts() + _paint(f"  You (typed): {text}", config.USER_COLOR))
        process_turn(text, brain, lights)


def wake_loop(brain, lights):
    from audio.listener import Listener

    audio.prepare()
    listener = None
    for attempt in range(1, 20):  # retry for up to ~3 min
        try:
            listener = Listener().start()
            break
        except Exception as exc:
            print(f"  [mic] attempt {attempt}: {exc}. Retrying in 10s...")
            try:  # the mic may have appeared after PortAudio initialized; refresh its device list
                import sounddevice as sd
                sd._terminate()
                sd._initialize()
            except Exception:
                pass
            time.sleep(10)
    if listener is None:
        print("  [mic] Could not open microphone after retries.")
        print("        Grant access: System Settings > Privacy & Security > Microphone")
        return

    detector = _make_detector()
    phrase = f"Hey {config.ASSISTANT_NAME}" if detector else config.WAKE_WORD
    print(f'\n{config.ASSISTANT_NAME} is listening. Say "{phrase}". Ctrl-C to quit.')
    # Let the user type commands in this terminal too -- handy when you'd rather
    # text than speak. Only when stdin is interactive (no TTY = LaunchAgent).
    if sys.stdin and sys.stdin.isatty():
        print("  (or just type a command here and press Enter)")
        threading.Thread(target=_keyboard_loop, args=(brain, lights),
                         name="keyboard-input", daemon=True).start()
    print()
    audio.speak(f"{config.ASSISTANT_NAME} standing by.")
    listener.flush()

    # Restart the whole process at midnight for a daily clean slate.
    threading.Thread(target=_schedule_midnight_restart,
                     name="midnight-restart", daemon=True).start()

    # Recalibrate the VAD noise floor every 30 min. If the room gets noisier
    # (AC, fan, TV) after startup, the baseline drifts up over hours and speech
    # detection gets harder. A periodic recalibration resets it to the current
    # room noise so the threshold stays accurate all day.
    _RECAL_SEC = 30 * 60
    _last_recal = time.time()

    try:
        while True:
            # Midnight restart: exit the loop so main() can re-exec a fresh
            # process. Never cut off a playing athan -- wait for the next pass.
            if _RESTART.is_set() and not _athan.is_playing():
                break
            if detector is not None:
                # Wait for the wake word, but wake up periodically to nag any due
                # reminders and recalibrate VAD, then go back to listening.
                woke = listener.wait_for_wake(detector, timeout_sec=config.REMINDER_CHECK_SEC)
                now = time.time()
                if now - _last_recal >= _RECAL_SEC:
                    listener._calibrate()
                    _last_recal = now
                if not woke:
                    if _announce_due_reminders(listener):
                        detector.reset()
                    continue
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

            # -- conversation turn --
            # After Jarvis answers, stay awake for FOLLOWUP_SEC seconds so the
            # user can keep talking without repeating "Hey Jarvis". If they
            # stay silent the whole window, fall back to wake-word mode.
            while command:
                print(_ts() + _paint(f"  You: {command}", config.USER_COLOR))
                process_turn(command, brain, lights, listener)
                time.sleep(0.3)
                listener.flush()  # drop our own TTS echo before listening

                if not config.FOLLOWUP_SEC:
                    break  # follow-up disabled -> always go back to wake word

                # Listen for a follow-up within the window. listen_utterance
                # with start_timeout_sec returns empty audio if silence the
                # whole time, which is our signal to return to wake-word mode.
                print(_ts() + f"  (listening for follow-up… {config.FOLLOWUP_SEC:.0f}s)")
                followup_clip = listener.listen_utterance(
                    start_timeout_sec=config.FOLLOWUP_SEC
                )
                command = audio.transcribe(followup_clip) if followup_clip.size else ""
                if not command:
                    print(_ts() + "  (back to wake-word mode)")
                    if detector is not None:
                        detector.reset()
                    break  # silence -> exit follow-up loop, return to "Hey Jarvis"
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
            print(_ts() + _paint(f"  You: {text}", config.USER_COLOR))
            process_turn(text, brain, lights)
        except (KeyboardInterrupt, EOFError):
            break


# -- text mode --------------------------------------------------------------
def text_loop(brain, lights):
    print(f"\n{config.ASSISTANT_NAME} (text mode). Type a question or a command "
          "like 'turn off the light'. Ctrl-C to quit.\n")
    while True:
        try:
            prompt_color = _start(config.USER_COLOR)
            text = input(prompt_color + "You: ")  # typed text inherits the color...
            if prompt_color:
                sys.stdout.write(_RESET)          # ...reset once they hit Enter
                sys.stdout.flush()
            process_turn(text, brain, lights)
        except (KeyboardInterrupt, EOFError):
            break


def selftest():
    """Verify routing and config without touching audio hardware or network."""
    cases = {
        # no room specified -> all
        "lights on": ("all", "ON"),
        "lights off": ("all", "OFF"),
        "lights out": ("all", "OFF"),
        "turn the lights off please": ("all", "OFF"),
        "kill the lights": ("all", "OFF"),
        # room-specific
        "bedroom lights on": ("bedroom", "ON"),
        "turn on the bedroom light": ("bedroom", "ON"),
        "door lights on": ("front_door", "ON"),
        "door lights off": ("front_door", "OFF"),
        "living room lights off": ("living_room", "OFF"),
        # must NOT trigger lights
        "what is the capital of France": None,
        "what's the weather like": None,
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
            except KeyboardInterrupt:
                break
            except Exception as exc:
                print(f"  [fatal] {exc!r} -- restarting in 5s...", flush=True)
                time.sleep(5)
                continue
            # Clean return: at midnight, re-exec a fresh interpreter (the loop
            # has already released the mic + MQTT). Otherwise it's a real quit.
            if _RESTART.is_set():
                print(_ts() + "  [restart] Midnight -- restarting Jarvis fresh.", flush=True)
                sys.stdout.flush()
                script = os.path.abspath(sys.argv[0])
                os.execv(sys.executable, [sys.executable, script] + sys.argv[1:])
            break  # clean exit (Ctrl-C)
    print(f"\n{config.ASSISTANT_NAME} offline. Goodbye.")


def _run_once(loop):
    brain = Brain()
    lights = LightController()
    _tools.set_light_controller(lights)  # let the brain actuate lights via set_light
    if not brain.ready:
        print(f"  [warn] Brain offline: {brain.error}.")
    # Start the athan background checker -- fires at each prayer time,
    # interrupts everything, and plays the full adhan.
    athan_stop = threading.Event()
    _athan.start(athan_stop)
    # Start the remote phone bridges -- both feed the iOS app's text through the
    # same process_turn() (speak + act) a spoken command takes. MQTT (remote.py)
    # is broker-based; HTTP (server.py, POST /ask on :8765) needs no broker and
    # is what the JarvisRemote app talks to over the LAN or Tailscale.
    bridge = _remote.RemoteBridge(
        process_turn=lambda t: process_turn(t, brain, lights)
    )
    bridge.start()
    http_bridge = None
    if config.REMOTE_ENABLED:
        http_bridge = _server.start(lambda t: process_turn(t, brain, lights))
    try:
        loop(brain, lights)
    finally:
        bridge.stop()      # stop the remote MQTT bridge
        if http_bridge:
            http_bridge.shutdown()  # stop the remote HTTP bridge
        athan_stop.set()   # stop the athan checker thread cleanly
        lights.close()


if __name__ == "__main__":
    main()
