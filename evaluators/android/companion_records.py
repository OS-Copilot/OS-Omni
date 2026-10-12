"""Read-only evaluators for records an agent creates on the companion phone.

* TasksAppItemsEvaluator: tasks in the Tasks app (org.tasks).
* CalendarEventsEvaluator: events in Fossify Calendar.

Both read the app database over adb (``su 0 sqlite3``; the phone's sqlite3 has no JSON
output, so text columns are read as hex). Each expected record must exist exactly once,
and the number of live records must equal the snapshot baseline plus the expected
records, so stray or duplicate entries fail. Times are compared in UTC, the phone's
time zone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

TASKS_DB = "/data/data/org.tasks/databases/database"
CALENDAR_DB = "/data/data/org.fossify.calendar/databases/events.db"


def _rows(controller: Any, db: str, query: str) -> list[list[str]]:
    output = str(controller.execute_adb(["shell", f"su 0 sqlite3 -separator '|' {db} \"{query}\""]) or "")
    if "Error" in output and "|" not in output:
        raise RuntimeError(output.strip())
    return [line.split("|") for line in output.splitlines() if line.strip()]


def _text(hex_value: str) -> str:
    return bytes.fromhex(hex_value).decode("utf-8", "replace")


def _utc(seconds: float, fmt: str) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(fmt)


def _compare(expected: list[dict[str, str]], actual: list[dict[str, str]], baseline: int, live: int) -> dict[str, Any]:
    checks = []
    for item in expected:
        matches = [row for row in actual if row["title"] == item["title"]]
        checks.append({"expected": item, "found": matches, "passed": len(matches) == 1 and matches[0] == item})
    count_ok = live == baseline + len(expected)
    return {"checks": checks, "live_count": live, "expected_count": baseline + len(expected),
            "passed": count_ok and all(check["passed"] for check in checks)}


class TasksAppItemsEvaluator(BaseEvaluator):
    """params: tasks [{title, due: YYYY-MM-DD}], baseline_count (live tasks in the snapshot)."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        try:
            rows = _rows(context.get("controller"), TASKS_DB,
                         "select hex(title), dueDate from tasks where deleted = 0 and completed = 0")
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Tasks database is not readable: {exc}")
        actual = [{"title": _text(title), "due": _utc(int(due) / 1000, "%Y-%m-%d") if int(due or 0) else ""}
                  for title, due in rows]
        expected = [{"title": str(item["title"]), "due": str(item["due"])} for item in params.get("tasks") or []]
        verdict = _compare(expected, actual, int(params.get("baseline_count", 0)), len(actual))
        status = EvalStatus.PASS if verdict["passed"] else EvalStatus.FAIL
        return EvalResult(status=status, message="Tasks app items " + ("match" if verdict["passed"] else "do not match"),
                          metadata=verdict)


class CalendarEventsEvaluator(BaseEvaluator):
    """params: events [{title, start: 'YYYY-MM-DD HH:MM', end: 'YYYY-MM-DD HH:MM'}] in UTC, baseline_count."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        try:
            rows = _rows(context.get("controller"), CALENDAR_DB, "select hex(title), start_ts, end_ts from events")
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Calendar database is not readable: {exc}")
        fmt = "%Y-%m-%d %H:%M"
        actual = [{"title": _text(title), "start": _utc(int(start), fmt), "end": _utc(int(end), fmt)}
                  for title, start, end in rows]
        expected = [{"title": str(item["title"]), "start": str(item["start"]), "end": str(item["end"])}
                    for item in params.get("events") or []]
        verdict = _compare(expected, actual, int(params.get("baseline_count", 0)), len(actual))
        status = EvalStatus.PASS if verdict["passed"] else EvalStatus.FAIL
        return EvalResult(status=status, message="Calendar events " + ("match" if verdict["passed"] else "do not match"),
                          metadata=verdict)
