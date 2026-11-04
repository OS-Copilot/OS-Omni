"""OpenNote snap_2 workflows (Web, WEB-067 / WEB-070): the document is decoded from LevelDB, not scraped.

The restored evaluators decoded the raw .log/.ldb bytes as UTF-8 and parsed JSON fragments.  OpenNote's
document is ~4 MB, so Chrome's log splits it across 32 KiB blocks (each with a 7-byte header) and the
sorted tables Snappy-compress it: the document was never parsed whole.  The evaluators now read it with
the shared LevelDB reader and grade its fields.
"""

from __future__ import annotations

import copy
import json
import struct
from pathlib import Path

import yaml

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.linux import opennote_desk_cable_followup_snap2 as desk_cable
from evaluators.linux import opennote_snap2_home_food_profile as home_food

REPO = Path(__file__).resolve().parents[1]
KEY = "opennote.localState.v2"
_BLOCK = 32768


def _params(name: str) -> dict:
    return yaml.safe_load((REPO / "tasks/v1/web" / name).read_text(encoding="utf-8"))["evaluation"]["params"]


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _leveldb_log(document: dict) -> bytes:
    """A LevelDB write-ahead log holding one put of the OpenNote document, as Chrome writes it."""
    user_key = b"_file://\x00\x01" + KEY.encode("utf-8")
    value = b"\x01" + json.dumps(document).encode("utf-8")
    payload = struct.pack("<QI", 1, 1) + b"\x01" + _varint(len(user_key)) + user_key + _varint(len(value)) + value
    out, first = bytearray(), True
    while payload:
        left = _BLOCK - len(out) % _BLOCK
        if left <= 7:
            out += b"\x00" * left
            continue
        fragment, payload = payload[: left - 7], payload[left - 7:]
        kind = (1 if not payload else 2) if first else (4 if not payload else 3)
        out += struct.pack("<IHB", 0, len(fragment), kind) + fragment
        first = False
    return bytes(out)


def _document(params: dict) -> dict:
    """The document a run that follows the brief leaves, plus enough seeded notes to span many blocks."""
    handle = "lina"
    notes, comments, liked, saved = [], {}, [], []
    for index in range(400):  # seeded filler (the real seed has 421 notes and data:image covers)
        notes.append({"id": "n-%d" % (5000 + index), "authorHandle": "seed_%d" % index, "title": "Seed note %d" % index,
                      "text": "x" * 200, "category": "Home", "tags": ["home"], "location": "somewhere",
                      "cover": "/assets/covers/%d.jpg" % index, "likes": 1, "saves": 1})
    for index, note in enumerate(params.get("existing_notes") or []):
        note_id = "n-%d" % (3000 + index)
        notes.append({"id": note_id, "authorHandle": "june_07", "title": note["title"], "text": "seeded",
                      "category": "Home", "tags": ["plant corner"], "location": "kitchen", "cover": "/a.jpg"})
        liked.append(note_id)
        saved.append(note_id)
    created = params.get("created_notes") or []
    for index, note in enumerate(created if isinstance(created, list) else [created]):
        note_id = "n-17900000%d" % index
        tags = note.get("tags") or []
        notes.insert(0, {"id": note_id, "authorHandle": handle, "title": note["title"], "text": note["body"],
                         "category": note.get("category") or "Lifestyle", "tags": tags if isinstance(tags, list) else [tags],
                         "location": note["location"], "cover": "data:image/png;base64,iVBORw0KGgo=", "likes": 0})
        if note.get("liked"):
            liked.append(note_id)
        if note.get("saved"):
            saved.append(note_id)
    by_title = {note["title"]: note["id"] for note in notes}
    for comment in params.get("comments") or []:
        comments.setdefault(by_title[comment["note_title"]], []).append(
            {"id": "c-%d" % len(comments), "authorHandle": handle, "text": comment["text"]})
    profile = {field["name"]: field["value"] for field in params.get("profile_fields") or []}
    return {
        "session": {"loggedIn": True, "user": {"handle": handle, "displayName": "Lina Park"}},
        "users": [{"handle": handle, "displayName": "Lina Park", "title": "", "bio": "", **profile},
                  {"handle": "june_07", "displayName": "June Ellis"}],
        "userState": {handle: {"following": ["hao_03", "june_07"], "followers": [], "likedNoteIds": liked,
                               "savedNoteIds": saved}},
        "notes": notes,
        "comments": comments,
        "userNotifications": {handle: [{"id": "notif-%d" % i, "read": True} for i in range(5)]},
        "evaluationEvents": [],
    }


def _verdict(module, params: dict, document: dict, tmp_path: Path):
    store = tmp_path / "Local Storage" / "leveldb"
    store.mkdir(parents=True, exist_ok=True)
    (store / "000003.log").write_bytes(_leveldb_log(document))
    params = dict(params, local_storage_path=str(store))
    return module.OpenNoteWorkflowEvaluator().evaluate({"params": params, "controller": None})


DESK = "opennote_desk_cable_followup_snap2.yaml"
FOOD = "opennote_snap2_home_food_profile.yaml"


def test_a_brief_following_document_split_across_log_blocks_passes(tmp_path):
    for module, name in ((desk_cable, DESK), (home_food, FOOD)):
        params = _params(name)
        document = _document(params)
        raw = _leveldb_log(document)
        assert len(raw) > 4 * _BLOCK
        # what the restored evaluators did: the document is not recoverable from the raw bytes
        text = raw.decode("utf-8", errors="ignore")
        start = text.index('{"session"')
        try:
            json.JSONDecoder().raw_decode(text[start:])
            whole = True
        except json.JSONDecodeError:
            whole = False
        assert not whole
        result = _verdict(module, params, document, tmp_path / name)
        assert result.status == EvalStatus.PASS, result.message
        assert result.metadata["checks"]


def test_missing_document_is_a_failure_not_an_error(tmp_path):
    (tmp_path / "empty").mkdir()
    params = dict(_params(DESK), local_storage_path=str(tmp_path / "empty"))
    result = desk_cable.OpenNoteWorkflowEvaluator().evaluate({"params": params, "controller": None})
    assert result.status == EvalStatus.FAIL


def _failures(module, name, tmp_path, edit) -> list[str]:
    params = _params(name)
    document = _document(params)
    edit(document)
    return _verdict(module, params, document, tmp_path).metadata["failures"]


def _note_id(document: dict, title: str) -> str:
    return next(note["id"] for note in document["notes"] if note["title"] == title)


def test_likes_saves_and_follows_are_read_from_the_account_lists(tmp_path):
    title = "Desk cable cleanup after I found three mystery screws"

    def unlike(document):
        document["userState"]["lina"]["likedNoteIds"].remove(_note_id(document, title))

    assert _failures(desk_cable, DESK, tmp_path / "a", unlike) == ["liked_note:" + title]

    def unsave_created(document):
        document["userState"]["lina"]["savedNoteIds"].remove(_note_id(document, "Desk Cable Follow-up"))

    assert _failures(desk_cable, DESK, tmp_path / "b", unsave_created) == ["saved_created_note:Desk Cable Follow-up"]

    def unfollow(document):
        document["userState"]["lina"]["following"].remove("june_07")

    assert _failures(home_food, FOOD, tmp_path / "c", unfollow) == ["followed_author:June Ellis"]


def test_comments_must_be_the_accounts_own_on_the_named_note(tmp_path):
    def by_someone_else(document):
        for rows in document["comments"].values():
            for row in rows:
                if row["text"] == "Cable audit complete":
                    row["authorHandle"] = "milo_09"

    assert _failures(desk_cable, DESK, tmp_path / "a", by_someone_else) == [
        "comment_on_note:Desk Cable Follow-up:Cable audit complete"]

    def on_another_note(document):
        rows = document["comments"].pop(_note_id(document, "A real-life test of cold brew walk"))
        document["comments"].setdefault(_note_id(document, "Weekday ramen, tested with a hair tie"), []).extend(rows)

    assert _failures(home_food, FOOD, tmp_path / "b", on_another_note) == [
        "comment_on_note:A real-life test of cold brew walk:Is it tasty"]


def test_published_notes_need_the_declared_fields_and_the_account_as_author(tmp_path):
    def other_author(document):
        next(n for n in document["notes"] if n["title"] == "Desk bay")["authorHandle"] = "seed_1"

    failures = _failures(desk_cable, DESK, tmp_path / "a", other_author)
    assert "created_note_present:Desk bay" in failures and "liked_created_note:Desk bay" in failures

    def wrong_fields(document):
        note = next(n for n in document["notes"] if n["title"] == "Desk Cable Follow-up")
        note.update(location="Desk", tags=["desks"], cover="/assets/covers/1.jpg")

    assert _failures(desk_cable, DESK, tmp_path / "b", wrong_fields) == [
        "created_note_location:Desk Cable Follow-up", "created_note_tag:Desk Cable Follow-up:desk",
        "created_note_use_text_cover:Desk Cable Follow-up"]


def test_alerts_and_profile_fields(tmp_path):
    def one_unread(document):
        document["userNotifications"]["lina"][2]["read"] = False

    assert _failures(desk_cable, DESK, tmp_path / "a", one_unread) == ["alerts_marked_all_read"]

    def old_bio(document):
        document["users"][0]["bio"] = "Starting a fresh notebook here."

    assert _failures(home_food, FOOD, tmp_path / "b", old_bio) == ["profile_field:bio"]


def test_search_strings_are_not_graded(tmp_path):
    # The desk_cable brief asks for "search ... workflows" but names no search text.
    result = _verdict(desk_cable, _params(DESK), _document(_params(DESK)), tmp_path)
    assert not any(check["name"].startswith("search_query") for check in result.metadata["checks"])
    assert result.metadata["evidence"]["search_queries_not_graded"] == _params(DESK)["search_queries"]
