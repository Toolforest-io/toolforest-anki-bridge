import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolforest_bridge import native_actions  # noqa: E402


class _Models:
    def __init__(self, model=None, use_count=0):
        self._model = model
        self._use_count = use_count
        self.removed = []

    def by_name(self, name):
        if self._model and self._model["name"] == name:
            return self._model
        return None

    def use_count(self, model):
        assert model == self._model
        return self._use_count

    def remove(self, model_id):
        self.removed.append(model_id)


class _Collection:
    def __init__(self, models, decks=None, sched=None):
        self.models = models
        self.decks = decks
        self.sched = sched
        self.removed_notes = []

    def remove_notes(self, note_ids):
        self.removed_notes.extend(note_ids)
        return object()


class _Sched:
    def __init__(self):
        self.set_due_date_calls = []

    def set_due_date(self, card_ids, days, config_key=None):
        self.set_due_date_calls.append((card_ids, days, config_key))
        return object()


class _Decks:
    def __init__(self):
        self._decks = {"Default": 1, "Scratch": 2}
        self.removed = []

    def all_names_and_ids(self):
        return [SimpleNamespace(name=name) for name in self._decks]

    def id(self, name):
        return self._decks[name]

    def remove(self, deck_ids):
        self.removed.extend(deck_ids)


def test_delete_model_removes_unused_model():
    models = _Models(model={"id": 123, "name": "Scratch"}, use_count=0)
    mw = MagicMock()

    result = native_actions.delete_model(
        {"modelName": "Scratch", "confirm": True}, collection=_Collection(models), mw=mw
    )

    assert result == {"model": "Scratch", "model_id": 123, "deleted": True}
    assert models.removed == [123]
    mw.reset.assert_called_once()


def test_delete_model_rejects_missing_model():
    models = _Models(model=None)

    with pytest.raises(ValueError, match="model was not found"):
        native_actions.delete_model(
            {"modelName": "Scratch", "confirm": True},
            collection=_Collection(models),
            mw=MagicMock(),
        )


def test_delete_model_rejects_model_in_use():
    models = _Models(model={"id": 123, "name": "Basic"}, use_count=2)

    with pytest.raises(ValueError, match="model is still in use"):
        native_actions.delete_model(
            {"modelName": "Basic", "confirm": True},
            collection=_Collection(models),
            mw=MagicMock(),
        )

    assert models.removed == []


def test_delete_model_requires_confirm():
    models = _Models(model={"id": 123, "name": "Basic"}, use_count=0)

    with pytest.raises(ValueError, match="confirm=true is required"):
        native_actions.delete_model(
            {"modelName": "Basic"}, collection=_Collection(models), mw=MagicMock()
        )


def test_delete_model_requires_model_name():
    models = _Models(model={"id": 123, "name": "Basic"}, use_count=0)

    with pytest.raises(ValueError, match="modelName is required"):
        native_actions.delete_model(
            {"confirm": True}, collection=_Collection(models), mw=MagicMock()
        )


def test_can_handle_supported_native_actions():
    assert native_actions.can_handle({"action": "deckNames"})
    assert native_actions.can_handle({"action": "addNote"})
    assert native_actions.can_handle({"action": native_actions.DELETE_MODEL_ACTION})
    assert not native_actions.can_handle({"action": "unknownAction"})


def test_handle_dispatches_through_anki_context(monkeypatch):
    seen = {}
    collection = _Collection(models=_Models(), decks=_Decks())

    def fake_run_in_anki(callback, timeout_s):
        seen["timeout_s"] = timeout_s
        return callback(collection, None)

    monkeypatch.setattr(native_actions, "_run_in_anki", fake_run_in_anki)

    out = native_actions.handle(
        {"action": "deckNames"},
        timeout_s=12.5,
    )

    assert out == {"result": ["Default", "Scratch"], "error": None}
    assert seen["timeout_s"] == 12.5


def test_handle_returns_unsupported_action_error():
    assert native_actions.handle({"action": "unknownAction"}) == {
        "result": None,
        "error": "unsupported action: unknownAction",
    }


def test_delete_decks_requires_cards_too():
    with pytest.raises(ValueError, match="cardsToo=true is required"):
        native_actions.execute_action(
            "deleteDecks",
            {"decks": ["Scratch"]},
            _Collection(models=_Models(), decks=_Decks()),
        )


def test_delete_decks_removes_existing_decks_only():
    decks = _Decks()

    result = native_actions.execute_action(
        "deleteDecks",
        {"decks": ["Scratch", "Missing"], "cardsToo": True},
        _Collection(models=_Models(), decks=decks),
    )

    assert result is None
    assert decks.removed == [2]


def test_create_model_rejects_duplicate_field_names_before_anki_import():
    with pytest.raises(ValueError, match="duplicate field name"):
        native_actions.execute_action(
            "createModel",
            {
                "modelName": "Duplicate Fields",
                "inOrderFields": ["Front", "front"],
                "cardTemplates": [{"Front": "{{Front}}", "Back": "{{Back}}"}],
            },
            _Collection(models=_Models()),
        )


def test_delete_notes_returns_serializable_null_result():
    collection = _Collection(models=_Models())

    result = native_actions.execute_action(
        "deleteNotes",
        {"notes": ["10", 11]},
        collection,
    )

    assert result is None
    assert collection.removed_notes == [10, 11]


def test_set_due_date_returns_serializable_null_result():
    sched = _Sched()

    result = native_actions.execute_action(
        "setDueDate",
        {"cards": ["20", 21], "days": "3"},
        _Collection(models=_Models(), sched=sched),
    )

    assert result is None
    assert sched.set_due_date_calls == [([20, 21], "3", None)]


def test_delete_model_timeout_warns_operation_may_complete(monkeypatch):
    mw = SimpleNamespace(
        taskman=SimpleNamespace(run_on_main=lambda _callback: None),
    )
    monkeypatch.setattr(
        native_actions,
        "_current_anki_context",
        lambda: (object(), mw),
    )
    monkeypatch.setattr(native_actions.threading, "current_thread", lambda: object())

    with pytest.raises(TimeoutError, match="may still complete"):
        native_actions.delete_model(
            {"modelName": "Scratch", "confirm": True},
            timeout_s=0,
        )
