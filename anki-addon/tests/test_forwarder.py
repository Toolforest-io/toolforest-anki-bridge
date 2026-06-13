import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolforest_bridge import forwarder, protocol  # noqa: E402


class _StubAnkiConnect(BaseHTTPRequestHandler):
    """Minimal AnkiConnect stand-in: echoes a canned result per action."""

    responses = {"deckNames": {"result": ["Default", "日本語"], "error": None}}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length))
        body = self.responses.get(request.get("action"), {"result": None, "error": None})
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def _run_stub_on_8765():
    server = HTTPServer(("127.0.0.1", 8765), _StubAnkiConnect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_forwards_to_ankiconnect_and_wraps_response():
    server = _run_stub_on_8765()
    try:
        message = {
            "type": "request",
            "correlation_id": "c1",
            "body": {"action": "deckNames", "version": 6},
            "timeout_ms": 5000,
        }
        replies = list(forwarder.handle_request(message))
        assert len(replies) == 1
        envelope = json.loads(replies[0])
        assert envelope["type"] == protocol.TYPE_RESPONSE
        assert envelope["status"] == 200
        assert envelope["body"]["result"] == ["Default", "日本語"]
    finally:
        server.shutdown()


def test_target_unavailable_when_ankiconnect_down():
    # nothing listening on 8765
    message = {
        "type": "request",
        "correlation_id": "c2",
        "body": {"action": "deckNames"},
        "timeout_ms": 2000,
    }
    replies = list(forwarder.handle_request(message))
    envelope = json.loads(replies[0])
    assert envelope["status"] == 0
    assert envelope["error"] == protocol.ERROR_TARGET_UNAVAILABLE


def test_injects_ankiconnect_key_when_configured():
    captured = {}

    class _KeyChecker(_StubAnkiConnect):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            captured.update(json.loads(self.rfile.read(length)))
            payload = json.dumps({"result": "ok", "error": None}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 8765), _KeyChecker)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        message = {
            "type": "request",
            "correlation_id": "c3",
            "body": {"action": "sync"},
            "timeout_ms": 2000,
        }
        list(forwarder.handle_request(message, ankiconnect_key="secret-key"))
        assert captured["key"] == "secret-key"
    finally:
        server.shutdown()
