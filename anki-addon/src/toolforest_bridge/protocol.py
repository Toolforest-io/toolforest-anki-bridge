"""Bridge wire protocol: envelope construction and response chunking.

Protocol v1. The gateway speaks the same envelope; this module is the add-on-side
source of truth and is pure Python (no Anki/Qt imports) so it can be unit tested.

API Gateway WebSocket enforces 128 KB per message but 32 KB per *frame* on
client->server traffic, and websocket-client sends one frame per send() call —
so any response larger than the chunk threshold must be split into
`response_part` messages and reassembled by the gateway. Parts carry base64 so
chunk boundaries can never split a UTF-8 character or JSON token.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Iterator

PROTOCOL_VERSION = 1

# Local forwarding target. Deliberately a constant, not configuration: the server
# must never be able to point the bridge at an arbitrary local port.
ANKICONNECT_URL = "http://127.0.0.1:8765"

DEFAULT_GATEWAY_URL = "wss://bridge.toolforest.io"
DEFAULT_API_URL = "https://bridge-api.toolforest.io"

# Per-part base64 payload size. 20 KB raw -> ~27 KB base64 + envelope overhead,
# safely under API Gateway's 32 KB inbound frame cap.
PART_RAW_BYTES = 20 * 1024

# A response whose serialized body fits in one frame alongside its envelope is
# sent unchunked.
SINGLE_MESSAGE_LIMIT_BYTES = 28 * 1024

# Message types
TYPE_REQUEST = "request"
TYPE_RESPONSE = "response"
TYPE_RESPONSE_PART = "response_part"
TYPE_DISPLACED = "displaced"
TYPE_REVOKED = "revoked"
TYPE_PING = "ping"

# Error codes reported in response envelopes
ERROR_TARGET_UNAVAILABLE = "TARGET_UNAVAILABLE"


def ping() -> str:
    return json.dumps({"v": PROTOCOL_VERSION, "type": TYPE_PING})


def error_response(correlation_id: str, error: str, detail: str) -> str:
    return json.dumps(
        {
            "v": PROTOCOL_VERSION,
            "type": TYPE_RESPONSE,
            "correlation_id": correlation_id,
            "status": 0,
            "error": error,
            "detail": detail,
        }
    )


def response_messages(correlation_id: str, status: int, body: Any) -> Iterator[str]:
    """Yield one `response` message, or several `response_part` messages when the
    serialized body is too large for a single WebSocket frame."""
    body_bytes = json.dumps(body).encode("utf-8")
    if len(body_bytes) <= SINGLE_MESSAGE_LIMIT_BYTES:
        yield json.dumps(
            {
                "v": PROTOCOL_VERSION,
                "type": TYPE_RESPONSE,
                "correlation_id": correlation_id,
                "status": status,
                "body": body,
            }
        )
        return

    parts = [
        body_bytes[i : i + PART_RAW_BYTES] for i in range(0, len(body_bytes), PART_RAW_BYTES)
    ]
    for index, part in enumerate(parts):
        yield json.dumps(
            {
                "v": PROTOCOL_VERSION,
                "type": TYPE_RESPONSE_PART,
                "correlation_id": correlation_id,
                "status": status,
                "part_index": index,
                "part_count": len(parts),
                "body_b64": base64.b64encode(part).decode("ascii"),
            }
        )
