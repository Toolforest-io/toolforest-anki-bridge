import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolforest_bridge import bridge  # noqa: E402
from toolforest_bridge.vendor import websocket  # noqa: E402


def _conn():
    return bridge.BridgeConnection(
        ws_endpoint="wss://bridge-dev.toolforest.io", token="tok", agent_version="0.1.0"
    )


def _conn_with_auth_callback(callback):
    return bridge.BridgeConnection(
        ws_endpoint="wss://bridge-dev.toolforest.io",
        token="tok",
        agent_version="0.1.0",
        on_auth_invalid=callback,
    )


def test_displaced_message_sets_flags_and_closes():
    conn = _conn()
    app = MagicMock()
    conn._on_message(app, json.dumps({"v": 1, "type": "displaced"}))
    assert conn._displaced.is_set()
    assert conn._stop.is_set()
    app.close.assert_called_once()


def test_revoked_message_stops_reconnect_clears_auth_and_closes():
    on_auth_invalid = MagicMock()
    conn = _conn_with_auth_callback(on_auth_invalid)
    app = MagicMock()
    conn._on_message(app, json.dumps({"v": 1, "type": "revoked"}))
    assert conn._stop.is_set()
    on_auth_invalid.assert_called_once()
    app.close.assert_called_once()


def test_request_message_forwards_and_replies(monkeypatch):
    conn = _conn()
    app = MagicMock()

    def fake_handle_request(message, key):
        assert message["correlation_id"] == "c1"
        yield json.dumps({"type": "response", "correlation_id": "c1", "status": 200, "body": {}})

    monkeypatch.setattr(bridge.forwarder, "handle_request", fake_handle_request)
    conn._on_message(
        app,
        json.dumps(
            {"v": 1, "type": "request", "correlation_id": "c1", "body": {"action": "deckNames"}}
        ),
    )
    app.send.assert_called_once()
    sent = json.loads(app.send.call_args[0][0])
    assert sent["correlation_id"] == "c1"


def test_revoked_close_code_stops_reconnect():
    on_auth_invalid = MagicMock()
    conn = _conn_with_auth_callback(on_auth_invalid)
    conn._on_close(MagicMock(), 4401, "unauthorized")
    assert conn._stop.is_set()
    on_auth_invalid.assert_called_once()


def test_handshake_401_stops_reconnect_and_clears_auth():
    on_auth_invalid = MagicMock()
    conn = _conn_with_auth_callback(on_auth_invalid)
    conn._on_error(
        MagicMock(),
        websocket.WebSocketBadStatusException("unauthorized", status_code=401),
    )
    assert conn._stop.is_set()
    on_auth_invalid.assert_called_once()


def test_normal_close_does_not_stop():
    conn = _conn()
    conn._on_close(MagicMock(), 1006, "abnormal")
    assert not conn._stop.is_set()


def test_malformed_message_is_ignored():
    conn = _conn()
    conn._on_message(MagicMock(), "not json")  # should not raise
