"""Tools-menu entry, sign-in dialog, and status indicator.

All Qt/Anki interaction lives here. Status updates arriving from the bridge
thread are marshalled onto the main thread via mw.taskman.run_on_main before
touching any widget.
"""

from __future__ import annotations

from typing import Optional

from aqt import mw
from aqt.qt import (
    QAction,
    QApplication,
    QDesktopServices,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    Qt,
    QUrl,
    QVBoxLayout,
)
from aqt.utils import showWarning

from . import auth, bridge, protocol

ADDON = __name__.split(".")[0]

_action: Optional[QAction] = None
_connection: Optional[bridge.BridgeConnection] = None
_sign_in_dialog: Optional[QDialog] = None
_status: str = bridge.STATUS_SIGNED_OUT

_STATUS_LABEL = {
    bridge.STATUS_CONNECTING: "Toolforest Bridge: connecting…",
    bridge.STATUS_CONNECTED: "Toolforest Bridge: disconnect",
    bridge.STATUS_RECONNECTING: "Toolforest Bridge: reconnecting…",
    bridge.STATUS_SIGNED_OUT: "Toolforest Bridge: connect",
    bridge.STATUS_DISPLACED: "Toolforest Bridge: connect",
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
        _show_connected_dialog()
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
        mw.taskman.run_on_main(lambda: _show_sign_in_instructions(start))
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
        config["bridge_device_id"] = result.get("device_id")
        mw.addonManager.writeConfig(ADDON, config)
        _close_sign_in_dialog()
        _connect(result["access_token"], config)

    mw.taskman.run_in_background(task, on_done)


def _show_sign_in_instructions(start: dict) -> None:
    global _sign_in_dialog
    uri = start["verification_uri"]
    code = start["user_code"]

    if _sign_in_dialog:
        _sign_in_dialog.close()

    dialog = QDialog(mw)
    _sign_in_dialog = dialog
    dialog.setWindowTitle("Toolforest Bridge — sign in")
    dialog.setMinimumWidth(420)

    layout = QVBoxLayout(dialog)

    instructions = QLabel(
        "To connect Anki to Toolforest:<br><br>"
        f"1. Open <a href=\"{uri}\">{uri}</a><br>"
        "2. Enter this code:"
    )
    instructions.setTextFormat(Qt.TextFormat.RichText)
    instructions.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    instructions.setOpenExternalLinks(False)
    instructions.setWordWrap(True)
    instructions.linkActivated.connect(lambda _url: QDesktopServices.openUrl(QUrl(uri)))
    layout.addWidget(instructions)

    code_field = QLineEdit(code)
    code_field.setReadOnly(True)
    code_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(code_field)

    note = QLabel("Leave Anki open — it will connect automatically once approved.")
    note.setWordWrap(True)
    layout.addWidget(note)

    buttons = QHBoxLayout()
    open_button = QPushButton("Open activation page")
    copy_button = QPushButton("Copy code")
    close_button = QPushButton("Close")
    buttons.addWidget(open_button)
    buttons.addWidget(copy_button)
    buttons.addStretch(1)
    buttons.addWidget(close_button)
    layout.addLayout(buttons)

    open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(uri)))
    copy_button.clicked.connect(lambda: QApplication.clipboard().setText(code))
    close_button.clicked.connect(dialog.close)
    dialog.finished.connect(lambda _result: _clear_sign_in_dialog(dialog))

    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def _show_connected_dialog() -> None:
    message = QMessageBox(mw)
    message.setWindowTitle("Toolforest Bridge")
    message.setIcon(QMessageBox.Icon.Information)
    message.setText(
        "Toolforest Bridge is connected.\n\n"
        "Your Anki collection is reachable from Toolforest while Anki is open. "
        "Use your AI assistant to create and review cards."
    )
    message.setStandardButtons(QMessageBox.StandardButton.Ok)
    disconnect_button = message.addButton("Disconnect", QMessageBox.ButtonRole.DestructiveRole)
    message.exec()
    if message.clickedButton() == disconnect_button:
        _disconnect()


def _clear_sign_in_dialog(dialog: QDialog) -> None:
    global _sign_in_dialog
    if _sign_in_dialog is dialog:
        _sign_in_dialog = None


def _close_sign_in_dialog() -> None:
    if _sign_in_dialog:
        _sign_in_dialog.close()


def _disconnect() -> None:
    global _connection
    config = _config()
    token = config.get("bridge_token")
    api_base = auth.api_base_from_ws(_ws_endpoint(config))
    if _connection:
        _connection.stop()
        _connection = None
    _clear_stored_token()
    _set_status(bridge.STATUS_SIGNED_OUT)
    if token:
        mw.taskman.run_in_background(
            lambda: auth.revoke_self(api_base, token),
            _ignore_background_error,
        )


def _ignore_background_error(future) -> None:
    try:
        future.result()
    except Exception:
        pass


def _clear_stored_token() -> None:
    """Called from the bridge thread when the gateway rejects/revokes the token."""
    def apply() -> None:
        config = _config()
        changed = False
        if "bridge_token" in config:
            config.pop("bridge_token", None)
            changed = True
        if "bridge_device_id" in config:
            config.pop("bridge_device_id", None)
            changed = True
        if changed:
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
    return (
        QMessageBox.question(mw, "Toolforest Bridge", text)
        == QMessageBox.StandardButton.Yes
    )
