"""Remote command bridge -- lets the iOS app (JarvisRemote) chat with Jarvis.

Jarvis is otherwise mic-only. This module subscribes to an MQTT topic on a
small broker running on the Mac itself (config.REMOTE_BROKER, default
127.0.0.1) and feeds any text it receives through the SAME ``handle()`` path a
spoken command would take -- so lights, Quran, athan, reminders and the brain
all behave identically. The phone reaches the Mac's broker from anywhere over
Tailscale.

Message protocol (JSON):
    command  (phone -> Jarvis) on REMOTE_CMD_TOPIC:
        {"id": "<uuid>", "text": "turn on the bedroom light", "src": "ios"}
    reply    (Jarvis -> phone) on REMOTE_REPLY_TOPIC:
        {"id": "<same uuid>", "text": "Turning the bedroom light on.", "ts": 1700000000}

Echoing the command's ``id`` back lets the app match a reply to its request.

This broker is SEPARATE from the home-automation broker (config.MQTT_BROKER)
that drives the ESP32 light switches; light control is unchanged.
"""
import json
import socket
import time

import paho.mqtt.client as mqtt

import config


class RemoteBridge:
    """Subscribes to remote commands and runs them through Jarvis.

    Pass a ``process_turn`` callable that takes the command text, runs a full
    Jarvis turn (speak + act), and returns the reply string. The bridge keeps
    no Jarvis state of its own -- it just shuttles text in and replies out.
    """

    def __init__(self, process_turn) -> None:
        self._process_turn = process_turn
        self._client = None
        self.connected = False

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Connect to the local broker and begin listening (non-blocking)."""
        if not config.REMOTE_ENABLED:
            return

        # Fail fast (2s) if the broker isn't up, mirroring LightController, so a
        # missing mosquitto doesn't hang Jarvis startup on a long TCP timeout.
        try:
            socket.create_connection(
                (config.REMOTE_BROKER, config.REMOTE_PORT), timeout=2
            ).close()
        except OSError as exc:
            print(
                f"  [remote] broker {config.REMOTE_BROKER}:{config.REMOTE_PORT} "
                f"unreachable ({exc}); phone app disabled. "
                "Start it with: brew services start mosquitto"
            )
            return

        try:
            try:
                # paho-mqtt 2.x requires an explicit callback API version.
                self._client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=config.REMOTE_CLIENT_ID,
                )
            except (AttributeError, TypeError):
                self._client = mqtt.Client(client_id=config.REMOTE_CLIENT_ID)  # 1.x

            if config.REMOTE_USERNAME:
                self._client.username_pw_set(
                    config.REMOTE_USERNAME, config.REMOTE_PASSWORD
                )
            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message
            self._client.connect(config.REMOTE_BROKER, config.REMOTE_PORT, keepalive=30)
            self._client.loop_start()
            self.connected = True
            print(
                f"  [remote] phone bridge live on {config.REMOTE_BROKER}:"
                f"{config.REMOTE_PORT} (topic '{config.REMOTE_CMD_TOPIC}')."
            )
        except Exception as exc:
            print(f"  [remote] bridge unavailable ({exc}); phone app disabled.")
            self._client = None

    def stop(self) -> None:
        if self._client and self.connected:
            try:
                self._client.disconnect()
                self._client.loop_stop()
            except Exception:
                pass
        self.connected = False

    # -- callbacks ----------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        # (Re)subscribe on every connect so an auto-reconnect re-arms the topic.
        client.subscribe(config.REMOTE_CMD_TOPIC)

    def _on_message(self, client, userdata, msg):
        try:
            cmd_id, text = self._parse(msg.payload)
        except Exception as exc:
            print(f"  [remote] bad command payload ignored ({exc}).")
            return
        if not text:
            return

        print(f"  [remote] command: {text!r}")
        try:
            reply = self._process_turn(text) or ""
        except Exception as exc:
            reply = f"I ran into a problem with that, sir: {exc}"
            print(f"  [remote] turn error: {exc!r}")

        self._publish_reply(cmd_id, reply)

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _parse(payload: bytes):
        """Return (id, text). Accepts a JSON object or a bare text string."""
        raw = payload.decode("utf-8", "replace").strip()
        if raw.startswith("{"):
            data = json.loads(raw)
            return str(data.get("id", "")), (data.get("text") or "").strip()
        return "", raw  # tolerate a plain string (e.g. mosquitto_pub -m "hi")

    def _publish_reply(self, cmd_id: str, text: str) -> None:
        if not (self._client and self.connected):
            return
        payload = json.dumps({"id": cmd_id, "text": text, "ts": int(time.time())})
        try:
            self._client.publish(config.REMOTE_REPLY_TOPIC, payload)
        except Exception as exc:
            print(f"  [remote] could not publish reply ({exc}).")
