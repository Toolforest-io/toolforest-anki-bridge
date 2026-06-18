import json
import socket
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


def _run_stub():
    server = HTTPServer(("127.0.0.1", 0), _StubAnkiConnect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _set_ankiconnect_url(monkeypatch, server):
    monkeypatch.setattr(protocol, "ANKICONNECT_URL", f"http://127.0.0.1:{server.server_port}")


def _unused_ankiconnect_url():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()
    return f"http://{host}:{port}"


def test_forwards_to_ankiconnect_and_wraps_response(monkeypatch):
    server = _run_stub()
    _set_ankiconnect_url(monkeypatch, server)
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


def test_target_unavailable_when_ankiconnect_down(monkeypatch):
    # Nothing is listening on this reserved test port.
    monkeypatch.setattr(protocol, "ANKICONNECT_URL", _unused_ankiconnect_url())
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


def test_injects_ankiconnect_key_when_configured(monkeypatch):
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

    server = HTTPServer(("127.0.0.1", 0), _KeyChecker)
    _set_ankiconnect_url(monkeypatch, server)
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


def test_bridge_native_action_does_not_call_ankiconnect(monkeypatch):
    captured = {}

    def fake_handle(body, timeout_s):
        captured["body"] = body
        captured["timeout_s"] = timeout_s
        return {"result": {"deleted": True}, "error": None}

    monkeypatch.setattr(forwarder.native_actions, "handle", fake_handle)
    message = {
        "type": "request",
        "correlation_id": "c4",
        "body": {"action": "toolforestDeleteModel", "params": {"modelName": "Scratch"}},
        "timeout_ms": 2000,
    }

    replies = list(forwarder.handle_request(message))

    envelope = json.loads(replies[0])
    assert captured["body"]["action"] == "toolforestDeleteModel"
    assert captured["timeout_s"] == 1.0
    assert envelope["status"] == 200
    assert envelope["body"] == {"result": {"deleted": True}, "error": None}


def test_bridge_native_action_returns_ankiconnect_style_error(monkeypatch):
    def fake_handle(_body, timeout_s):
        raise ValueError("model is still in use")

    monkeypatch.setattr(forwarder.native_actions, "handle", fake_handle)
    message = {
        "type": "request",
        "correlation_id": "c5",
        "body": {"action": "toolforestDeleteModel", "params": {"modelName": "Basic"}},
        "timeout_ms": 2000,
    }

    replies = list(forwarder.handle_request(message))

    envelope = json.loads(replies[0])
    assert envelope["status"] == 200
    assert envelope["body"] == {"result": None, "error": "model is still in use"}
