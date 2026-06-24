import base64
import io
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
    def __init__(self, models, decks=None, sched=None, media=None):
        self.models = models
        self.decks = decks
        self.sched = sched
        self.media = media
        self.removed_notes = []
        self.updated_notes = []
        self.set_deck_calls = []

    def remove_notes(self, note_ids):
        self.removed_notes.extend(note_ids)
        return object()

    def get_note(self, note_id):
        return _Note(note_id)

    def update_note(self, note, skip_undo_entry=False):
        self.updated_notes.append((note, skip_undo_entry))
        return object()

    def set_deck(self, card_ids, deck_id):
        self.set_deck_calls.append((card_ids, deck_id))
        return object()


class _Note:
    def __init__(self, note_id):
        self.id = note_id
        self.fields = {"Front": "old", "Back": "old"}

    def keys(self):
        return self.fields.keys()

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, key):
        return self.fields[key]


class _Sched:
    def __init__(self):
        self.set_due_date_calls = []

    def set_due_date(self, card_ids, days, config_key=None):
        self.set_due_date_calls.append((card_ids, days, config_key))
        return object()


class _SyncOutput:
    NO_CHANGES = 0
    NORMAL_SYNC = 1

    def __init__(self, required):
        self.required = required


class _SyncCollection(_Collection):
    def __init__(self, required):
        super().__init__(models=_Models())
        self.output = _SyncOutput(required)
        self.sync_args = None

    def sync_collection(self, auth, media_syncing_enabled):
        self.sync_args = (auth, media_syncing_enabled)
        return self.output


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


class _Media:
    def __init__(self, media_dir):
        self._dir = Path(media_dir)
        self._dir.mkdir()
        self.trashed = []

    def dir(self):
        return str(self._dir)

    def write_data(self, desired_fname, data):
        (self._dir / desired_fname).write_bytes(data)
        return desired_fname

    def add_file(self, path):
        filename = Path(path).name
        (self._dir / filename).write_bytes(Path(path).read_bytes())
        return filename

    def trash_files(self, fnames):
        self.trashed.extend(fnames)
        for filename in fnames:
            (self._dir / filename).unlink(missing_ok=True)


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
    assert native_actions.can_handle({"action": native_actions.ADD_MEDIA_FILE_ACTION})
    assert native_actions.can_handle({"action": native_actions.GET_MEDIA_FILE_ACTION})
    assert native_actions.can_handle({"action": native_actions.LIST_MEDIA_FILES_ACTION})
    assert native_actions.can_handle({"action": native_actions.DELETE_MEDIA_FILE_ACTION})
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
    assert 12.0 < seen["timeout_s"] <= 12.5


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


def test_add_notes_returns_null_for_rejected_notes_without_rollback(monkeypatch):
    def fake_add_note(note_input, _collection):
        if note_input["fields"]["Front"] == "duplicate":
            raise ValueError("cannot create note because it is a duplicate")
        return 100 + len(note_input["fields"]["Front"])

    monkeypatch.setattr(native_actions, "_add_note", fake_add_note)
    collection = _Collection(models=_Models())

    result = native_actions.execute_action(
        "addNotes",
        {
            "notes": [
                {"fields": {"Front": "ok"}},
                {"fields": {"Front": "duplicate"}},
                {"fields": {"Front": "also ok"}},
            ]
        },
        collection,
    )

    assert result == [102, None, 107]
    assert collection.removed_notes == []


def test_update_note_fields_matches_field_names_case_insensitively():
    collection = _Collection(models=_Models())

    result = native_actions.execute_action(
        "updateNoteFields",
        {"note": {"id": 123, "fields": {"front": "new front"}}},
        collection,
    )

    assert result is None
    note, skip_undo_entry = collection.updated_notes[0]
    assert note.fields == {"Front": "new front", "Back": "old"}
    assert skip_undo_entry is True


def test_update_note_fields_rejects_unknown_fields():
    with pytest.raises(ValueError, match="field was not found"):
        native_actions.execute_action(
            "updateNoteFields",
            {"note": {"id": 123, "fields": {"Missing": "new"}}},
            _Collection(models=_Models()),
        )


def test_change_deck_uses_collection_set_deck_when_available():
    collection = _Collection(models=_Models(), decks=_Decks())

    result = native_actions.execute_action(
        "changeDeck",
        {"cards": ["30", 31], "deck": "Scratch"},
        collection,
    )

    assert result is None
    assert collection.set_deck_calls == [([30, 31], 2)]


def test_add_media_file_base64_writes_data(tmp_path):
    media = _Media(tmp_path / "media")
    collection = _Collection(models=_Models(), media=media)

    result = native_actions.execute_action(
        native_actions.ADD_MEDIA_FILE_ACTION,
        {
            "filename": "image.png",
            "data": base64.b64encode(b"png bytes").decode("ascii"),
        },
        collection,
    )

    assert result == {"filename": "image.png"}
    assert (Path(media.dir()) / "image.png").read_bytes() == b"png bytes"


def test_add_media_file_path_imports_local_file(tmp_path):
    media = _Media(tmp_path / "media")
    source = tmp_path / "sound.mp3"
    source.write_bytes(b"mp3 bytes")

    result = native_actions.execute_action(
        native_actions.ADD_MEDIA_FILE_ACTION,
        {"filename": "sound.mp3", "path": str(source)},
        _Collection(models=_Models(), media=media),
    )

    assert result == {"filename": "sound.mp3"}
    assert (Path(media.dir()) / "sound.mp3").read_bytes() == b"mp3 bytes"


def test_add_media_file_rejects_unsafe_filename(tmp_path):
    media = _Media(tmp_path / "media")

    with pytest.raises(ValueError, match="basename"):
        native_actions.execute_action(
            native_actions.ADD_MEDIA_FILE_ACTION,
            {
                "filename": "../image.png",
                "data": base64.b64encode(b"png bytes").decode("ascii"),
            },
            _Collection(models=_Models(), media=media),
        )


def test_add_media_file_requires_one_source(tmp_path):
    media = _Media(tmp_path / "media")

    with pytest.raises(ValueError, match="exactly one"):
        native_actions.execute_action(
            native_actions.ADD_MEDIA_FILE_ACTION,
            {
                "filename": "image.png",
                "data": base64.b64encode(b"png bytes").decode("ascii"),
                "path": str(tmp_path / "image.png"),
            },
            _Collection(models=_Models(), media=media),
        )


def test_add_media_file_path_filename_must_match_basename(tmp_path):
    media = _Media(tmp_path / "media")
    source = tmp_path / "actual.png"
    source.write_bytes(b"png bytes")

    with pytest.raises(ValueError, match="match the basename"):
        native_actions.execute_action(
            native_actions.ADD_MEDIA_FILE_ACTION,
            {"filename": "wanted.png", "path": str(source)},
            _Collection(models=_Models(), media=media),
        )


def test_get_list_delete_media_file_round_trip(tmp_path):
    media = _Media(tmp_path / "media")
    media.write_data("one.png", b"one")
    media.write_data("two.mp3", b"two")
    media.write_data("skip.txt", b"skip")
    collection = _Collection(models=_Models(), media=media)

    listed = native_actions.execute_action(
        native_actions.LIST_MEDIA_FILES_ACTION,
        {"pattern": "*.png"},
        collection,
    )
    fetched = native_actions.execute_action(
        native_actions.GET_MEDIA_FILE_ACTION,
        {"filename": "one.png"},
        collection,
    )
    deleted = native_actions.execute_action(
        native_actions.DELETE_MEDIA_FILE_ACTION,
        {"filename": "one.png", "confirm": True},
        collection,
    )

    assert listed == {"filenames": ["one.png"]}
    assert fetched == {
        "filename": "one.png",
        "data": base64.b64encode(b"one").decode("ascii"),
        "mime_type": "image/png",
        "size_bytes": 3,
    }
    assert deleted == {"filename": "one.png", "deleted": True}
    assert media.trashed == ["one.png"]
    assert not (Path(media.dir()) / "one.png").exists()


def test_get_media_file_rejects_symlink_escape(tmp_path):
    media = _Media(tmp_path / "media")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    (Path(media.dir()) / "leak.png").symlink_to(outside)

    with pytest.raises(ValueError, match="inside the Anki media directory"):
        native_actions.execute_action(
            native_actions.GET_MEDIA_FILE_ACTION,
            {"filename": "leak.png"},
            _Collection(models=_Models(), media=media),
        )


def test_delete_media_file_requires_confirm(tmp_path):
    media = _Media(tmp_path / "media")
    media.write_data("image.png", b"png bytes")

    with pytest.raises(ValueError, match="confirm=true"):
        native_actions.execute_action(
            native_actions.DELETE_MEDIA_FILE_ACTION,
            {"filename": "image.png"},
            _Collection(models=_Models(), media=media),
        )


def test_add_media_file_url_fetches_public_url_with_pinned_ip(monkeypatch, tmp_path):
    media = _Media(tmp_path / "media")

    def fake_getaddrinfo(host, port, type=0):
        assert host == "example.com"
        return [(native_actions.socket.AF_INET, native_actions.socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    def fake_request(parsed, pinned_ip, timeout_s):
        assert parsed.hostname == "example.com"
        assert pinned_ip == "93.184.216.34"
        assert timeout_s <= 10.0
        return 200, {"content-type": "image/png"}, b"remote png"

    monkeypatch.setattr(native_actions.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(native_actions, "_request_pinned_url", fake_request)

    result = native_actions.execute_action(
        native_actions.ADD_MEDIA_FILE_ACTION,
        {"filename": "remote.png", "url": "https://example.com/image"},
        _Collection(models=_Models(), media=media),
    )

    assert result == {"filename": "remote.png"}
    assert (Path(media.dir()) / "remote.png").read_bytes() == b"remote png"


def test_fetch_media_url_does_not_reresolve_hostname_after_pinning(monkeypatch):
    resolve_calls = []
    sockets = []

    class FakeSocket:
        def __init__(self):
            self.sent = b""

        def sendall(self, data):
            self.sent += data

        def makefile(self, mode):
            assert mode == "rb"
            return io.BytesIO(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: image/png\r\n"
                b"Content-Length: 10\r\n"
                b"\r\n"
                b"remote png"
            )

        def close(self):
            pass

    def fake_getaddrinfo(host, port, type=0):
        resolve_calls.append((host, port))
        if host != "example.com":
            raise AssertionError(f"unexpected DNS lookup for {host}")
        if len(resolve_calls) > 1:
            raise AssertionError("hostname was re-resolved after validation")
        return [
            (
                native_actions.socket.AF_INET,
                native_actions.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", port),
            )
        ]

    def fake_create_connection(address, timeout=None):
        socket = FakeSocket()
        sockets.append((address, timeout, socket))
        return socket

    monkeypatch.setattr(native_actions.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(native_actions.socket, "create_connection", fake_create_connection)

    data, content_type = native_actions._fetch_media_url(
        "http://example.com/image.png",
        deadline=native_actions.time.monotonic() + 5,
    )

    assert data == b"remote png"
    assert content_type == "image/png"
    assert resolve_calls == [("example.com", 80)]
    assert sockets[0][0] == ("93.184.216.34", 80)
    assert b"Host: example.com" in sockets[0][2].sent
    assert (
        b"User-Agent: ToolforestAnkiBridge/0.1.1 "
        b"(+https://toolforest.io; mailto:support@toolforest.io)"
    ) in sockets[0][2].sent


def test_media_fetch_user_agent_uses_addon_version(monkeypatch):
    monkeypatch.setattr(native_actions, "addon_version", lambda: "9.8.7")

    user_agent = native_actions._media_fetch_user_agent()

    assert user_agent == (
        "ToolforestAnkiBridge/9.8.7 "
        "(+https://toolforest.io; mailto:support@toolforest.io)"
    )
    assert "Mozilla" not in user_agent


def test_add_media_file_url_blocks_private_ip(monkeypatch, tmp_path):
    media = _Media(tmp_path / "media")

    monkeypatch.setattr(
        native_actions.socket,
        "getaddrinfo",
        lambda host, port, type=0: [
            (
                native_actions.socket.AF_INET,
                native_actions.socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1", port),
            )
        ],
    )

    with pytest.raises(ValueError, match="private or reserved"):
        native_actions.execute_action(
            native_actions.ADD_MEDIA_FILE_ACTION,
            {"filename": "remote.png", "url": "https://private.example/image"},
            _Collection(models=_Models(), media=media),
        )


def test_add_media_file_url_blocks_redirect_to_private(monkeypatch, tmp_path):
    media = _Media(tmp_path / "media")

    def fake_getaddrinfo(host, port, type=0):
        ip = "93.184.216.34" if host == "example.com" else "127.0.0.1"
        return [(native_actions.socket.AF_INET, native_actions.socket.SOCK_STREAM, 6, "", (ip, port))]

    def fake_request(parsed, pinned_ip, timeout_s):
        assert parsed.hostname == "example.com"
        return 302, {"location": "http://127.0.0.1/secret"}, b""

    monkeypatch.setattr(native_actions.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(native_actions, "_request_pinned_url", fake_request)

    with pytest.raises(ValueError, match="private or reserved"):
        native_actions.execute_action(
            native_actions.ADD_MEDIA_FILE_ACTION,
            {"filename": "remote.png", "url": "https://example.com/image"},
            _Collection(models=_Models(), media=media),
        )


def test_handle_prefetches_url_before_anki_main_thread(monkeypatch, tmp_path):
    media = _Media(tmp_path / "media")
    collection = _Collection(models=_Models(), media=media)
    seen = []

    def fake_fetch(url, deadline=None):
        seen.append(("fetch", url))
        return b"remote png", "image/png"

    def fake_run_in_anki(callback, timeout_s):
        seen.append(("run", timeout_s))
        return callback(collection, None)

    monkeypatch.setattr(native_actions, "_fetch_media_url", fake_fetch)
    monkeypatch.setattr(native_actions, "_run_in_anki", fake_run_in_anki)

    out = native_actions.handle(
        {
            "action": native_actions.ADD_MEDIA_FILE_ACTION,
            "params": {"filename": "remote.png", "url": "https://example.com/image"},
        },
        timeout_s=12.0,
    )

    assert out == {"result": {"filename": "remote.png"}, "error": None}
    assert seen[0] == ("fetch", "https://example.com/image")
    assert seen[1][0] == "run"


def test_url_validation_blocks_nat64_well_known_prefix(monkeypatch):
    monkeypatch.setattr(
        native_actions.socket,
        "getaddrinfo",
        lambda host, port, type=0: [
            (
                native_actions.socket.AF_INET6,
                native_actions.socket.SOCK_STREAM,
                6,
                "",
                ("64:ff9b::7f00:1", port, 0, 0),
            )
        ],
    )

    with pytest.raises(ValueError, match="private or reserved"):
        native_actions._validate_public_url_target("https://nat64.example/image.png")


def test_get_media_file_rejects_large_file(tmp_path, monkeypatch):
    media = _Media(tmp_path / "media")
    media.write_data("large.png", b"large")
    monkeypatch.setattr(native_actions, "_MAX_MEDIA_GET_BYTES", 4)

    with pytest.raises(ValueError, match="too large"):
        native_actions.execute_action(
            native_actions.GET_MEDIA_FILE_ACTION,
            {"filename": "large.png"},
            _Collection(models=_Models(), media=media),
        )


def test_sync_runs_normal_sync_and_calls_anki_sync_ui():
    collection = _SyncCollection(required=_SyncOutput.NORMAL_SYNC)
    mw = SimpleNamespace(
        pm=SimpleNamespace(
            sync_auth=lambda: "auth-token",
            media_syncing_enabled=lambda: False,
        ),
        onSync=MagicMock(),
    )

    result = native_actions.execute_action("sync", {}, collection, mw)

    assert result is None
    assert collection.sync_args == ("auth-token", False)
    mw.onSync.assert_called_once()


def test_sync_full_sync_required_refuses_with_user_action():
    collection = _SyncCollection(required=2)
    mw = SimpleNamespace(
        pm=SimpleNamespace(
            sync_auth=lambda: "auth-token",
            media_syncing_enabled=lambda: True,
        ),
        onSync=MagicMock(),
    )

    with pytest.raises(ValueError) as exc_info:
        native_actions.execute_action("sync", {}, collection, mw)

    message = str(exc_info.value)
    assert "Anki requires a full sync" in message
    assert "Sync button" in message
    assert "Upload to AnkiWeb or Download from AnkiWeb" in message
    assert "Sync status" not in message
    mw.onSync.assert_not_called()


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
