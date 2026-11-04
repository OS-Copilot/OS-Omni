"""Delta Chat 4_3: the Bob Ops forward into Saved Messages, graded from a dc.db fixture.

The reviewed run's Forward -> Saved Messages row kept Bob's sender (from_id 12) and
original timestamp_sent. Builds without that path write a new outgoing row from SELF
with the Forwarded param (``a``). Both count as the forward; a retyped copy of the
text does not.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from evaluators.ios import deltachat_launch_checklist_saved_messages_4_3 as e43

CLS = e43.DeltaChatLaunchChecklistStateEvaluator
BASELINE_TS = e43.DEFAULT_BASELINE_MAX_TIMESTAMP
NOTE_NAME = e43.NOTE_NAMES[0]

BOB = "Bob update 02: ops_launch_green_2026 is the status marker."
MEI = "Mei update 03: search token route_final_blue_1740 should stay in this thread."
NORA = "Nora check: nav_bar_search_token_nora_2606 passes."
BOB_FROM_ID = 12
BOB_SENT = 1781008340


def _note_lines(spec):
    sources = {"bob_copy": {"text": BOB}, "mei_copy": {"text": MEI}, "nora_copy": {"text": NORA}}
    return CLS._resolve_line_spec(list(spec), sources)


def _build(tmp_path: Path, forward_row: dict | None) -> tuple[Path, Path]:
    account = tmp_path / "accounts" / "acct"
    blobs = account / "dc.db-blobs"
    blobs.mkdir(parents=True)
    v1 = "\n".join(_note_lines(e43.V1_LINE_SPEC)).encode()
    v2 = "\n".join(_note_lines(e43.V2_LINE_SPEC)).encode()
    (blobs / "v1.markdown").write_bytes(v1)
    (blobs / "v2.markdown").write_bytes(v2)
    documents = tmp_path / "Documents"
    documents.mkdir()
    note = documents / NOTE_NAME
    note.write_bytes(v2)
    os.utime(note, (BASELINE_TS + 5000, BASELINE_TS + 5000))

    db_path = account / "dc.db"
    conn = sqlite3.connect(db_path)
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
        [
            (10, 100, "Me", "K=1"),
            (12, 100, "Mei Chen", ""),
            (13, 100, "Nora QA", ""),
            (14, 100, "Bob Ops", ""),
        ],
    )
    attachment_param = "f=$BLOBDIR/{blob}\nv=" + NOTE_NAME
    rows = [
        (39, 12, 10, 1, 10, 16, 1781007800, 1781007800, MEI, ""),
        (44, 13, 11, 1, 10, 16, 1781008000, 1781008000, NORA, ""),
        (48, 14, BOB_FROM_ID, 1, 10, 16, BOB_SENT, BOB_SENT, BOB, ""),
        (535, 10, 1, 1, 60, 26, BASELINE_TS + 100, 0, "", attachment_param.format(blob="v1.markdown")),
        (538, 10, 1, 1, 60, 26, BASELINE_TS + 200, 0, "", attachment_param.format(blob="v2.markdown")),
    ]
    if forward_row is not None:
        rows.append((
            540, 10, forward_row["from_id"], 1, 10, forward_row.get("state", 26),
            BASELINE_TS + 300, forward_row["timestamp_sent"], forward_row.get("txt", BOB),
            forward_row.get("param", ""),
        ))
    conn.executemany(
        "INSERT INTO msgs (id,chat_id,from_id,to_id,type,state,timestamp,timestamp_sent,txt,param)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path, documents


def _checks(tmp_path: Path, forward_row: dict | None) -> dict[str, bool]:
    db_path, documents = _build(tmp_path, forward_row)
    checks, _observed = CLS._evaluate_bound_state(
        db_path=db_path,
        documents=documents,
        minimum_message_id=e43.DEFAULT_MINIMUM_MESSAGE_ID,
        baseline_max_timestamp=BASELINE_TS,
        sent_state=e43.DEFAULT_SENT_STATE,
    )
    return {check["name"]: check["pass"] for check in checks}


def test_source_preserving_forward_from_reviewed_build_passes(tmp_path):
    checks = _checks(tmp_path, {"from_id": BOB_FROM_ID, "timestamp_sent": BOB_SENT, "state": 16})
    assert all(checks.values()), checks


def test_outgoing_forward_with_forwarded_param_passes(tmp_path):
    checks = _checks(tmp_path, {"from_id": 1, "timestamp_sent": BASELINE_TS + 301, "param": "a=48"})
    assert all(checks.values()), checks


def test_legacy_forwarded_flag_one_passes(tmp_path):
    checks = _checks(tmp_path, {"from_id": 1, "timestamp_sent": 0, "param": "a=1\nc=1"})
    assert checks["forwarded_bob_source_message"] is True
    assert checks["saved_outputs_business_order"] is True


def test_retyped_bob_text_is_not_a_forward(tmp_path):
    checks = _checks(tmp_path, {"from_id": 1, "timestamp_sent": BASELINE_TS + 301, "param": ""})
    assert checks["forwarded_bob_source_message"] is False
    assert checks["saved_outputs_business_order"] is False


def test_forward_with_other_text_or_missing_forward_fails(tmp_path):
    other = _checks(tmp_path / "other", {"from_id": 1, "timestamp_sent": 0, "param": "a=48", "txt": BOB + " "})
    missing = _checks(tmp_path / "missing", None)
    assert other["forwarded_bob_source_message"] is False
    assert missing["forwarded_bob_source_message"] is False
    assert missing["saved_outputs_business_order"] is False
