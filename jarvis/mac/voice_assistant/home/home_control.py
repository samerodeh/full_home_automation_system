"""Home control -- turns room lights on/off over MQTT.

Detects which room from the spoken phrase ("door lights on" -> front door,
"bedroom light off" -> bedroom) and publishes to that room's ESP32. Also decides
whether a sentence is a *light command* (handled locally and instantly, even with
no internet) or a general question (which the caller forwards to the brain).
"""
import re
import socket

import paho.mqtt.client as mqtt

import config

# Words that indicate the sentence is about the light.
_LIGHT_WORDS = ("light", "lights", "lamp")
# Fixed phrases that always mean "all lights off", even without a room word.
_OFF_ALIASES = ("lights out", "kill the lights", "go dark")
# Fixed phrases that always mean "all lights on".
_ON_ALIASES = ("lights on",)

# Rooms with active ESP32 switches wired up. "all" broadcasts to every room
# in this list. Add a room here when you flash a new board.
# (kitchen removed -- not wired yet)
ACTIVE_ROOMS = ("bedroom", "front_door", "desk")

# Spoken room names -> the room key used in the MQTT topic. Checked in order.
# "door lights on" -> front_door, "bedroom lights off" -> bedroom.
# If no room phrase is found the command is treated as "all rooms".
_ROOM_PHRASES = (
    ("front_door", ("front door", "door")),
    ("bedroom", ("bedroom", "bed room")),
    ("living_room", ("living room", "livingroom", "living-room", "lounge")),
    ("desk", ("desk", "desk light", "desk lights")),
)


def _detect_room(text: str):
    """Return the matched room key, or None if no room was mentioned (= all rooms)."""
    for room, phrases in _ROOM_PHRASES:
        if any(p in text for p in phrases):
            return room
    return None


# The last room we acted on, so bare follow-up directives ("off", "turn it on")
# apply to whatever you just controlled. Defaults to the configured room.
_last_room = config.DEFAULT_LIGHT_ROOM

# Bare on/off directives that carry NO light noun -- a follow-up to a previous
# light command ("bedroom lights on" ... then just "off"). The whole utterance
# must be the directive (anchored) so we don't fire on "what's going on".
_BARE_OFF = re.compile(
    r"^(?:please\s+|okay\s+|ok\s+|yeah\s+)?"
    r"(?:(?:turn|switch|shut|put|kill)\s+)?"
    r"(?:(?:it|that|them|those|these|the\s+lights?|everything)\s+)?"
    r"(?:off|out)"
    r"(?:\s+now|\s+please)?$"
)
_BARE_ON = re.compile(
    r"^(?:please\s+|okay\s+|ok\s+|yeah\s+)?"
    r"(?:(?:turn|switch|put)\s+)?"
    r"(?:(?:it|that|them|those|these|the\s+lights?|everything)\s+)?"
    r"on"
    r"(?:\s+now|\s+please)?$"
)


def detect_light_command(text: str):
    """Classify a transcript.

    Returns ``(room_or_"all", "ON"|"OFF")`` for a light command, or ``None``
    if it isn't one (caller forwards to the brain). room="all" means every
    active room -- triggered when you say "lights on/off" with no room.

    Bare follow-up directives with no light word ("off", "turn it on now") are
    recognized too, and applied to the last room acted on, so a conversation
    like "bedroom lights on" ... "off" works without repeating the room.

    Examples:
        "lights off"           -> ("all",  "OFF")   all rooms
        "bedroom lights on"    -> ("bedroom", "ON")
        "bedrooom lights on"   -> ("bedroom", "ON")  (collapses the typo)
        "door lights off"      -> ("front_door", "OFF")
        "off" (after bedroom)  -> ("bedroom", "OFF")
        "what is a light year" -> None
    """
    global _last_room
    t = re.sub(r"[.!?,]+$", "", text.lower().strip()).strip()
    # Collapse stretched/typo'd letters ("bedrooom"->"bedroom", "offf"->"off")
    # so a doubled key still resolves; legit double letters (oo) are preserved.
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)

    # All-lights aliases: only fire when NO specific room phrase is in the text,
    # so "door lights on" doesn't match the "lights on" all-alias.
    if not _detect_room(t):
        if any(alias in t for alias in _OFF_ALIASES):
            _last_room = "all"
            return ("all", "OFF")
        if any(alias in t for alias in _ON_ALIASES):
            _last_room = "all"
            return ("all", "ON")

    # An explicit light command needs a light word ("turn the bedroom light off").
    if any(word in t for word in _LIGHT_WORDS):
        if re.search(r"\b(off|out)\b", t):
            state = "OFF"
        elif re.search(r"\bon\b", t):
            state = "ON"
        else:
            return None  # "what is a light year" -- no on/off, not a command
        room = _detect_room(t) or "all"
        _last_room = room
        return (room, state)

    # No light word -- maybe a bare follow-up directive aimed at the last room.
    if _BARE_OFF.match(t):
        return (_last_room, "OFF")
    if _BARE_ON.match(t):
        return (_last_room, "ON")
    return None


class LightController:
    """Publishes ON/OFF to the ESP32 light switch over MQTT."""

    def __init__(self) -> None:
        self._client = None
        self.connected = False

        # Fail fast (2s) if the broker isn't reachable, rather than letting a
        # blocking connect() hang startup for the full TCP timeout (~75s).
        try:
            socket.create_connection(
                (config.MQTT_BROKER, config.MQTT_PORT), timeout=2
            ).close()
        except OSError as exc:
            print(
                f"  [home] MQTT broker {config.MQTT_BROKER}:{config.MQTT_PORT} "
                f"unreachable ({exc}); light control disabled."
            )
            return

        try:
            try:
                # paho-mqtt 2.x requires an explicit callback API version.
                self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            except (AttributeError, TypeError):
                # paho-mqtt 1.x
                self._client = mqtt.Client()
            self._client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=30)
            self._client.loop_start()
            self.connected = True
        except Exception as exc:
            print(f"  [home] MQTT unavailable ({exc}); light control disabled.")

    def light_reply(self, room: str, state: str) -> str:
        """Return the spoken confirmation text without touching MQTT."""
        if not self.connected:
            return "I can't reach the lights right now -- the home hub looks offline."
        if room == "all":
            return f"Turning all lights {state.lower()}."
        where = room.replace("_", " ")  # front_door -> "front door"
        return f"Turning the {where} light {state.lower()}."

    def publish(self, room: str, state: str) -> None:
        """Send the MQTT command (call this AFTER speaking the reply)."""
        if not self.connected:
            return
        if room == "all":
            for r in ACTIVE_ROOMS:
                self._client.publish(config.LIGHT_TOPIC_TEMPLATE.format(room=r), state)
        else:
            self._client.publish(config.LIGHT_TOPIC_TEMPLATE.format(room=room), state)

    def set_light(self, room: str, state: str) -> str:
        """Publish ``state`` ('ON'/'OFF') to ``room``'s switch (or all active
        rooms when room='all'). Returns a spoken confirmation."""
        reply = self.light_reply(room, state)
        self.publish(room, state)
        return reply

    def close(self) -> None:
        if self._client and self.connected:
            try:
                self._client.disconnect()  # stops the loop cleanly first
                self._client.loop_stop()
            except Exception:
                pass
