"""Lightweight HTTP bridge so the iOS Jarvis Remote app can text Jarvis.

A companion to remote.py (the MQTT bridge): rather than run a mosquitto broker,
this exposes the SAME process_turn() path over a plain HTTP endpoint on the Mac.
The phone reaches it on the LAN, or from anywhere using the Mac's Tailscale IP.

    POST /ask  {"text": "turn on the bedroom light"}  ->  {"ok": true}

The text is run through a full Jarvis turn -- it speaks the reply aloud on the
Mac and performs any action -- exactly like a spoken command. The phone gets an
instant acknowledgement and does not wait for the spoken reply.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("REMOTE_HTTP_PORT", "8765"))
_handler = None  # callable(text) -> reply, set by start()


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/ask":
            self._respond(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except Exception:
            self._respond(400, {"error": "bad json"})
            return
        text = (data.get("text") or "").strip()
        if not text:
            self._respond(400, {"error": "empty text"})
            return
        if _handler is None:
            self._respond(503, {"error": "jarvis not ready"})
            return
        # Run the turn on a worker thread so the phone gets an instant ack while
        # Jarvis thinks and speaks the reply aloud on the Mac. process_turn is
        # already serialized (_TURN_LOCK), so concurrent sends can't interleave.
        threading.Thread(target=_handler, args=(text,), daemon=True).start()
        self._respond(200, {"ok": True})

    def _respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # silence default per-request HTTP logging


def start(handler):
    """Begin serving in the background. ``handler(text)`` runs one Jarvis turn
    (speaks + acts). Returns the server, or None if the port is unavailable."""
    global _handler
    try:
        httpd = HTTPServer(("", PORT), _Handler)
    except OSError as exc:
        print(f"  [remote] HTTP bridge disabled (port {PORT}: {exc}).")
        return None
    _handler = handler
    threading.Thread(target=httpd.serve_forever, name="jarvis-http", daemon=True).start()
    print(f"  [remote] HTTP bridge live on port {PORT} (POST /ask).")
    return httpd
