"""Execute a bridge request through the native Anki action shim."""

from __future__ import annotations

from typing import Iterator

from . import native_actions, protocol

_TIMEOUT_MARGIN_S = 1.0


def handle_request(message: dict) -> Iterator[str]:
    """Handle a decoded `request` envelope; yield wire messages to send back."""
    correlation_id = message["correlation_id"]
    body = message.get("body") or {}
    timeout_s = max(1.0, message.get("timeout_ms", 15000) / 1000 - _TIMEOUT_MARGIN_S)
    try:
        payload = native_actions.handle(body, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001 - keep response shape stable across failures
        payload = {"result": None, "error": str(exc)}

    yield from protocol.response_messages(correlation_id, 200, payload)
