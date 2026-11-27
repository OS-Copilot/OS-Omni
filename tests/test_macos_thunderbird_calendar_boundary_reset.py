from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from evaluators.cua_review.initializers.macos.thunderbird_snapshot_app import (
    _build_target_event_reset_script,
)


def _make_calendar_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE cal_events (id TEXT PRIMARY KEY, title TEXT NOT NULL);
            CREATE TABLE cal_properties (item_id TEXT, key TEXT, value TEXT);
            CREATE TABLE cal_alarms (item_id TEXT, icalString TEXT);
            CREATE TABLE cal_recurrence (item_id TEXT, icalString TEXT);
            CREATE TABLE cal_metadata (name TEXT, value TEXT);
            INSERT INTO cal_events VALUES ('stale-budget', 'Budget Approval');
            INSERT INTO cal_events VALUES ('stale-release', 'Release Sync');
            INSERT INTO cal_events VALUES ('keep-unrelated', 'Dentist');
            INSERT INTO cal_properties VALUES ('stale-budget', 'LOCATION', 'Finance Room');
            INSERT INTO cal_properties VALUES ('stale-release', 'LOCATION', 'Launch Room');
            INSERT INTO cal_properties VALUES ('keep-unrelated', 'LOCATION', 'Clinic');
            INSERT INTO cal_alarms VALUES ('stale-budget', '-PT30M');
            INSERT INTO cal_recurrence VALUES ('stale-release', 'FREQ=WEEKLY');
            INSERT INTO cal_metadata VALUES ('unrelated', 'preserve');
            """
        )


def test_target_reset_removes_only_named_events_and_linked_rows(tmp_path: Path) -> None:
    data_root = tmp_path / "Library" / "Thunderbird"
    profile_root = data_root / "Profiles"
    profile = profile_root / "benchprofile.default-release"
    db_path = profile / "calendar-data" / "local.sqlite"
    _make_calendar_db(db_path)
    (data_root / "profiles.ini").write_text(
        "[InstallABC]\nDefault=Profiles/benchprofile.default-release\n",
        encoding="utf-8",
    )

    script = _build_target_event_reset_script(str(profile_root), ["Budget Approval", "Release Sync"])
    run = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    result = json.loads(run.stdout.strip().splitlines()[-1])

    assert result["removed_count"] == 2
    assert set(result["removed_titles"]) == {"Budget Approval", "Release Sync"}
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT title FROM cal_events").fetchall() == [("Dentist",)]
        assert db.execute("SELECT item_id FROM cal_properties").fetchall() == [("keep-unrelated",)]
        assert db.execute("SELECT item_id FROM cal_alarms").fetchall() == []
        assert db.execute("SELECT item_id FROM cal_recurrence").fetchall() == []
        assert db.execute("SELECT value FROM cal_metadata").fetchall() == [("preserve",)]


def test_target_reset_is_noop_when_task_titles_are_absent(tmp_path: Path) -> None:
    data_root = tmp_path / "Library" / "Thunderbird"
    profile_root = data_root / "Profiles"
    profile = profile_root / "benchprofile.default-release"
    db_path = profile / "calendar-data" / "local.sqlite"
    _make_calendar_db(db_path)
    (data_root / "profiles.ini").write_text(
        "[InstallABC]\nDefault=Profiles/benchprofile.default-release\n",
        encoding="utf-8",
    )

    script = _build_target_event_reset_script(str(profile_root), ["Stock Count"])
    run = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    result = json.loads(run.stdout.strip().splitlines()[-1])

    assert result["removed_count"] == 0
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM cal_events").fetchone()[0] == 3
