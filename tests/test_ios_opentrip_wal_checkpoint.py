"""iOS OpenTrip evaluators: WAL checkpoints during an episode must not break judging.

WebKit keeps the OpenTrip localStorage database in WAL mode.  The evaluators
used to read the pre-episode state from the main database file and replay every
WAL frame on top of it, which is only valid while no checkpoint has happened.
These tests drive a real SQLite WAL database through the checkpoint patterns
SQLite produces (none, passive checkpoint then restart, passive checkpoint with
no later write, truncating checkpoint) and evaluate it end to end through
``evaluate()`` with simulator containers built from the bundled OpenTrip assets.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.cua_review.initializers.ios.opentrip_seed_state import _seeded_state
from evaluators.cua_review.platforms.ios import webview_state
from evaluators.cua_review.platforms.ios.webview_state import (
    checkpointed_frame_count,
    read_wal,
    read_window_seed,
)
import evaluators.ios.opentrip_nr2269_sanya_seabreeze_booking_158915 as nr2269
import evaluators.ios.opentrip_review_flight_hotel_reschedule_234497 as reschedule
import evaluators.ios.opentrip_sanya_parkline_review_mj2158_638214 as parkline

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "local_eval/app_assets/opentrip/assets/public"
TASK = ROOT / "tasks/v1/ios/opentrip_nr2269_sanya_seabreeze_booking_158915.yaml"
KEY = "opentrip.localState.v1"

pytestmark = pytest.mark.skipif(
    not (BUNDLE / "seed-data.js").is_file(), reason="bundled OpenTrip assets are not available"
)


def _canonical_base() -> dict[str, Any]:
    return _seeded_state(read_window_seed(BUNDLE / "seed-data.js", "opentripSeed"))


def _booking(summary: dict[str, Any], created_at: str) -> dict[str, Any]:
    stamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    millis = int(stamp.timestamp() * 1000)
    return {"id": f"OT{millis:013d}", "createdAt": created_at, **json.loads(json.dumps(summary))}


FLIGHT = _booking(nr2269.FLIGHT_EXPECTED_SUMMARY, "2026-08-03T09:50:00.000Z")
HOTEL = _booking(nr2269.HOTEL_EXPECTED_SUMMARY, "2026-08-03T09:55:00.000Z")


def _fingerprint(booking: dict[str, Any]) -> str:
    return nr2269._canonical_json_sha256({k: v for k, v in booking.items() if k not in {"id", "createdAt"}})


@pytest.fixture(autouse=True)
def _synthetic_fingerprints(monkeypatch):
    # The real fingerprints cover the full app-generated booking objects; the
    # WAL handling under test is independent of those payload details.
    monkeypatch.setattr(nr2269, "EXPECTED_FLIGHT_FINGERPRINT", _fingerprint(FLIGHT))
    monkeypatch.setattr(nr2269, "EXPECTED_HOTEL_FINGERPRINT", _fingerprint(HOTEL))


def _with_bookings(base: dict[str, Any], *new: dict[str, Any]) -> dict[str, Any]:
    state = json.loads(json.dumps(base))
    state["bookings"] = [json.loads(json.dumps(item)) for item in new] + state["bookings"]
    return state


class _LiveDatabase:
    """A WAL-mode WebKit-style localStorage database kept open like the app keeps it."""

    def __init__(self, path: Path, base: dict[str, Any]) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA wal_autocheckpoint=0")
        self.conn.execute(
            "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB NOT NULL ON CONFLICT FAIL)"
        )
        self.conn.execute("INSERT INTO ItemTable VALUES (?, ?)", (KEY, self._encode(base)))
        # The initializer's seed write ends with its connection closing, which
        # checkpoints the seed into the main file and empties the WAL.
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    @staticmethod
    def _encode(state: dict[str, Any]) -> bytes:
        return json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-16-le")

    def commit(self, state: dict[str, Any]) -> None:
        self.conn.execute("UPDATE ItemTable SET value = ? WHERE key = ?", (self._encode(state), KEY))

    def checkpoint(self, mode: str) -> None:
        self.conn.execute(f"PRAGMA wal_checkpoint({mode})")

    def close(self) -> None:
        self.conn.close()


def _containers(tmp_path: Path) -> tuple[Path, Path, Path]:
    app = tmp_path / "app"
    (app / "public" / "flights").mkdir(parents=True)
    for name in ("app.js", "seed-data.js"):
        shutil.copy2(BUNDLE / name, app / "public" / name)
    shutil.copy2(BUNDLE / "flights" / "2026-06-12.json", app / "public" / "flights" / "2026-06-12.json")
    data = tmp_path / "data"
    origin_dir = data / "Library/WebKit/com.killt.opentrip/WebsiteData/Default/aaaa/bbbb"
    (origin_dir / "LocalStorage").mkdir(parents=True)

    def component(value: bytes) -> bytes:
        return struct.pack("<I", len(value)) + b"\x01" + value

    record = component(b"capacitor") + component(b"localhost") + b"\x00"
    (origin_dir / "origin").write_bytes(record + record)
    return app, data, origin_dir / "LocalStorage" / "localstorage.sqlite3"


def _evaluate(monkeypatch, app: Path, data: Path):
    monkeypatch.setattr(
        nr2269.OpenTripNr2269SanyaSeabreezeBooking158915Evaluator,
        "_simctl_container",
        staticmethod(lambda udid, bundle_id, kind: app if kind == "app" else data),
    )
    params = dict(yaml.safe_load(TASK.read_text(encoding="utf-8"))["evaluation"]["params"])
    params["udid"] = "SIMULATOR-UDID"
    return nr2269.OpenTripNr2269SanyaSeabreezeBooking158915Evaluator().evaluate({"params": params})


def _checks(result) -> dict[str, dict[str, Any]]:
    return {check["name"]: check for check in result.metadata["checks"]}


def _run(tmp_path, monkeypatch, steps):
    app, data, db_path = _containers(tmp_path)
    base = _canonical_base()
    live = _LiveDatabase(db_path, base)
    try:
        for step in steps:
            if isinstance(step, str):
                live.checkpoint(step)
            else:
                live.commit(step(base))
        return _evaluate(monkeypatch, app, data)
    finally:
        live.close()


AFTER_FLIGHT = lambda base: _with_bookings(base, FLIGHT)  # noqa: E731
AFTER_HOTEL = lambda base: _with_bookings(base, HOTEL, FLIGHT)  # noqa: E731
# The brief states no order between the two bookings: hotel first is as valid.
HOTEL_FIRST = dict(HOTEL, id=FLIGHT["id"], createdAt=FLIGHT["createdAt"])
FLIGHT_SECOND = dict(FLIGHT, id=HOTEL["id"], createdAt=HOTEL["createdAt"])
AFTER_HOTEL_FIRST = lambda base: _with_bookings(base, HOTEL_FIRST)  # noqa: E731
AFTER_FLIGHT_SECOND = lambda base: _with_bookings(base, FLIGHT_SECOND, HOTEL_FIRST)  # noqa: E731


def test_canonical_seed_matches_the_evaluators_baseline_hash() -> None:
    assert nr2269._canonical_json_sha256(_canonical_base()) == nr2269.EXPECTED_BASE_STATE_SHA256


@pytest.mark.parametrize(
    "steps, expected_source, truncated",
    [
        pytest.param([AFTER_FLIGHT, AFTER_HOTEL], "main_database_file", False, id="no-checkpoint"),
        pytest.param([AFTER_FLIGHT, "PASSIVE", AFTER_HOTEL], "canonical_seed_from_app_bundle", True,
                     id="checkpoint-after-first-commit-then-wal-restart"),
        pytest.param([AFTER_FLIGHT, AFTER_HOTEL, "PASSIVE"], "canonical_seed_from_app_bundle", True,
                     id="checkpoint-after-last-commit-wal-not-restarted"),
        pytest.param([AFTER_FLIGHT, AFTER_HOTEL, "TRUNCATE"], "canonical_seed_from_app_bundle", True,
                     id="truncating-checkpoint-after-last-commit"),
        pytest.param([AFTER_HOTEL_FIRST, AFTER_FLIGHT_SECOND], "main_database_file", False,
                     id="hotel-first-no-checkpoint"),
        pytest.param([AFTER_HOTEL_FIRST, AFTER_FLIGHT_SECOND, "TRUNCATE"], "canonical_seed_from_app_bundle", True,
                     id="hotel-first-truncating-checkpoint"),
    ],
)
def test_correct_bookings_pass_with_or_without_checkpoint(tmp_path, monkeypatch, steps, expected_source, truncated):
    result = _run(tmp_path, monkeypatch, steps)

    failures = [(c["name"], c["failure_reason"]) for c in result.metadata.get("failures", [])]
    assert result.status == EvalStatus.PASS, (result.message, failures)
    database = result.metadata["observed"]["database"]
    assert database["baseline_source"] == expected_source
    assert database["history_truncated_by_checkpoint"] is truncated
    assert _checks(result)["baseline_clean_exact"]["observed"]["baseline_source"] == expected_source


def test_checkpointed_frames_are_not_replayed_onto_the_main_file(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, [AFTER_FLIGHT, AFTER_HOTEL, "PASSIVE"])

    database = result.metadata["observed"]["database"]
    assert database["wal_frames_committed"] > 0
    assert database["wal_frames_already_checkpointed"] == database["wal_frames_committed"]
    assert database["wal_commit_count"] == 0


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param([AFTER_FLIGHT], id="hotel-missing"),
        # Hotel committed first but stamped later than the flight committed after it.
        pytest.param([lambda base: _with_bookings(base, HOTEL), AFTER_HOTEL], id="timestamps-disagree-with-commits"),
        pytest.param(
            [lambda base: _with_bookings(base, dict(FLIGHT, note="wrong")), "PASSIVE", AFTER_FLIGHT, AFTER_HOTEL],
            id="corrected-flight-visible-after-checkpoint",
        ),
        pytest.param(
            [lambda base: _with_bookings(base, dict(HOTEL, createdAt=FLIGHT["createdAt"], id=FLIGHT["id"]),
                                         dict(FLIGHT, createdAt=HOTEL["createdAt"], id=HOTEL["id"])),
             "TRUNCATE"],
            id="storage-disagrees-with-timestamps-when-history-checkpointed",
        ),
        pytest.param([lambda base: _with_bookings(base, dict(FLIGHT, id="OT1700000000000",
                                                             createdAt="2023-11-14T22:13:20.000Z")),
                      AFTER_FLIGHT, AFTER_HOTEL], id="stale-booking-outside-window"),
    ],
)
def test_wrong_or_incomplete_work_still_fails(tmp_path, monkeypatch, steps):
    result = _run(tmp_path, monkeypatch, steps)

    assert result.status == EvalStatus.FAIL, result.message


def test_unclean_start_without_any_clean_state_fails(tmp_path, monkeypatch):
    app, data, db_path = _containers(tmp_path)
    junk = _canonical_base()
    junk["session"]["user"]["name"] = "Someone Else"
    live = _LiveDatabase(db_path, junk)
    try:
        live.commit(_with_bookings(junk, FLIGHT))
        live.commit(_with_bookings(junk, HOTEL, FLIGHT))
        result = _evaluate(monkeypatch, app, data)
    finally:
        live.close()
    assert result.status == EvalStatus.FAIL
    assert not _checks(result)["account_binding_exact"]["pass"]


# ---------------------------------------------------------------------------
# webview_state WAL helpers
# ---------------------------------------------------------------------------
def _wal_db(tmp_path: Path) -> _LiveDatabase:
    return _LiveDatabase(tmp_path / "localstorage.sqlite3", {"n": 0, "pad": "x" * 6000})


def test_read_wal_stops_at_frames_of_an_earlier_generation(tmp_path):
    live = _wal_db(tmp_path)
    try:
        live.commit({"n": 1, "pad": "y" * 20000})  # many frames
        live.checkpoint("PASSIVE")
        live.commit({"n": 2})  # restarts the WAL with new salts; old frames remain after it
        wal = read_wal(Path(f"{live.path}-wal"))
    finally:
        live.close()
    assert wal.evidence["wal_header_valid"] is True
    assert wal.evidence["wal_frames_in_file"] > wal.evidence["wal_frames_valid"]
    assert "earlier WAL generation" in wal.evidence["wal_stop_reason"]
    assert all(frame.number <= wal.evidence["wal_frames_committed"] for frame in wal.frames)


def test_checkpointed_prefix_is_detected_by_page_content(tmp_path):
    live = _wal_db(tmp_path)
    try:
        live.commit({"n": 1, "pad": "a" * 9000})
        live.commit({"n": 2, "pad": "b" * 9000})
        wal_before = read_wal(Path(f"{live.path}-wal"))
        main_before = live.path.read_bytes()
        live.checkpoint("PASSIVE")
        wal_after = read_wal(Path(f"{live.path}-wal"))
        main_after = live.path.read_bytes()
    finally:
        live.close()
    assert checkpointed_frame_count(main_before, wal_before) == 0
    assert checkpointed_frame_count(main_after, wal_after) == len(wal_after.frames) > 0


def test_invalid_wal_header_is_ignored_like_sqlite(tmp_path):
    wal_path = tmp_path / "x.sqlite3-wal"
    wal_path.write_bytes(b"\x00" * 64)
    wal = read_wal(wal_path)
    assert wal.frames == ()
    assert "SQLite ignores this WAL" in wal.evidence["wal_stop_reason"]


def test_local_storage_history_finds_baseline_committed_in_the_wal(tmp_path):
    live = _wal_db(tmp_path)
    try:
        live.commit({"n": 0, "pad": "seed"})  # e.g. the seed write still in the WAL
        live.commit({"n": 1})
        live.commit({"n": 2})
        snapshot = tmp_path / "snap" / "localstorage.sqlite3"
        snapshot.parent.mkdir()
        for suffix in ("", "-wal", "-shm"):
            shutil.copy2(f"{live.path}{suffix}", f"{snapshot}{suffix}")
    finally:
        live.close()

    def read(path: Path) -> dict[str, Any]:
        conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        try:
            raw = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (KEY,)).fetchone()[0]
        finally:
            conn.close()
        return json.loads(bytes(raw).decode("utf-16-le"))

    history = webview_state.local_storage_history(
        snapshot, read_state=read, is_baseline=lambda state: state.get("pad") == "seed"
    )
    assert history["evidence"]["baseline_source"] == "wal_commit_1"
    assert [state["n"] for state in history["history"]] == [1, 2]


# ---------------------------------------------------------------------------
# Transition rules of the other two task shapes under truncation (any order)
# ---------------------------------------------------------------------------
WINDOW = (
    datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc),
    datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
)


def _flag_facts(flag_count: int):
    def facts(cls, state, **_kwargs):
        flags = tuple(bool(value) for value in state["flags"])
        assert len(flags) == flag_count
        return {"flags": flags, "anomalies": [], "dynamic": [], "in_window_order_ids": []}

    return classmethod(facts)


@pytest.mark.parametrize(
    "rows, truncated, passed",
    [
        ([(1, 0, 0), (1, 1, 0), (1, 1, 1)], False, True),
        ([(1, 1, 0), (1, 1, 1)], False, False),  # without a checkpoint a missing commit fails
        ([(1, 1, 0), (1, 1, 1)], True, True),
        ([(1, 1, 1)], True, True),
        ([(0, 1, 0), (1, 1, 1)], True, False),  # hotel and flight land in one commit
        ([(0, 1, 0), (1, 1, 0), (1, 1, 1)], False, True),  # review first: no order is required
        ([(0, 0, 1), (1, 0, 1), (1, 1, 1)], False, True),  # flight, hotel, review
        ([(1, 1, 1), (1, 1, 1)], True, False),  # extra commit after completion
    ],
)
def test_parkline_history_offset(monkeypatch, rows, truncated, passed):
    cls = parkline.OpenTripSanyaParklineReviewMj2158638214Evaluator
    monkeypatch.setattr(cls, "_target_facts", _flag_facts(3))
    check, _evidence = cls._evaluate_transaction_history(
        [{"flags": row} for row in rows],
        base_state={},
        window_start=WINDOW[0],
        window_end=WINDOW[1],
        allowed_review_dates=set(),
        history_truncated=truncated,
    )
    assert check["pass"] is passed, check["failure_reason"]


@pytest.mark.parametrize(
    "rows, truncated, passed",
    [
        ([(1, 0, 0, 0), (1, 1, 0, 0), (1, 1, 1, 0), (1, 1, 1, 1)], False, True),
        ([(1, 1, 0, 0), (1, 1, 1, 0), (1, 1, 1, 1)], False, False),
        ([(1, 1, 0, 0), (1, 1, 1, 0), (1, 1, 1, 1)], True, True),
        ([(1, 1, 1, 1)], True, True),
        ([(0, 1, 0, 0), (1, 1, 1, 1)], True, False),  # three effects land in one commit
        ([(0, 0, 0, 1), (0, 0, 1, 1), (0, 1, 1, 1), (1, 1, 1, 1)], False, True),  # reverse order
        ([(1, 0, 1, 0), (1, 1, 1, 1)], True, False),  # hotel absorbed without the flight
    ],
)
def test_reschedule_history_ties_only_for_checkpointed_prefix(monkeypatch, rows, truncated, passed):
    cls = reschedule.OpenTripReviewFlightHotelReschedule234497Evaluator
    monkeypatch.setattr(cls, "_target_facts", _flag_facts(4))
    check, _evidence = cls._evaluate_transaction_history(
        [{"flags": row} for row in rows],
        window_start=WINDOW[0],
        window_end=WINDOW[1],
        allowed_review_dates=set(),
        history_truncated=truncated,
    )
    assert check["pass"] is passed, check["failure_reason"]


# ---------------------------------------------------------------------------
# All four task evaluators read a checkpointed database end to end
# ---------------------------------------------------------------------------
import importlib

ALL_TASKS = {
    "opentrip_nr2269_sanya_seabreeze_booking_158915": "OpenTripNr2269SanyaSeabreezeBooking158915Evaluator",
    "opentrip_sc2306_grand_axis_booking_284952": "OpenTripSc2306GrandAxisBooking284952Evaluator",
    "opentrip_review_flight_hotel_reschedule_234497": "OpenTripReviewFlightHotelReschedule234497Evaluator",
    "opentrip_sanya_parkline_review_mj2158_638214": "OpenTripSanyaParklineReviewMj2158638214Evaluator",
}


@pytest.mark.parametrize("checkpoint", [None, "PASSIVE", "TRUNCATE"])
@pytest.mark.parametrize("module_name", sorted(ALL_TASKS))
def test_every_opentrip_evaluator_handles_checkpointed_history(tmp_path, monkeypatch, module_name, checkpoint):
    module = importlib.import_module(f"evaluators.ios.{module_name}")
    cls = getattr(module, ALL_TASKS[module_name])
    app, data, db_path = _containers(tmp_path)
    monkeypatch.setattr(cls, "_simctl_container", staticmethod(lambda udid, bundle_id, kind: app if kind == "app" else data))
    task = yaml.safe_load((ROOT / "tasks/v1/ios" / f"{module_name}.yaml").read_text(encoding="utf-8"))
    params = dict(task["evaluation"]["params"], udid="SIMULATOR-UDID")
    base = _canonical_base()
    live = _LiveDatabase(db_path, base)
    try:
        # Two app commits that are not the task's target data.
        live.commit(_with_bookings(base, dict(FLIGHT, note="not the requested booking")))
        if checkpoint:
            live.checkpoint(checkpoint)
        live.commit(_with_bookings(base, dict(HOTEL, note="not the requested booking"), dict(FLIGHT, note="x")))
        result = cls().evaluate({"params": params})
    finally:
        live.close()

    assert result.status == EvalStatus.FAIL, result.message  # judged, not an ERROR
    database = result.metadata["observed"]["database"]
    expected_source = "main_database_file" if checkpoint is None else "canonical_seed_from_app_bundle"
    assert database["baseline_source"] == expected_source
    checks = _checks(result)
    baseline_check = next(name for name in checks if name.startswith("baseline_clean"))
    assert checks[baseline_check]["pass"] is True
