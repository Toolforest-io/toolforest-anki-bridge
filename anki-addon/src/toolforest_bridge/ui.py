"""Tools-menu entry, sign-in dialog, and status indicator.

All Qt/Anki interaction lives here. Status updates arriving from the bridge
thread are marshalled onto the main thread via mw.taskman.run_on_main before
touching any widget.
"""

from __future__ import annotations

import html
import json
from typing import Optional

from aqt import gui_hooks, mw
from aqt.qt import (
    QAction,
    QApplication,
    QDesktopServices,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
_status_dialog: Optional[QDialog] = None
_toolbar_hook_registered = False
_status: str = bridge.STATUS_SIGNED_OUT

_STATUS_LABEL = {
    bridge.STATUS_CONNECTING: "Toolforest Bridge: connecting…",
    bridge.STATUS_CONNECTED: "Toolforest Bridge: disconnect",
    bridge.STATUS_RECONNECTING: "Toolforest Bridge: reconnecting…",
    bridge.STATUS_SIGNED_OUT: "Toolforest Bridge: connect",
    bridge.STATUS_DISPLACED: "Toolforest Bridge: connect",
}

_STATUS_DISPLAY = {
    bridge.STATUS_CONNECTING: ("Connecting", "#d97706", "Toolforest Bridge is connecting"),
    bridge.STATUS_CONNECTED: ("Connected", "#059669", "Toolforest Bridge is connected"),
    bridge.STATUS_RECONNECTING: (
        "Reconnecting",
        "#d97706",
        "Toolforest Bridge is reconnecting",
    ),
    bridge.STATUS_SIGNED_OUT: ("Signed out", "#6b7280", "Toolforest Bridge is signed out"),
    bridge.STATUS_DISPLACED: (
        "Disconnected",
        "#dc2626",
        "Toolforest Bridge was disconnected by another device",
    ),
}

TOOLFOREST_APP_URL = "https://app.toolforest.io"
TOOLFOREST_DOCS_URL = "https://docs.toolforest.io"
TOOLFOREST_REPO_URL = "https://github.com/Toolforest-io/toolforest-anki-bridge"


def _config() -> dict:
    return mw.addonManager.getConfig(ADDON) or {}


def _ws_endpoint(config: dict) -> str:
    return config.get("endpoint_override") or protocol.DEFAULT_GATEWAY_URL


def setup_menu() -> None:
    global _action, _toolbar_hook_registered
    _action = QAction(_STATUS_LABEL[bridge.STATUS_SIGNED_OUT], mw)
    _action.triggered.connect(show_dialog)
    mw.form.menuTools.addAction(_action)
    if not _toolbar_hook_registered:
        gui_hooks.top_toolbar_did_init_links.append(_add_toolbar_link)
        _toolbar_hook_registered = True
    _redraw_toolbar()


def _set_status(status: str) -> None:
    """Called from the bridge thread; hop to the main thread for the UI."""
    def apply() -> None:
        global _status
        _status = status
        if _action:
            _action.setText(_STATUS_LABEL.get(status, _STATUS_LABEL[bridge.STATUS_SIGNED_OUT]))
        _refresh_status_dialog()
        _redraw_toolbar()
    mw.taskman.run_on_main(apply)


def start_if_configured() -> None:
    """On profile open: if a token is stored, connect."""
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
        on_status=_set_status,
        on_auth_invalid=_clear_stored_token,
    )
    _connection.start()


def show_dialog() -> None:
    _show_status_dialog()


def _sign_in() -> None:
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
        _refresh_status_dialog()
        _close_sign_in_dialog()
        _connect(result["access_token"], config)

    mw.taskman.run_in_background(task, on_done)


def _show_sign_in_instructions(start: dict) -> None:
    global _sign_in_dialog
    uri = start["verification_uri"]
    code = start["user_code"]
    uri_attr = html.escape(uri, quote=True)
    uri_text = html.escape(uri)

    if _sign_in_dialog:
        _sign_in_dialog.close()

    dialog = QDialog(mw)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    _sign_in_dialog = dialog
    dialog.setWindowTitle("Toolforest Bridge — sign in")
    dialog.setMinimumWidth(420)

    layout = QVBoxLayout(dialog)

    instructions = QLabel(
        "To connect Anki to Toolforest:<br><br>"
        f'1. Open <a href="{uri_attr}">{uri_text}</a><br>'
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


def _show_status_dialog() -> None:
    global _status_dialog
    if _status_dialog:
        _refresh_status_dialog()
        _status_dialog.show()
        _status_dialog.raise_()
        _status_dialog.activateWindow()
        return

    dialog = QDialog(mw)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    _status_dialog = dialog
    dialog.setWindowTitle("Toolforest Bridge")
    dialog.setMinimumWidth(520)

    layout = QVBoxLayout(dialog)

    title = QLabel("<b>Toolforest Bridge</b>")
    title.setTextFormat(Qt.TextFormat.RichText)
    layout.addWidget(title)

    summary = QLabel()
    summary.setObjectName("toolforest_summary")
    summary.setTextFormat(Qt.TextFormat.RichText)
    summary.setWordWrap(True)
    layout.addWidget(summary)

    details = QGridLayout()
    details.setColumnStretch(1, 1)
    layout.addLayout(details)
    _add_detail_row(details, 0, "Status", "toolforest_status")
    _add_detail_row(details, 1, "Environment", "toolforest_environment")
    _add_detail_row(details, 2, "Gateway", "toolforest_gateway")
    _add_detail_row(details, 3, "Device", "toolforest_device")
    _add_detail_row(details, 4, "Executor", "toolforest_local_api")

    links = QLabel(
        f'<a href="{TOOLFOREST_APP_URL}">Toolforest app</a>'
        f' · <a href="{TOOLFOREST_DOCS_URL}">Docs</a>'
        f' · <a href="{TOOLFOREST_REPO_URL}">GitHub</a>'
    )
    links.setTextFormat(Qt.TextFormat.RichText)
    links.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    links.setOpenExternalLinks(True)
    layout.addWidget(links)

    buttons = QHBoxLayout()
    connect_button = QPushButton("Connect")
    reconnect_button = QPushButton("Reconnect")
    disconnect_button = QPushButton("Disconnect")
    diagnostics_button = QPushButton("Copy diagnostics")
    close_button = QPushButton("Close")
    connect_button.setObjectName("toolforest_connect")
    reconnect_button.setObjectName("toolforest_reconnect")
    disconnect_button.setObjectName("toolforest_disconnect")
    diagnostics_button.setObjectName("toolforest_diagnostics")
    buttons.addWidget(connect_button)
    buttons.addWidget(reconnect_button)
    buttons.addWidget(disconnect_button)
    buttons.addStretch(1)
    buttons.addWidget(diagnostics_button)
    buttons.addWidget(close_button)
    layout.addLayout(buttons)

    connect_button.clicked.connect(_sign_in)
    reconnect_button.clicked.connect(_reconnect)
    disconnect_button.clicked.connect(_disconnect)
    diagnostics_button.clicked.connect(_copy_diagnostics)
    close_button.clicked.connect(dialog.close)
    dialog.finished.connect(lambda _result: _clear_status_dialog(dialog))

    _refresh_status_dialog()
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def _clear_sign_in_dialog(dialog: QDialog) -> None:
    global _sign_in_dialog
    if _sign_in_dialog is dialog:
        _sign_in_dialog = None


def _clear_status_dialog(dialog: QDialog) -> None:
    global _status_dialog
    if _status_dialog is dialog:
        _status_dialog = None


def _close_sign_in_dialog() -> None:
    if _sign_in_dialog:
        _sign_in_dialog.close()


def _reconnect() -> None:
    config = _config()
    token = config.get("bridge_token")
    if token:
        _connect(token, config)
    else:
        _sign_in()


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
        _refresh_status_dialog()

    mw.taskman.run_on_main(apply)


def _add_toolbar_link(links: list[str], toolbar) -> None:
    status_text, color, tip = _status_display()
    command = f"{ADDON}_status"
    element_id = f"{ADDON}-status"
    toolbar_label = html.escape(_toolbar_label())
    label = html.escape(f"{status_text} - open Toolforest Bridge")
    toolbar.link_handlers[command] = show_dialog
    links.append(
        '<a class=hitem tabindex="-1" '
        f'aria-label="{label}" title="{html.escape(tip)}" id="{element_id}" '
        f"href=# onclick=\"return pycmd('{command}')\">"
        f'<span style="color:{color}; font-weight:700">●</span> {toolbar_label}'
        "</a>"
    )


def _redraw_toolbar() -> None:
    toolbar = getattr(mw, "toolbar", None)
    if toolbar is not None:
        try:
            toolbar.draw()
        except Exception:
            pass


def _refresh_status_dialog() -> None:
    dialog = _status_dialog
    if not dialog:
        return

    status_text, color, _tip = _status_display()
    config = _config()
    endpoint = _ws_endpoint(config)
    environment = _environment_label(endpoint)
    device_id = config.get("bridge_device_id") or "Not registered"
    token_label = "saved" if config.get("bridge_token") else "not saved"
    local_api = "Native Anki API"

    _set_label_html(
        dialog,
        "toolforest_summary",
        f'<span style="color:{color}; font-size:18px">●</span> '
        f"<b>{html.escape(status_text)}</b>",
    )
    _set_label_text(dialog, "toolforest_status", status_text)
    _set_label_text(dialog, "toolforest_environment", environment)
    _set_label_text(dialog, "toolforest_gateway", endpoint)
    _set_label_text(dialog, "toolforest_device", f"{device_id} ({token_label})")
    _set_label_text(dialog, "toolforest_local_api", local_api)

    connect_button = dialog.findChild(QPushButton, "toolforest_connect")
    reconnect_button = dialog.findChild(QPushButton, "toolforest_reconnect")
    disconnect_button = dialog.findChild(QPushButton, "toolforest_disconnect")
    has_token = bool(config.get("bridge_token"))
    is_connected = _status in (
        bridge.STATUS_CONNECTED,
        bridge.STATUS_CONNECTING,
        bridge.STATUS_RECONNECTING,
    )
    if connect_button:
        connect_button.setVisible(not has_token)
    if reconnect_button:
        reconnect_button.setVisible(has_token and not is_connected)
    if disconnect_button:
        disconnect_button.setVisible(has_token)


def _add_detail_row(grid: QGridLayout, row: int, label: str, object_name: str) -> None:
    label_widget = QLabel(f"<b>{html.escape(label)}:</b>")
    label_widget.setTextFormat(Qt.TextFormat.RichText)
    value_widget = QLabel()
    value_widget.setObjectName(object_name)
    value_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    value_widget.setWordWrap(True)
    grid.addWidget(label_widget, row, 0)
    grid.addWidget(value_widget, row, 1)


def _set_label_text(dialog: QDialog, object_name: str, text: str) -> None:
    label = dialog.findChild(QLabel, object_name)
    if label:
        label.setText(text)


def _set_label_html(dialog: QDialog, object_name: str, text: str) -> None:
    label = dialog.findChild(QLabel, object_name)
    if label:
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setText(text)


def _copy_diagnostics() -> None:
    QApplication.clipboard().setText(_diagnostics_text())


def _diagnostics_text() -> str:
    config = _config()
    safe_config = {
        "endpoint_override": config.get("endpoint_override"),
        "bridge_token_saved": bool(config.get("bridge_token")),
        "bridge_device_id": config.get("bridge_device_id"),
    }
    data = {
        "status": _status,
        "environment": _environment_label(_ws_endpoint(config)),
        "gateway": _ws_endpoint(config),
        "executor": "native_anki_api",
        "config": safe_config,
    }
    return json.dumps(data, indent=2, sort_keys=True)


def _status_display() -> tuple[str, str, str]:
    return _STATUS_DISPLAY.get(_status, _STATUS_DISPLAY[bridge.STATUS_SIGNED_OUT])


def _environment_label(endpoint: str) -> str:
    if "bridge-dev." in endpoint or "bridge-dev-" in endpoint:
        return "Development"
    if "bridge-test." in endpoint or "bridge-test-" in endpoint:
        return "Test"
    return "Production"


def _toolbar_label() -> str:
    environment = _environment_label(_ws_endpoint(_config()))
    if environment == "Development":
        return "Toolforest Dev"
    if environment == "Test":
        return "Toolforest Test"
    return "Toolforest"


def _device_name() -> str:
    import platform

    return f"Anki on {platform.node() or platform.system()}"[:64]
