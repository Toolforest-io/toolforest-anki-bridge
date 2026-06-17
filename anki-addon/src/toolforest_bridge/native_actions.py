"""Bridge-native actions that cannot be expressed through AnkiConnect.

These handlers run inside Anki, but avoid importing Anki/Qt modules at import
time so protocol and forwarder tests can run in a normal Python process.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Optional


DELETE_MODEL_ACTION = "toolforestDeleteModel"
_NATIVE_ACTION_TIMEOUT_S = 30


@dataclass
class _DeleteModelOpResult:
    payload: dict
    changes: Any


def can_handle(body: dict) -> bool:
    return body.get("action") == DELETE_MODEL_ACTION


def handle(body: dict) -> dict:
    action = body.get("action")
    params = body.get("params") or {}
    if action == DELETE_MODEL_ACTION:
        return {"result": delete_model(params), "error": None}
    return {"result": None, "error": f"unsupported bridge-native action: {action}"}


def _current_anki_context() -> tuple[Any, Any]:
    try:
        import aqt  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Anki runtime is not available") from exc

    collection = getattr(getattr(aqt, "mw", None), "col", None)
    if collection is None:
        raise RuntimeError("Anki collection is not available")
    return collection, aqt.mw


def _notetype_id(model_id: int) -> Any:
    try:
        from anki.models import NotetypeId  # type: ignore
    except ImportError:
        return model_id
    return NotetypeId(model_id)


def _delete_model_from_collection(params: dict, collection: Any) -> _DeleteModelOpResult:
    if params.get("confirm") is not True:
        raise ValueError("confirm=true is required")

    model_name = params.get("modelName") or params.get("model")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("modelName is required")

    models = collection.models
    model = models.by_name(model_name)
    if model is None:
        raise ValueError(f"model was not found: {model_name}")

    use_count = int(models.use_count(model))
    if use_count:
        raise ValueError(
            f"model is still in use: {model_name} has {use_count} note(s); "
            "delete or move those notes first."
        )

    model_id = int(model["id"])
    changes = models.remove(_notetype_id(model_id))
    return _DeleteModelOpResult(
        payload={"model": model_name, "model_id": model_id, "deleted": True},
        changes=changes,
    )


def _delete_model_in_anki(params: dict) -> dict:
    _collection, mw = _current_anki_context()
    done = threading.Event()
    outcome: dict[str, Any] = {}

    def finish(result: Optional[_DeleteModelOpResult] = None, error: Optional[Exception] = None) -> None:
        if error is not None:
            outcome["error"] = error
        elif result is not None:
            outcome["result"] = result.payload
        done.set()

    def start_op() -> None:
        try:
            from aqt.operations import CollectionOp  # type: ignore

            CollectionOp(
                mw,
                lambda col: _delete_model_from_collection(params, col),
            ).success(finish).failure(lambda exc: finish(error=exc)).run_in_background()
        except Exception as exc:
            finish(error=exc)

    mw.taskman.run_on_main(start_op)
    if not done.wait(_NATIVE_ACTION_TIMEOUT_S):
        raise TimeoutError("timed out deleting model")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def delete_model(params: dict, collection: Optional[Any] = None, mw: Optional[Any] = None) -> dict:
    if collection is not None:
        result = _delete_model_from_collection(params, collection)
        if mw is not None:
            mw.reset()
        return result.payload
    return _delete_model_in_anki(params)
