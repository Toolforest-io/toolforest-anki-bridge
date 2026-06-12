"""Tools-menu entry, sign-in dialog, and status indicator. M2 scope.

All Qt interaction lives here; never call into Qt from the bridge thread —
status updates must go through mw.taskman.run_on_main.
"""

from aqt import mw
from aqt.qt import QAction
from aqt.utils import showInfo

_MENU_TEXT = "Toolforest Bridge…"


def setup_menu() -> None:
    action = QAction(_MENU_TEXT, mw)
    action.triggered.connect(show_dialog)
    mw.form.menuTools.addAction(action)


def show_dialog() -> None:
    # M2: full dialog — sign-in via device flow, connection status
    # (Connected / Signed out / AnkiConnect missing with install code 2055492159),
    # and sign-out.
    showInfo("Toolforest Bridge is under development. See github.com/Toolforest-io/toolforest-anki-bridge")
