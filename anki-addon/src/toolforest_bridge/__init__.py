"""Toolforest Bridge: connects local AnkiConnect to the Toolforest gateway.

Anki entry point. Everything Qt/Anki-specific is imported lazily so the pure
protocol/forwarding modules stay importable (and testable) outside Anki.
"""

try:
    import aqt  # noqa: F401
except ImportError:
    _IN_ANKI = False
else:
    _IN_ANKI = True

if _IN_ANKI:
    from aqt import gui_hooks, mw

    from . import ui

    def _on_profile_open() -> None:
        ui.setup_menu()
        # M2: start the bridge connection thread if a token is configured.

    def _on_profile_close() -> None:
        # M2: clean shutdown of the bridge connection thread.
        pass

    gui_hooks.profile_did_open.append(_on_profile_open)
    gui_hooks.profile_will_close.append(_on_profile_close)
    mw.addonManager.setConfigAction(__name__, lambda: ui.show_dialog())
