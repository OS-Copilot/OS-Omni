#!/usr/bin/env python3
"""Independent semantic references on a disposable Calendar audit simulator."""
import argparse
import copy
import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.evaluation import load_evaluator
from platforms.ios.calendar_store import IOSCalendarStore
from platforms.ios.core.types import load_task_from_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=["update", "finalize"])
    parser.add_argument("--udid", required=True, help="Disposable audit simulator; never a formal run")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    filename = "calendar_update_and_create_followup.yaml" if args.task == "update" else "calendar_finalize_schedule_with_two_followups.yaml"
    task_path = ROOT / "tasks/v1/ios" / filename
    task = load_task_from_file(str(task_path))
    store = IOSCalendarStore.from_simulator(args.udid, timezone_name="Asia/Singapore")
    args.output.mkdir(parents=True, exist_ok=False)
    # Authored from the instruction and preserved seed, not evaluator output.
    values = (
        [("Bench Volunteer Briefing Updated", 0, "18:15", "19:00", "Cedar Room"),
         ("Bench Volunteer Debrief", 1, "09:30", "10:00", "Cedar Room"),
         ("Bench Pharmacy Run", 0, "18:10", "18:30", "Market Street"),
         ("Bench Evening Walk", 0, "20:00", "20:30", "Riverside")]
        if args.task == "update" else
        [("Bench Outreach Briefing Final", 0, "16:40", "17:25", "Cedar Room"),
         ("Bench Outreach Supply Pickup", 1, "08:45", "09:15", "Market Hall"),
         ("Bench Outreach Debrief", 2, "18:10", "18:50", "Cedar Room"),
         ("Bench Commute", 0, "18:30", "18:50", "Station")]
    )
    correct = [dict(zip(["summary", "day_offset", "start_time", "end_time", "location"], v)) for v in values]
    preserved_index = 2 if args.task == "update" else 3
    mutated = copy.deepcopy(correct)
    mutated[preserved_index]["description"] = "Unrequested mutation"
    wrong_time = copy.deepcopy(correct)
    wrong_time[0]["start_time"] = "12:00"
    extra = correct + [dict(summary="Unrequested extra", day_offset=0, start_time="12:00", end_time="12:10")]
    params = dict(task.evaluation.params, udid=args.udid, timeout_seconds=0)
    try:
        store.disable_subscribed_calendars()
        for name, events, expected in [("correct", correct, "PASS"), ("extra-event", extra, "FAIL"),
                                       ("mutated-unchanged-event", mutated, "FAIL"), ("wrong-time", wrong_time, "FAIL")]:
            store.purge_all_events()
            store.seed_events(events)
            result = load_evaluator(task.evaluation.evaluator_id).evaluate({"task": task, "params": params})
            record = dict(task_id=task.id, task_sha256=hashlib.sha256(task_path.read_bytes()).hexdigest(),
                          reference=name, expected=expected, actual=result.status.value,
                          message=result.message,
                          metadata=result.metadata,
                          visible_event_count=len(store.list_events(visible_calendars_only=True)),
                          physical_event_count=len(store.list_events()),
                          checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          scope="Visible-calendar verifier reference; hidden OS subscription retained separately")
            (args.output / (name + ".json")).write_text(json.dumps(record, indent=2) + "\n")
            assert result.status.value == expected, record
            print(name, result.status.value)
    finally:
        store.purge_all_events()
        store.seed_events(task.init.params["seed_events"])


if __name__ == "__main__":
    main()
