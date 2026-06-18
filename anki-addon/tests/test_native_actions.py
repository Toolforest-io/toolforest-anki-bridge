import sys
from pathlib import Path
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
    def __init__(self, models):
        self.models = models


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


def test_handle_dispatches_delete_model(monkeypatch):
    seen = {}

    def fake_delete_model(params, timeout_s):
        seen["timeout_s"] = timeout_s
        return {"model": params["modelName"], "model_id": 1, "deleted": True}

    monkeypatch.setattr(
        native_actions,
        "delete_model",
        fake_delete_model,
    )

    out = native_actions.handle(
        {"action": native_actions.DELETE_MODEL_ACTION, "params": {"modelName": "Scratch"}},
        timeout_s=12.5,
    )

    assert out == {"result": {"model": "Scratch", "model_id": 1, "deleted": True}, "error": None}
    assert seen["timeout_s"] == 12.5
