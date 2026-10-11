#!/usr/bin/env python3
"""Portable headless native-store verifier reference checker for Habit tasks.

Offline audit helper only. Reads an existing Habit SQLite audit copy
read-only, backs it up into a TemporaryDirectory, and runs the native-store
verifier (IOSHabitStore.assert_state with the task YAML's supplied
assert_spec) against manually authored reference records. Never writes the
source database. A separate on-device / GUI preflight is still required;
this script is not a substitute for it.

Use an offline audit copy, never a live database.
"""

import argparse
import copy
import datetime
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from platforms.ios.core.types import load_task_from_file
from platforms.ios.habit_store import IOSHabitStore

TASK_FILES = {
    "manage": "tasks/v1/ios/habit_manage_seeded_habits.yaml",
    "rework": "tasks/v1/ios/habit_rework_seeded_routine.yaml",
}

SCOPE = (
    "Offline native-copy verifier reference only; "
    "separate on-device/GUI preflight still required."
)

# Manually authored from the task instruction text and the unchanged
# Water Plants seed entry. These literals are intentionally written out by
# hand and must not be replaced with a copy of the task's expected
# assert_spec block.
CORRECT_RECORDS = {
    "manage": [
        {"title": "Desk Reset", "motivation": "Clear the desk and inbox before leaving.", "color": "blue"},
        {"title": "Deep Reading", "motivation": "Finish one focused chapter before bed.", "color": "purple"},
        {"title": "Water Plants", "motivation": "Check the kitchen plants after dinner.", "color": "teal"},
        {"title": "After Dinner Walk", "motivation": "Walk the long loop after dinner.", "color": "red"},
        {"title": "Plan Tomorrow", "motivation": "Write tomorrow's top three priorities.", "color": "green"},
    ],
    "rework": [
        {"title": "Studio Reset", "motivation": "Reset the tables and wipe the counters before lunch.", "color": "blue"},
        {"title": "Mobility Reset", "motivation": "Two rounds of shoulder and hip stretches.", "color": "purple"},
        {"title": "Water Plants", "motivation": "Check the window plants every evening.", "color": "green"},
        {"title": "Receipt Review", "motivation": "File every receipt before Sunday.", "color": "orange"},
        {"title": "Pack Tomorrow Bag", "motivation": "Lay out laptop, badge, and charger.", "color": "green"},
    ],
}

WATER_PLANTS_TITLE = "Water Plants"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        required=True,
        type=Path,
        help="Existing Habit SQLite audit copy (opened read-only; never written).",
    )
    parser.add_argument("--task", required=True, choices=sorted(TASK_FILES))
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New output directory for reference JSON records (must not exist yet).",
    )
    args = parser.parse_args()

    source_db = args.db_path.expanduser()
    if not source_db.is_file():
        parser.error(f"--db-path must be an existing file: {source_db}")

    task_path = ROOT / TASK_FILES[args.task]
    task = load_task_from_file(str(task_path))
    task_sha256 = hashlib.sha256(task_path.read_bytes()).hexdigest()
    source_db_sha256 = _sha256_file(source_db)

    # Supplied assert_spec from the task YAML; the verifier checks against this.
    assert_spec = dict(task.evaluation.params.get("assert_spec") or {})
    if not assert_spec:
        parser.error(f"Task {task_path} has no evaluation.params.assert_spec")
    seed_habits = task.init.params.get("seed_spec", {}).get("habits", [])

    correct = copy.deepcopy(CORRECT_RECORDS[args.task])

    wrong_color = copy.deepcopy(correct)
    wrong_color[0]["color"] = "yellow"

    extra = copy.deepcopy(correct) + [
        {"title": "Unrequested Extra", "motivation": "Extra habit not in instruction.", "color": "blue"},
    ]

    mutated = copy.deepcopy(correct)
    for record in mutated:
        if record["title"] == WATER_PLANTS_TITLE:
            record["motivation"] = "Unrequested mutation."
            break

    scenarios = [
        ("initial", seed_habits, "FAIL"),
        ("correct", correct, "PASS"),
        ("wrong-color", wrong_color, "FAIL"),
        ("extra-habit", extra, "FAIL"),
        ("preserved-motivation-mutation", mutated, "FAIL"),
    ]

    args.output.mkdir(parents=True, exist_ok=False)

    # SQLite backup includes committed WAL state without mutating the source DB.
    with tempfile.TemporaryDirectory(prefix="habit_reference_check_") as tmpdir:
        work_db = Path(tmpdir) / "Habit.sqlite"
        source = sqlite3.connect(source_db.resolve().as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(work_db)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        store = IOSHabitStore(work_db)

        for name, records, expected in scenarios:
            store.reset_habits(records)
            # Evaluator-equivalent check: same assert_state entry point the
            # HabitStateEvaluator uses, with the task's supplied assert_spec.
            result = store.assert_state(assert_spec)
            actual = str(result.get("status") or "").upper()
            record = {
                "task_id": task.id,
                "task_sha256": task_sha256,
                "source_db_sha256": source_db_sha256,
                "reference": name,
                "expected": expected,
                "actual": actual,
                "failures": result.get("failures") or [],
                "summary": result.get("summary") or {},
                "habit_count": len(records),
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "scope": SCOPE,
            }
            (args.output / (name + ".json")).write_text(json.dumps(record, indent=2) + "\n")
            assert actual == expected, record
            print(name, actual)


if __name__ == "__main__":
    main()
