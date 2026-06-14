"""Tools-menu entry, sign-in dialog, and status indicator.

All Qt/Anki interaction lives here. Status updates arriving from the bridge
thread are marshalled onto the main thread via mw.taskman.run_on_main before
touching any widget.
"""

from __future__ import annotations

from typing import Optional

from aqt import mw
from aqt.qt import QAction
from aqt.utils import showInfo, showWarning

from . import auth, bridge, protocol

ADDON = __name__.split(".")[0]

_action: Optional[QAction] = None
_connection: Optional[bridge.BridgeConnection] = None
_status: str = bridge.STATUS_SIGNED_OUT

_STATUS_LABEL = {
    bridge.STATUS_CONNECTING: "Toolforest Bridge: connecting…",
    bridge.STATUS_CONNECTED: "Toolforest Bridge: connected ✓",
    bridge.STATUS_RECONNECTING: "Toolforest Bridge: reconnecting…",
    bridge.STATUS_SIGNED_OUT: "Toolforest Bridge: sign in…",
    bridge.STATUS_DISPLACED: "Toolforest Bridge: connected on another device",
}


def _config() -> dict:
    return mw.addonManager.getConfig(ADDON) or {}


def _ws_endpoint(config: dict) -> str:
    return config.get("endpoint_override") or protocol.DEFAULT_GATEWAY_URL


def setup_menu() -> None:
    global _action
    _action = QAction(_STATUS_LABEL[bridge.STATUS_SIGNED_OUT], mw)
    _action.triggered.connect(show_dialog)
    mw.form.menuTools.addAction(_action)


def _set_status(status: str) -> None:
    """Called from the bridge thread; hop to the main thread for the UI."""
    def apply() -> None:
        global _status
        _status = status
        if _action:
            _action.setText(_STATUS_LABEL.get(status, _STATUS_LABEL[bridge.STATUS_SIGNED_OUT]))
    mw.taskman.run_on_main(apply)


def start_if_configured() -> None:
    """On profile open: if AnkiConnect is present and a token is stored, connect."""
    if not _ankiconnect_available():
        if _action:
            _action.setText("Toolforest Bridge: AnkiConnect missing (code 2055492159)")
        return
    config = _config()
    token = config.get("bridge_token")
    if token:
        _connect(token, config)


def shutdown() -> None:
    if _connection:
        _connection.stop()


def _connect(token: str, config: dict) -> None:
    global _connection
    if _connection and _connection.is_running():
        _connection.stop()
    _connection = bridge.BridgeConnection(
        ws_endpoint=_ws_endpoint(config),
        token=token,
        ankiconnect_key=config.get("ankiconnect_key"),
        on_status=_set_status,
        on_auth_invalid=_clear_stored_token,
    )
    _connection.start()


def show_dialog() -> None:
    if _status in (bridge.STATUS_CONNECTED, bridge.STATUS_CONNECTING, bridge.STATUS_RECONNECTING):
        showInfo(
            "Toolforest Bridge is connected.\n\n"
            "Your Anki collection is reachable from Toolforest while Anki is open. "
            "Use your AI assistant to create and review cards.",
            title="Toolforest Bridge",
        )
        return
    if _status == bridge.STATUS_DISPLACED:
        if _ask("This account is connected through Anki on another device. Connect here instead?"):
            config = _config()
            token = config.get("bridge_token")
            if token:
                _connect(token, config)
        return
    _sign_in()


def _sign_in() -> None:
    if not _ankiconnect_available():
        showWarning(
            "AnkiConnect isn't installed. Install it first (Tools → Add-ons → "
            "Get Add-ons… → code 2055492159), restart Anki, then sign in.",
            title="Toolforest Bridge",
        )
        return

    config = _config()
    api_base = auth.api_base_from_ws(_ws_endpoint(config))

    def task() -> dict:
        start = auth.start_device_flow(api_base, device_name=_device_name())
        # Show the code to the user on the main thread.
        mw.taskman.run_on_main(
            lambda: showInfo(
                f"To connect Anki to Toolforest:\n\n"
                f"1. Open {start['verification_uri']}\n"
                f"2. Enter this code:  {start['user_code']}\n\n"
                f"Leave Anki open — it will connect automatically once approved.",
                title="Toolforest Bridge — sign in",
            )
        )
        return auth.poll_for_token(
            api_base,
            start["device_code"],
            interval=start.get("interval", 5),
            expires_in=start.get("expires_in", 600),
        )

    def on_done(future) -> None:
        try:
            result = future.result()
        except auth.DeviceFlowError as exc:
            if str(exc) != "cancelled":
                showWarning(f"Sign-in didn't complete: {exc}", title="Toolforest Bridge")
            return
        config = _config()
        config["bridge_token"] = result["access_token"]
        mw.addonManager.writeConfig(ADDON, config)
        _connect(result["access_token"], config)

    mw.taskman.run_in_background(task, on_done)


def _clear_stored_token() -> None:
    """Called from the bridge thread when the gateway rejects/revokes the token."""
    def apply() -> None:
        config = _config()
        if "bridge_token" in config:
            config.pop("bridge_token", None)
            mw.addonManager.writeConfig(ADDON, config)

    mw.taskman.run_on_main(apply)


def _device_name() -> str:
    import platform

    return f"Anki on {platform.node() or platform.system()}"[:64]


def _ankiconnect_available() -> bool:
    """AnkiConnect installs into the same Anki process; detect it by add-on dir
    presence rather than a network probe (fast, no event-loop interaction)."""
    for module in mw.addonManager.allAddons():
        if module == "2055492159" or "ankiconnect" in module.lower():
            return True
    return False


def _ask(text: str) -> bool:
    from aqt.qt import QMessageBox

    return (
        QMessageBox.question(mw, "Toolforest Bridge", text)
        == QMessageBox.StandardButton.Yes
    )
