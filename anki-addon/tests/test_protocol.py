import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolforest_bridge import protocol  # noqa: E402


def reassemble(messages: list[str]):
    """Reverse of response_messages, mirroring what the gateway does."""
    decoded = [json.loads(m) for m in messages]
    if len(decoded) == 1 and decoded[0]["type"] == protocol.TYPE_RESPONSE:
        return decoded[0]["body"]
    assert all(d["type"] == protocol.TYPE_RESPONSE_PART for d in decoded)
    assert [d["part_index"] for d in decoded] == list(range(decoded[0]["part_count"]))
    raw = b"".join(base64.b64decode(d["body_b64"]) for d in decoded)
    return json.loads(raw.decode("utf-8"))


def test_small_body_single_message():
    body = {"result": ["Default"], "error": None}
    messages = list(protocol.response_messages("c1", 200, body))
    assert len(messages) == 1
    envelope = json.loads(messages[0])
    assert envelope["type"] == protocol.TYPE_RESPONSE
    assert envelope["v"] == protocol.PROTOCOL_VERSION
    assert envelope["correlation_id"] == "c1"
    assert envelope["body"] == body


def test_large_body_chunks_and_reassembles():
    body = {"result": [{"note": i, "text": "x" * 100} for i in range(2000)], "error": None}
    messages = list(protocol.response_messages("c2", 200, body))
    assert len(messages) > 1
    for message in messages:
        assert len(message.encode("utf-8")) < 32 * 1024
    assert reassemble(messages) == body


def test_large_multibyte_body_survives_chunk_boundaries():
    body = {"result": "日本語テキスト🎴" * 5000, "error": None}
    messages = list(protocol.response_messages("c3", 200, body))
    assert len(messages) > 1
    assert reassemble(messages) == body


def test_error_response_shape():
    envelope = json.loads(
        protocol.error_response("c4", protocol.ERROR_TARGET_UNAVAILABLE, "refused")
    )
    assert envelope["status"] == 0
    assert envelope["error"] == protocol.ERROR_TARGET_UNAVAILABLE
