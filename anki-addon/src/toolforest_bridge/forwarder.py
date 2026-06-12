"""Forward a bridge request to local AnkiConnect and produce response messages.

Pure Python (stdlib urllib only, no Anki/Qt imports) so it can be unit tested
against a stub HTTP server.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterator, Optional

from . import protocol

_TIMEOUT_MARGIN_S = 1.0


def handle_request(message: dict, ankiconnect_key: Optional[str] = None) -> Iterator[str]:
    """Handle a decoded `request` envelope; yield wire messages to send back."""
    correlation_id = message["correlation_id"]
    body = message.get("body") or {}
    if ankiconnect_key and "key" not in body:
        body["key"] = ankiconnect_key
    timeout_s = max(1.0, message.get("timeout_ms", 15000) / 1000 - _TIMEOUT_MARGIN_S)

    request = urllib.request.Request(
        protocol.ANKICONNECT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
    except urllib.error.URLError as exc:
        yield protocol.error_response(
            correlation_id,
            protocol.ERROR_TARGET_UNAVAILABLE,
            f"AnkiConnect not reachable on 127.0.0.1:8765: {exc.reason}",
        )
        return
    except (json.JSONDecodeError, TimeoutError, OSError) as exc:
        yield protocol.error_response(
            correlation_id,
            protocol.ERROR_TARGET_UNAVAILABLE,
            f"AnkiConnect request failed: {exc}",
        )
        return

    yield from protocol.response_messages(correlation_id, status, payload)
