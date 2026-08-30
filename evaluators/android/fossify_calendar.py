"""Evaluators for Fossify Calendar benchmark tasks."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any, Mapping

try:
    from zoneinfo import ZoneInfo
except ModuleNotFoundError:  # pragma: no cover - compatibility with older local Python.
    ZoneInfo = None  # type: ignore[assignment]

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


DEFAULT_DATABASE_PATH = "/data/user/0/org.fossify.calendar/databases/events.db"
DEFAULT_TIMEZONE = "UTC"


class FossifyCalendarEventStateEvaluator(BaseEvaluator):
    """Validate Fossify Calendar tasks through Fossify's local events.db."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.execute_adb is required for Fossify Calendar evaluation",
            )

        database_path = str(params.get("database_path") or DEFAULT_DATABASE_PATH).strip()
        timezone_name = str(params.get("timezone") or DEFAULT_TIMEZONE).strip()
        expected_events = [dict(item) for item in (params.get("expected_events") or [])]
        absent_titles = [str(item).strip() for item in (params.get("absent_titles") or []) if str(item).strip()]
        strict_benchmark_titles = bool(params.get("strict_benchmark_titles", True))
        timeout_seconds = float(params.get("timeout_seconds", 10) or 0)
        poll_interval_seconds = float(params.get("poll_interval_seconds", 1) or 0)

        if not expected_events:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.expected_events is required",
            )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_details: dict[str, Any] = {}
        while True:
            attempts += 1
            try:
                events = self._read_events(controller, database_path=database_path)
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to inspect Fossify Calendar events.db: {type(exc).__name__}: {exc}",
                    metadata={"attempts": attempts, "database_path": database_path},
                )

            ok, details = self._validate(
                events,
                expected_events=expected_events,
                absent_titles=absent_titles,
                strict_benchmark_titles=strict_benchmark_titles,
                timezone_name=timezone_name,
            )
            last_details = details
            if ok:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Fossify Calendar event checks passed",
                    metadata={
                        "attempts": attempts,
                        "database_path": database_path,
                        **details,
                    },
                )

            if time.time() >= deadline:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message="Fossify Calendar event checks did not pass",
                    metadata={
                        "attempts": attempts,
                        "database_path": database_path,
                        "validation": last_details,
                        "events_seen": events,
                    },
                )
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

    @staticmethod
    def _read_events(controller: Any, *, database_path: str) -> list[dict[str, Any]]:
        sql = (
            "SELECT id,start_ts,end_ts,title,location,description,flags,type,status "
            "FROM events WHERE status != 0 ORDER BY id;"
        )
        command = f"sqlite3 {database_path} \"{sql}\""
        output = str(controller.execute_adb(["shell", command]) or "")
        rows: list[dict[str, Any]] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) < 9:
                continue
            rows.append(
                {
                    "id": parts[0],
                    "start_ts": parts[1],
                    "end_ts": parts[2],
                    "title": parts[3],
                    "location": parts[4],
                    "description": parts[5],
                    "flags": parts[6],
                    "type": parts[7],
                    "status": parts[8],
                }
            )
        return rows

    def _validate(
        self,
        events: list[dict[str, Any]],
        *,
        expected_events: list[dict[str, Any]],
        absent_titles: list[str],
        strict_benchmark_titles: bool,
        timezone_name: str,
    ) -> tuple[bool, dict[str, Any]]:
        timezone = _timezone_for_name(timezone_name)
        unmatched_expected: list[dict[str, Any]] = []
        matched_event_ids: list[str] = []
        for expected in expected_events:
            match = self._find_expected_match(events, expected=expected, timezone=timezone)
            if match is None:
                unmatched_expected.append(expected)
            else:
                matched_event_ids.append(str(match.get("id") or ""))

        active_titles = [str(event.get("title") or "").strip() for event in events]
        present_absent_titles = [title for title in absent_titles if title in active_titles]

        unexpected_bench_titles: list[str] = []
        if strict_benchmark_titles:
            expected_titles = {str(event.get("title") or "").strip() for event in expected_events}
            allowed_absent = set(absent_titles)
            unexpected_bench_titles = [
                title
                for title in active_titles
                if title.startswith("BMK ") and title not in expected_titles and title not in allowed_absent
            ]

        ok = not unmatched_expected and not present_absent_titles and not unexpected_bench_titles
        return ok, {
            "expected_count": len(expected_events),
            "matched_event_ids": matched_event_ids,
            "unmatched_expected": unmatched_expected,
            "absent_titles_present": present_absent_titles,
            "unexpected_benchmark_titles": unexpected_bench_titles,
            "active_titles": active_titles,
        }

    @classmethod
    def _find_expected_match(
        cls,
        events: list[dict[str, Any]],
        *,
        expected: Mapping[str, Any],
        timezone: dt.tzinfo,
    ) -> dict[str, Any] | None:
        title = str(expected.get("title") or "").strip()
        location = str(expected.get("location") or "").strip()
        description = str(expected.get("description") or "").strip()
        expected_type = expected.get("type")
        expected_start = str(expected.get("start") or "").strip()
        expected_end = str(expected.get("end") or "").strip()
        expected_date = str(expected.get("date") or "").strip()

        for event in events:
            if str(event.get("title") or "").strip() != title:
                continue
            if location and str(event.get("location") or "").strip() != location:
                continue
            if description and str(event.get("description") or "").strip() != description:
                continue
            if expected_type not in (None, "") and str(event.get("type") or "").strip() != str(expected_type).strip():
                continue
            if expected_start and not cls._seconds_matches_datetime(event.get("start_ts"), expected_start, timezone):
                continue
            if expected_end and not cls._seconds_matches_datetime(event.get("end_ts"), expected_end, timezone):
                continue
            if expected_date and not cls._seconds_on_date(event.get("start_ts"), expected_date, timezone):
                continue
            return event
        return None

    @staticmethod
    def _seconds_matches_datetime(actual: Any, expected: str, timezone: dt.tzinfo) -> bool:
        try:
            actual_seconds = int(str(actual or "0"))
        except ValueError:
            return False
        expected_dt = dt.datetime.fromisoformat(expected)
        if expected_dt.tzinfo is None:
            expected_dt = expected_dt.replace(tzinfo=timezone)
        expected_seconds = int(expected_dt.timestamp())
        return abs(actual_seconds - expected_seconds) <= 60

    @staticmethod
    def _seconds_on_date(actual: Any, expected_date: str, timezone: dt.tzinfo) -> bool:
        try:
            actual_seconds = int(str(actual or "0"))
            expected_day = dt.date.fromisoformat(expected_date)
        except (TypeError, ValueError):
            return False
        actual_day = dt.datetime.fromtimestamp(actual_seconds, tz=timezone).date()
        return actual_day == expected_day


def _timezone_for_name(timezone_name: str) -> dt.tzinfo:
    if ZoneInfo is not None:
        return ZoneInfo(timezone_name)
    return dt.timezone.utc
