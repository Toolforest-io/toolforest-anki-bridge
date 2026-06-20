import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolforest_bridge import forwarder, protocol  # noqa: E402


def test_executes_native_action_and_wraps_response(monkeypatch):
    captured = {}

    def fake_handle(body, timeout_s):
        captured["body"] = body
        captured["timeout_s"] = timeout_s
        return {"result": ["Default", "Japanese"], "error": None}

    monkeypatch.setattr(forwarder.native_actions, "handle", fake_handle)
    message = {
        "type": "request",
        "correlation_id": "c1",
        "body": {"action": "deckNames", "version": 6},
        "timeout_ms": 5000,
    }

    replies = list(forwarder.handle_request(message))

    assert len(replies) == 1
    envelope = json.loads(replies[0])
    assert captured["body"] == {"action": "deckNames", "version": 6}
    assert captured["timeout_s"] == 4.0
    assert envelope["type"] == protocol.TYPE_RESPONSE
    assert envelope["status"] == 200
    assert envelope["body"] == {"result": ["Default", "Japanese"], "error": None}


def test_native_timeout_has_one_second_floor(monkeypatch):
    captured = {}

    def fake_handle(_body, timeout_s):
        captured["timeout_s"] = timeout_s
        return {"result": "ok", "error": None}

    monkeypatch.setattr(forwarder.native_actions, "handle", fake_handle)
    message = {
        "type": "request",
        "correlation_id": "c2",
        "body": {"action": "sync"},
        "timeout_ms": 500,
    }

    list(forwarder.handle_request(message))

    assert captured["timeout_s"] == 1.0


def test_native_action_returns_anki_style_error(monkeypatch):
    def fake_handle(_body, timeout_s):
        raise ValueError("model is still in use")

    monkeypatch.setattr(forwarder.native_actions, "handle", fake_handle)
    message = {
        "type": "request",
        "correlation_id": "c3",
        "body": {"action": "toolforestDeleteModel", "params": {"modelName": "Basic"}},
        "timeout_ms": 2000,
    }

    replies = list(forwarder.handle_request(message))

    envelope = json.loads(replies[0])
    assert envelope["status"] == 200
    assert envelope["body"] == {"result": None, "error": "model is still in use"}


def test_unsupported_action_is_reported_by_native_executor(monkeypatch):
    def fake_handle(body, timeout_s):
        return {"result": None, "error": f"unsupported action: {body.get('action')}"}

    monkeypatch.setattr(forwarder.native_actions, "handle", fake_handle)
    message = {
        "type": "request",
        "correlation_id": "c4",
        "body": {"action": "unknownAction"},
    }

    replies = list(forwarder.handle_request(message))

    envelope = json.loads(replies[0])
    assert envelope["status"] == 200
    assert envelope["body"] == {"result": None, "error": "unsupported action: unknownAction"}
