"""Home control -- turns the bedroom light on/off over MQTT.

Also decides whether a spoken sentence is a *light command* (handled locally
and instantly, even with no internet) or a general question (which the caller
forwards to the Gemini brain).
"""
import re
import socket

import paho.mqtt.client as mqtt

import config

# Words that indicate the sentence is about the light.
_LIGHT_WORDS = ("light", "lights", "lamp")
# Fixed phrases that always mean "off", even without a light word.
_OFF_ALIASES = ("lights out", "kill the lights", "go dark")


def detect_light_command(text: str):
    """Classify a transcript.

    Returns ``"ON"``, ``"OFF"``, or ``None`` (meaning: not a light command,
    so it should go to the brain instead).
    """
    t = text.lower().strip()

    if any(alias in t for alias in _OFF_ALIASES):
        return "OFF"

    # Only treat it as a light command if a light word is present. This keeps
    # general questions ("what is a light year?") from flipping the switch by
    # accident, while still catching "turn the lights off", "light on", etc.
    if not any(word in t for word in _LIGHT_WORDS):
        return None

    if re.search(r"\boff\b", t):
        return "OFF"
    if re.search(r"\bon\b", t):
        return "ON"
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

    def set_light(self, state: str) -> str:
        """Publish ``state`` ('ON'/'OFF') and return a spoken confirmation."""
        if not self.connected:
            return "I can't reach the light right now -- the home hub looks offline."
        self._client.publish(config.LIGHT_TOPIC, state)
        return f"Turning the bedroom light {state.lower()}."

    def close(self) -> None:
        if self._client and self.connected:
            try:
                self._client.disconnect()  # stops the loop cleanly first
                self._client.loop_stop()
            except Exception:
                pass
