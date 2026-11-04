"""Delta Chat 4_2 / 4_4: FSNotes notes that carry the app-managed creation title.

scan rows IOS-004/IOS-005 (4_2) and IOS-006 (4_4).  FSNotes may write the
creation title (typed into "Search or create") ahead of the typed content and
name the file "<title> <first heading>.markdown".  The ruleset treats that
title as app-managed, so:

* the content checks compare the title-normalized lines, not raw bytes, and
* a shared attachment must be byte-identical to the *actual* note file.

Both renderings pass end to end; any other prefix, a blob that differs from
the note, or an ambiguous pair of note files still fails.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from evaluators.ios import deltachat_route_approval_saved_messages_4_2 as e42
from evaluators.ios import deltachat_route_handoff_saved_messages_4_4 as e44

MEI = "Mei update 03: search token route_final_blue_1740 should stay in this thread."
ALICE = "Alice note: design_search_anchor_alice_avatar is the anchor."
BOB = "Bob update 02: ops_launch_green_2026 is the status marker."
NORA = "Nora check: nav_bar_search_token_nora_2606 passes."
SOURCES = {"mei": MEI, "alice": ALICE, "bob": BOB, "nora": NORA}
CHATS = {"mei": (12, "Mei Chen"), "alice": (13, "Alice Design"), "bob": (14, "Bob Ops"), "nora": (15, "Nora QA")}
SELF_CHAT = 10


def _db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE chats (id INTEGER PRIMARY KEY, type INTEGER, name TEXT, param TEXT);
        CREATE TABLE msgs (
            id INTEGER PRIMARY KEY, chat_id INTEGER, from_id INTEGER, to_id INTEGER,
            type INTEGER, state INTEGER, timestamp INTEGER, timestamp_sent INTEGER,
            txt TEXT, param TEXT, hidden INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0
        );
        """
    )
    conn.executemany(
        "INSERT INTO chats VALUES (?,?,?,?)",
        [(SELF_CHAT, 100, "Saved Messages", "K=1")] + [(cid, 100, name, "") for cid, name in CHATS.values()],
    )
    baseline = [
        (40 + index, CHATS[key][0], 20 + index, 1, 10, 16, 1781000000 + index, 1781000000 + index, SOURCES[key], "")
        for index, key in enumerate(CHATS)
    ]
    conn.executemany(
        "INSERT INTO msgs (id,chat_id,from_id,to_id,type,state,timestamp,timestamp_sent,txt,param)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        baseline + rows,
    )
    conn.commit()
    conn.close()


def _attachment(msg_id: int, ts: int, blob: str, name: str) -> tuple:
    return (msg_id, SELF_CHAT, 1, 1, 60, 26, ts, 0, "", f"f=$BLOBDIR/{blob}\nv={name}")


def _content(lines) -> bytes:
    return "\n".join(lines).encode("utf-8")


# ---------------------------------------------------------------------------
# 4_2 route approval
# ---------------------------------------------------------------------------

CLS42 = e42.DeltaChatRouteApprovalStateEvaluator
FIRST_LINES = CLS42._resolve_line_spec(
    list(e42.FIRST_NOTE_LINE_SPEC), {key: {"text": text} for key, text in SOURCES.items()}
)
SECOND_LINES = list(e42.SECOND_NOTE_LINES)


def _run_42(tmp_path: Path, *, prefix: str, blob_override: dict[str, bytes] | None = None) -> dict[str, bool]:
    first_note = (e42.FIRST_NOTE_TITLE + prefix).encode() + _content(FIRST_LINES) if prefix is not None else _content(FIRST_LINES)
    second_note = (e42.SECOND_NOTE_TITLE + prefix).encode() + _content(SECOND_LINES) if prefix is not None else _content(SECOND_LINES)
    account = tmp_path / "acct"
    blobs = account / "dc.db-blobs"
    blobs.mkdir(parents=True)
    blob_bytes = {"first": first_note, "second": second_note}
    blob_bytes.update(blob_override or {})
    (blobs / "first.markdown").write_bytes(blob_bytes["first"])
    (blobs / "second.markdown").write_bytes(blob_bytes["second"])
    documents = tmp_path / "Documents"
    documents.mkdir()
    fresh = e42.DEFAULT_FSNOTES_BASELINE_MAX_TIMESTAMP + 1000
    for name, payload in ((e42.FIRST_NOTE_NAME, first_note), (e42.SECOND_NOTE_NAME, second_note)):
        (documents / name).write_bytes(payload)
        os.utime(documents / name, (fresh, fresh))
    base = e42.DEFAULT_BASELINE_MAX_TIMESTAMP
    _db(account / "dc.db", [
        (535, SELF_CHAT, 1, 1, 10, 26, base + 100, base + 100, e42.AUTHORED_SUMMARY, ""),
        _attachment(536, base + 200, "first.markdown", e42.FIRST_NOTE_NAME),
        _attachment(537, base + 300, "second.markdown", e42.SECOND_NOTE_NAME),
    ])
    checks, _ = CLS42._evaluate_bound_state(
        db_path=account / "dc.db",
        fsnotes_documents=documents,
        minimum_message_id=e42.DEFAULT_MINIMUM_MESSAGE_ID,
        baseline_max_timestamp=base,
        fsnotes_baseline_max_timestamp=e42.DEFAULT_FSNOTES_BASELINE_MAX_TIMESTAMP,
        sent_state=e42.DEFAULT_SENT_STATE,
        boot_timestamp=0.0,
    )
    return {check["name"]: check["pass"] for check in checks}


@pytest.mark.parametrize("prefix", [None, "", "\n"], ids=["content_only", "title_merged", "title_line"])
def test_42_both_note_renderings_pass_end_to_end(tmp_path, prefix):
    checks = _run_42(tmp_path, prefix=prefix)
    assert all(checks.values()), {name: ok for name, ok in checks.items() if not ok}


def test_42_titled_note_would_fail_a_raw_byte_comparison():
    titled = (e42.FIRST_NOTE_TITLE + "\n").encode() + _content(FIRST_LINES)
    # The pre-fix grader compared these raw bytes with the content-only bytes.
    assert titled != CLS42._expected_bytes(FIRST_LINES)
    assert CLS42._logical_lines(titled) == FIRST_LINES


def test_42_blob_must_equal_the_actual_note_file(tmp_path):
    # Titled note, but the shared blob is the content-only text: not byte-identical.
    checks = _run_42(tmp_path, prefix="\n", blob_override={"first": _content(FIRST_LINES)})
    assert checks["first_note_exact_bytes_and_newlines"] is True
    assert checks["first_saved_attachment"] is False


def test_42_other_prefix_or_trailing_lf_fails():
    wrong = b"Route Gate 0729\n" + _content(FIRST_LINES)
    assert CLS42._logical_lines(wrong) != FIRST_LINES
    assert CLS42._logical_lines(_content(FIRST_LINES) + b"\n") != FIRST_LINES


# ---------------------------------------------------------------------------
# 4_4 route handoff
# ---------------------------------------------------------------------------

CLS44 = e44.DeltaChatRouteHandoffStateEvaluator
_SRC44 = {f"{key}_copy": {"text": text} for key, text in SOURCES.items()}
V1_LINES = CLS44._resolve_line_spec(list(e44.V1_LINE_SPEC), _SRC44)
V2_LINES = CLS44._resolve_line_spec(list(e44.V2_LINE_SPEC), _SRC44)


def _run_44(tmp_path: Path, *, name: str, prefix: str | None, extra_note: str | None = None) -> dict[str, bool]:
    title = b"" if prefix is None else (e44.NOTE_TITLE + prefix).encode()
    v1 = title + _content(V1_LINES)
    v2 = title + _content(V2_LINES)
    account = tmp_path / "acct"
    blobs = account / "dc.db-blobs"
    blobs.mkdir(parents=True)
    (blobs / "v1.markdown").write_bytes(v1)
    (blobs / "v2.markdown").write_bytes(v2)
    documents = tmp_path / "Documents"
    documents.mkdir()
    fresh = e44.DEFAULT_BASELINE_MAX_TIMESTAMP + 5000
    for note_name in filter(None, (name, extra_note)):
        (documents / note_name).write_bytes(v2)
        os.utime(documents / note_name, (fresh, fresh))
    base = e44.DEFAULT_BASELINE_MAX_TIMESTAMP
    _db(account / "dc.db", [
        _attachment(535, base + 100, "v1.markdown", name),
        _attachment(536, base + 200, "v2.markdown", name),
    ])
    checks, _ = CLS44._evaluate_bound_state(
        db_path=account / "dc.db",
        documents=documents,
        minimum_message_id=e44.DEFAULT_MINIMUM_MESSAGE_ID,
        baseline_max_timestamp=base,
        sent_state=e44.DEFAULT_SENT_STATE,
    )
    return {check["name"]: check["pass"] for check in checks}


@pytest.mark.parametrize(
    "name,prefix",
    [
        (e44.NOTE_NAMES[0], None),
        (e44.NOTE_NAMES[1], ""),
        (e44.NOTE_NAMES[1], "\n"),
    ],
    ids=["plain_name_content_only", "title_heading_name_merged", "title_heading_name_title_line"],
)
def test_44_both_documented_renderings_pass_end_to_end(tmp_path, name, prefix):
    checks = _run_44(tmp_path, name=name, prefix=prefix)
    assert all(checks.values()), {check: ok for check, ok in checks.items() if not ok}


def test_44_ambiguous_note_files_or_other_names_fail(tmp_path):
    both = _run_44(tmp_path / "both", name=e44.NOTE_NAMES[1], prefix="\n", extra_note=e44.NOTE_NAMES[0])
    assert both["fsnotes_object_new"] is False
    other = _run_44(tmp_path / "other", name="Handoff Log 0729.markdown", prefix=None)
    assert other["first_saved_attachment"] is False
    assert other["fsnotes_object_new"] is False


def test_44_only_the_explicit_title_prefix_is_stripped():
    body = _content(V1_LINES)
    assert CLS44._strip_app_title(e44.NOTE_TITLE.encode() + body) == body
    assert CLS44._strip_app_title(e44.NOTE_TITLE.encode() + b"\n" + body) == body
    assert CLS44._strip_app_title(b"Handoff Log 0729\n" + body) != body
    assert CLS44._strip_app_title(e44.NOTE_TITLE.encode() + b"\n\n" + body) != body
