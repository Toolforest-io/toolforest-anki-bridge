"""Native Anki action executor used by the Toolforest bridge.

The cloud toolkit still sends AnkiConnect-shaped envelopes. This module maps
that stable wire shape to in-process Anki APIs, so the bridge no longer needs
the separate AnkiConnect add-on or localhost HTTP server.

All Anki imports are lazy so protocol/forwarder tests remain runnable in a
normal Python process.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional


DELETE_MODEL_ACTION = "toolforestDeleteModel"
_DEFAULT_TIMEOUT_S = 15
_WRITE_ACTIONS = {
    "addNote",
    "addNotes",
    "addTags",
    "answerCards",
    "changeDeck",
    "createDeck",
    "createModel",
    "deleteDecks",
    "deleteNotes",
    "removeTags",
    "setDueDate",
    "suspend",
    "sync",
    "unsuspend",
    "updateNoteFields",
    DELETE_MODEL_ACTION,
}
_SUPPORTED_ACTIONS = {
    "cardsInfo",
    "deckNames",
    "findCards",
    "findNotes",
    "getDeckStats",
    "modelFieldNames",
    "modelNames",
    "modelNamesAndIds",
    "modelTemplates",
    "notesInfo",
    "version",
    *_WRITE_ACTIONS,
}


def can_handle(body: dict) -> bool:
    return body.get("action") in _SUPPORTED_ACTIONS


def handle(body: dict, timeout_s: float = _DEFAULT_TIMEOUT_S) -> dict:
    action = body.get("action")
    params = body.get("params") or {}
    if action not in _SUPPORTED_ACTIONS:
        return {"result": None, "error": f"unsupported action: {action}"}

    try:
        result = _run_in_anki(lambda col, mw: execute_action(action, params, col, mw), timeout_s)
    except Exception as exc:  # noqa: BLE001 - AnkiConnect-compatible error envelope
        return {"result": None, "error": str(exc)}
    return {"result": result, "error": None}


def execute_action(action: str, params: dict, collection: Any, mw: Optional[Any] = None) -> Any:
    if action in _WRITE_ACTIONS:
        _mark_collection_changed(mw)

    if action == "version":
        return 6
    if action == "deckNames":
        return _deck_names(collection)
    if action == "createDeck":
        return int(collection.decks.id(_required(params, "deck")))
    if action == "deleteDecks":
        return _delete_decks(params, collection)
    if action == "getDeckStats":
        return _get_deck_stats(params, collection)
    if action == "findCards":
        return _find_cards(params, collection)
    if action == "findNotes":
        return _find_notes(params, collection)
    if action == "cardsInfo":
        return _cards_info(params, collection)
    if action == "notesInfo":
        return _notes_info(params, collection, mw)
    if action == "modelNames":
        return _model_names(collection)
    if action == "modelNamesAndIds":
        return _model_names_and_ids(collection)
    if action == "modelFieldNames":
        return _model_field_names(params, collection)
    if action == "modelTemplates":
        return _model_templates(params, collection)
    if action == "createModel":
        return _create_model(params, collection)
    if action == "addNote":
        return _add_note(_required(params, "note"), collection)
    if action == "addNotes":
        return _add_notes(params.get("notes") or [], collection)
    if action == "updateNoteFields":
        return _update_note_fields(_required(params, "note"), collection)
    if action == "addTags":
        return _add_tags(params, collection, add=True)
    if action == "removeTags":
        return _add_tags(params, collection, add=False)
    if action == "deleteNotes":
        collection.remove_notes([int(note_id) for note_id in (params.get("notes") or [])])
        return None
    if action == "answerCards":
        return _answer_cards(params, collection)
    if action == "setDueDate":
        collection.sched.set_due_date(
            [int(card_id) for card_id in (params.get("cards") or [])],
            str(_required(params, "days")),
            config_key=None,
        )
        return None
    if action == "suspend":
        return _set_suspended(params, collection, suspended=True)
    if action == "unsuspend":
        return _set_suspended(params, collection, suspended=False)
    if action == "changeDeck":
        return _change_deck(params, collection)
    if action == "sync":
        return _sync(collection, mw)
    if action == DELETE_MODEL_ACTION:
        return delete_model(params, collection=collection, mw=mw)

    raise ValueError(f"unsupported action: {action}")


def delete_model(
    params: dict,
    collection: Optional[Any] = None,
    mw: Optional[Any] = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict:
    if collection is not None:
        return _delete_model(params, collection, mw)
    return _run_in_anki(lambda col, actual_mw: _delete_model(params, col, actual_mw), timeout_s)


def _run_in_anki(fn: Callable[[Any, Any], Any], timeout_s: float) -> Any:
    collection, mw = _current_anki_context()
    if threading.current_thread() is threading.main_thread():
        return fn(collection, mw)

    done = threading.Event()
    outcome: dict[str, Any] = {}

    def task() -> None:
        try:
            current_collection, current_mw = _current_anki_context()
            outcome["result"] = fn(current_collection, current_mw)
        except Exception as exc:  # noqa: BLE001 - transport worker re-raises below
            outcome["error"] = exc
        finally:
            done.set()

    mw.taskman.run_on_main(task)
    if not done.wait(timeout_s):
        raise TimeoutError("timed out waiting for Anki; the operation may still complete in Anki")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("result")


def _current_anki_context() -> tuple[Any, Any]:
    try:
        import aqt  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Anki runtime is not available") from exc

    collection = getattr(getattr(aqt, "mw", None), "col", None)
    if collection is None:
        raise RuntimeError("Anki collection is not available")
    return collection, aqt.mw


def _required(params: dict, key: str) -> Any:
    if key not in params:
        raise ValueError(f"{key} is required")
    return params[key]


def _mark_collection_changed(mw: Optional[Any]) -> None:
    if mw is None:
        return
    try:
        mw.requireReset()
    except Exception:
        pass


def _deck_names(collection: Any) -> list[str]:
    return [item.name for item in collection.decks.all_names_and_ids()]


def _deck_name_from_id(collection: Any, deck_id: int) -> str:
    deck = collection.decks.get(deck_id)
    if deck is None:
        raise ValueError(f"deck was not found: {deck_id}")
    return deck["name"]


def _delete_decks(params: dict, collection: Any) -> None:
    if params.get("cardsToo") is not True:
        raise ValueError("cardsToo=true is required to delete decks")
    existing = set(_deck_names(collection))
    for deck in params.get("decks") or []:
        if deck in existing:
            collection.decks.remove([collection.decks.id(deck)])
    return None


def _get_deck_stats(params: dict, collection: Any) -> dict:
    wanted: set[int] = set()
    for deck in params.get("decks") or []:
        deck_dict = collection.decks.by_name(deck)
        if deck_dict is not None:
            wanted.add(int(deck_dict["id"]))

    output: dict[int, dict[str, Any]] = {}
    for deck_id, node in _deck_tree_nodes(collection.sched.deck_due_tree()).items():
        if deck_id in wanted:
            item = {
                "deck_id": node.deck_id,
                "name": node.name,
                "new_count": node.new_count,
                "learn_count": node.learn_count,
                "review_count": node.review_count,
            }
            if hasattr(node, "total_in_deck"):
                item["total_in_deck"] = node.total_in_deck
            output[deck_id] = item
    return output


def _deck_tree_nodes(node: Any) -> dict[int, Any]:
    nodes = {int(node.deck_id): node}
    for child in getattr(node, "children", []):
        nodes.update(_deck_tree_nodes(child))
    return nodes


def _find_cards(params: dict, collection: Any) -> list[int]:
    query = params.get("query")
    if query is None:
        return []
    return [int(card_id) for card_id in collection.find_cards(query)]


def _find_notes(params: dict, collection: Any) -> list[int]:
    query = params.get("query")
    if query is None:
        return []
    return [int(note_id) for note_id in collection.find_notes(query)]


def _get_card(collection: Any, card_id: int) -> Any:
    try:
        return collection.get_card(card_id)
    except Exception as exc:
        raise ValueError(f"Card was not found: {card_id}") from exc


def _get_note(collection: Any, note_id: int) -> Any:
    try:
        return collection.get_note(note_id)
    except Exception as exc:
        raise ValueError(f"Note was not found: {note_id}") from exc


def _card_question(card: Any) -> str:
    if hasattr(card, "question"):
        return card.question()
    return card._getQA()["q"]


def _card_answer(card: Any) -> str:
    if hasattr(card, "answer"):
        return card.answer()
    return card._getQA()["a"]


def _cards_info(params: dict, collection: Any) -> list[dict]:
    result = []
    for raw_card_id in params.get("cards") or []:
        card_id = int(raw_card_id)
        try:
            card = _get_card(collection, card_id)
            model = card.note_type()
            note = card.note()
            fields = {
                field["name"]: {"value": note.fields[field["ord"]], "order": field["ord"]}
                for field in model["flds"]
            }
            next_reviews = []
            try:
                states = collection._backend.get_scheduling_states(card.id)
                next_reviews = list(collection._backend.describe_next_states(states))
            except Exception:
                pass
            result.append(
                {
                    "cardId": card.id,
                    "fields": fields,
                    "fieldOrder": card.ord,
                    "question": _card_question(card),
                    "answer": _card_answer(card),
                    "modelName": model["name"],
                    "ord": card.ord,
                    "deckName": _deck_name_from_id(collection, card.did),
                    "css": model.get("css", ""),
                    "factor": card.factor,
                    "interval": card.ivl,
                    "note": card.nid,
                    "type": card.type,
                    "queue": card.queue,
                    "due": card.due,
                    "reps": card.reps,
                    "lapses": card.lapses,
                    "left": card.left,
                    "mod": card.mod,
                    "nextReviews": next_reviews,
                    "flags": card.flags,
                }
            )
        except Exception:
            result.append({})
    return result


def _notes_info(params: dict, collection: Any, mw: Optional[Any]) -> list[dict]:
    notes = params.get("notes")
    if notes is None:
        query = params.get("query")
        if query is None:
            raise ValueError('Must provide either "notes" or a "query"')
        notes = _find_notes({"query": query}, collection)

    note_ids = [int(note_id) for note_id in notes]
    card_ids_by_note = _card_ids_by_note(collection, note_ids)
    profile = getattr(getattr(mw, "pm", None), "name", "") if mw is not None else ""
    result = []
    for note_id in note_ids:
        try:
            note = _get_note(collection, note_id)
            model = note.note_type()
            fields = {
                field["name"]: {"value": note.fields[field["ord"]], "order": field["ord"]}
                for field in model["flds"]
            }
            result.append(
                {
                    "noteId": note.id,
                    "profile": profile,
                    "tags": note.tags,
                    "fields": fields,
                    "modelName": model["name"],
                    "mod": note.mod,
                    "cards": card_ids_by_note.get(note_id, []),
                }
            )
        except Exception:
            result.append({})
    return result


def _card_ids_by_note(collection: Any, note_ids: list[int]) -> dict[int, list[int]]:
    if not note_ids:
        return {}
    output: dict[int, list[int]] = {}
    for batch in _batches(note_ids, 999):
        placeholders = ",".join("?" for _ in batch)
        rows = collection.db.all(
            f"select id, nid from cards where nid in ({placeholders}) order by ord",
            *batch,
        )
        for card_id, note_id in rows:
            output.setdefault(int(note_id), []).append(int(card_id))
    return output


def _batches(values: list[int], size: int) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _model_names(collection: Any) -> list[str]:
    return [item.name for item in collection.models.all_names_and_ids()]


def _model_names_and_ids(collection: Any) -> dict[str, int]:
    return {
        name: int(collection.models.by_name(name)["id"])
        for name in _model_names(collection)
    }


def _model_field_names(params: dict, collection: Any) -> list[str]:
    model_name = params.get("modelName") or params.get("model")
    model = collection.models.by_name(model_name)
    if model is None:
        raise ValueError(f"model was not found: {model_name}")
    return [field["name"] for field in model["flds"]]


def _model_templates(params: dict, collection: Any) -> dict[str, dict[str, str]]:
    model_name = params.get("modelName") or params.get("model")
    model = collection.models.by_name(model_name)
    if model is None:
        raise ValueError(f"model was not found: {model_name}")
    return {
        template["name"]: {"Front": template["qfmt"], "Back": template["afmt"]}
        for template in model["tmpls"]
    }


def _create_model(params: dict, collection: Any) -> dict:
    model_name = _required(params, "modelName")
    fields = params.get("inOrderFields") or []
    templates = params.get("cardTemplates") or []
    if not fields:
        raise ValueError("Must provide at least one field for inOrderFields")
    if not templates:
        raise ValueError("Must provide at least one card for cardTemplates")
    _validate_unique_names(fields, "field")
    if model_name in _model_names(collection):
        raise ValueError("Model name already exists")

    from anki.consts import MODEL_CLOZE  # type: ignore

    models = collection.models
    model = models.new(model_name)
    if params.get("isCloze"):
        model["type"] = MODEL_CLOZE
    for field_name in fields:
        field = models.new_field(field_name)
        models.addField(model, field)
    if params.get("css") is not None:
        model["css"] = params["css"]
    for index, template_input in enumerate(templates, start=1):
        name = template_input.get("Name") or f"Card {index}"
        template = models.new_template(name)
        template["qfmt"] = template_input["Front"]
        template["afmt"] = template_input["Back"]
        models.addTemplate(model, template)
    models.add(model)
    return model


def _validate_unique_names(names: list[str], label: str) -> None:
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label} names must be non-empty strings")
        normalized = name.casefold()
        if normalized in seen:
            raise ValueError(f"duplicate {label} name: {name}")
        seen.add(normalized)


def _make_note(note_input: dict, collection: Any) -> tuple[Any, int]:
    model_name = note_input["modelName"]
    deck_name = note_input["deckName"]
    model = collection.models.by_name(model_name)
    if model is None:
        raise ValueError(f"model was not found: {model_name}")
    deck = collection.decks.by_name(deck_name)
    if deck is None:
        raise ValueError(f"deck was not found: {deck_name}")

    if hasattr(collection, "new_note"):
        note = collection.new_note(model)
    else:
        from anki.notes import Note  # type: ignore

        note = Note(collection, model)
    note.note_type()["did"] = deck["id"]
    note.tags = list(note_input.get("tags") or [])

    for name, value in (note_input.get("fields") or {}).items():
        for anki_name in note.keys():
            if name.lower() == anki_name.lower():
                note[anki_name] = value
                break

    state = int(note.fields_check())
    allow_duplicate = bool((note_input.get("options") or {}).get("allowDuplicate"))
    if state == 1:
        raise ValueError("cannot create note because it is empty")
    if state == 2 and not allow_duplicate:
        raise ValueError("cannot create note because it is a duplicate")
    if state not in (0, 2):
        raise ValueError(f"cannot create note: fields check failed with state {state}")
    return note, int(deck["id"])


def _add_note(note_input: dict, collection: Any) -> int:
    note, deck_id = _make_note(note_input, collection)
    if hasattr(collection, "add_note"):
        collection.add_note(note, deck_id)
    else:
        card_count = collection.addNote(note)
        if card_count < 1:
            raise ValueError("The field values you have provided would make an empty question on all cards.")
    return int(note.id)


def _add_notes(notes: list[dict], collection: Any) -> list[int]:
    note_ids: list[int] = []
    try:
        for note_input in notes:
            note_ids.append(_add_note(note_input, collection))
    except Exception:
        if note_ids:
            collection.remove_notes(note_ids)
        raise
    return note_ids


def _update_note_fields(note_update: dict, collection: Any) -> None:
    note = _get_note(collection, int(_required(note_update, "id")))
    for name, value in (note_update.get("fields") or {}).items():
        if name in note:
            note[name] = value
    collection.update_note(note, skip_undo_entry=True)
    return None


def _add_tags(params: dict, collection: Any, add: bool) -> None:
    notes = [int(note_id) for note_id in (params.get("notes") or [])]
    collection.tags.bulkAdd(notes, params.get("tags") or "", add)
    return None


def _answer_cards(params: dict, collection: Any) -> list[bool]:
    success = []
    for answer in params.get("answers") or []:
        try:
            card = _get_card(collection, int(answer["cardId"]))
            card.start_timer()
            collection.sched.answerCard(card, int(answer["ease"]))
            success.append(True)
        except Exception:
            success.append(False)
    return success


def _set_suspended(params: dict, collection: Any, suspended: bool) -> bool:
    cards = []
    for raw_card_id in params.get("cards") or []:
        card_id = int(raw_card_id)
        try:
            card = _get_card(collection, card_id)
        except Exception:
            continue
        if (card.queue == -1) != suspended:
            cards.append(card_id)
    if not cards:
        return False
    if suspended:
        collection.sched.suspendCards(cards)
    else:
        collection.sched.unsuspendCards(cards)
    return True


def _change_deck(params: dict, collection: Any) -> None:
    import anki.utils  # type: ignore

    cards = [int(card_id) for card_id in (params.get("cards") or [])]
    if not cards:
        return None
    deck_id = collection.decks.id(_required(params, "deck"))
    collection.sched.remFromDyn(cards)
    collection.db.execute(
        "update cards set usn=?, mod=?, did=? where id in " + anki.utils.ids2str(cards),
        collection.usn(),
        anki.utils.int_time(),
        deck_id,
    )
    return None


def _sync(collection: Any, mw: Optional[Any]) -> None:
    if mw is None:
        raise ValueError("sync requires the Anki main window")
    auth = mw.pm.sync_auth()
    if not auth:
        raise ValueError("sync: auth not configured")
    output = collection.sync_collection(auth, mw.pm.media_syncing_enabled())
    accepted = [output.NO_CHANGES, output.NORMAL_SYNC]
    if output.required not in accepted:
        raise ValueError(f"Sync status {output.required} not one of {accepted}")
    mw.onSync()
    return None


def _notetype_id(model_id: int) -> Any:
    try:
        from anki.models import NotetypeId  # type: ignore
    except ImportError:
        return model_id
    return NotetypeId(model_id)


def _delete_model(params: dict, collection: Any, mw: Optional[Any]) -> dict:
    if params.get("confirm") is not True:
        raise ValueError("confirm=true is required")

    model_name = params.get("modelName") or params.get("model")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("modelName is required")

    model = collection.models.by_name(model_name)
    if model is None:
        raise ValueError(f"model was not found: {model_name}")

    use_count = int(collection.models.use_count(model))
    if use_count:
        raise ValueError(
            f"model is still in use: {model_name} has {use_count} note(s); "
            "delete or move those notes first."
        )

    model_id = int(model["id"])
    collection.models.remove(_notetype_id(model_id))
    try:
        if mw is not None:
            mw.reset()
    except Exception:
        pass
    return {"model": model_name, "model_id": model_id, "deleted": True}
