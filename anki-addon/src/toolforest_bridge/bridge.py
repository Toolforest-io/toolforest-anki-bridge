"""Background WebSocket connection to the Toolforest bridge gateway.

Runs a daemon thread holding a single outbound WSS connection. On each
`request` message it executes the requested action through Anki's in-process
APIs and replies (chunking large responses). Reconnects with backoff, pings to
beat the idle timeout, and stops cleanly on quit, revocation, or displacement
by another device.

No Anki/Qt imports — the caller passes an on_status callback and is responsible
for marshalling it onto the main thread.
"""

from __future__ import annotations

import json
import threading
from typing import Callable, Optional

from . import forwarder, protocol
from .vendor import websocket

# Status strings the UI maps to menu text / indicator.
STATUS_CONNECTING = "connecting"
STATUS_CONNECTED = "connected"
STATUS_SIGNED_OUT = "signed_out"
STATUS_DISPLACED = "displaced"
STATUS_RECONNECTING = "reconnecting"

PING_INTERVAL_S = 300  # beat API Gateway's 10-minute idle timeout
PING_TIMEOUT_S = 10


class BridgeConnection:
    def __init__(
        self,
        ws_endpoint: str,
        token: str,
        agent_version: str = "0.1.0",
        on_status: Optional[Callable[[str], None]] = None,
        on_auth_invalid: Optional[Callable[[], None]] = None,
    ) -> None:
        self._ws_endpoint = ws_endpoint
        self._token = token
        self._agent_version = agent_version
        self._on_status = on_status or (lambda status: None)
        self._on_auth_invalid = on_auth_invalid or (lambda: None)

        self._thread: Optional[threading.Thread] = None
        self._app: Optional[websocket.WebSocketApp] = None
        self._stop = threading.Event()
        # Set when the gateway tells us another device took over: we must NOT
        # reconnect (otherwise two machines fight over the single slot).
        self._displaced = threading.Event()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._displaced.clear()
        self._thread = threading.Thread(target=self._run, name="toolforest-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._app:
            try:
                self._app.close()
            except Exception:
                pass

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- worker --------------------------------------------------------------

    def _run(self) -> None:
        header = [
            f"Authorization: Bearer {self._token}",
            f"X-Bridge-Protocol-Version: {protocol.PROTOCOL_VERSION}",
            f"X-Bridge-Agent-Version: {self._agent_version}",
            # The gateway still routes this capability by its historical name.
            "X-Bridge-Capability: ankiconnect",
        ]
        backoff = 1
        while not self._stop.is_set() and not self._displaced.is_set():
            self._on_status(STATUS_CONNECTING)
            self._app = websocket.WebSocketApp(
                self._ws_endpoint,
                header=header,
                on_open=self._on_open,
                on_message=self._on_message,
                on_close=self._on_close,
                on_error=self._on_error,
            )
            self._app.run_forever(ping_interval=PING_INTERVAL_S, ping_timeout=PING_TIMEOUT_S)

            if self._stop.is_set() or self._displaced.is_set():
                break
            # Unexpected drop — reconnect with capped exponential backoff.
            self._on_status(STATUS_RECONNECTING)
            self._stop.wait(timeout=backoff)
            backoff = min(backoff * 2, 30)

        if self._displaced.is_set():
            self._on_status(STATUS_DISPLACED)
        else:
            self._on_status(STATUS_SIGNED_OUT)

    # -- WebSocketApp callbacks ---------------------------------------------

    def _on_open(self, _app) -> None:
        self._on_status(STATUS_CONNECTED)

    def _on_message(self, app, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        message_type = message.get("type")

        if message_type == protocol.TYPE_REQUEST:
            for reply in forwarder.handle_request(message):
                app.send(reply)
        elif message_type == protocol.TYPE_DISPLACED:
            # Another device signed in for this capability. Give up the slot;
            # the user reconnects manually from the menu.
            self._displaced.set()
            self._stop.set()
            try:
                app.close()
            except Exception:
                pass
        elif message_type == protocol.TYPE_REVOKED:
            self._auth_invalid()
            try:
                app.close()
            except Exception:
                pass

    def _on_close(self, _app, status_code, _msg) -> None:
        # 4401 is our gateway's "token revoked/unauthorized" close code.
        if status_code in (4401, 1008):
            self._auth_invalid()

    def _on_error(self, _app, error) -> None:
        if isinstance(error, websocket.WebSocketBadStatusException) and error.status_code == 401:
            self._auth_invalid()
        # run_forever returns after this; the _run loop decides whether to
        # reconnect based on the stop/displaced flags.
        pass

    def _auth_invalid(self) -> None:
        self._stop.set()
        self._on_auth_invalid()
