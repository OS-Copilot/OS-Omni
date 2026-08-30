"""Evaluate Thunderbird calendar state on macOS via the active profile SQLite store."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


_SCAN_SCRIPT = r'''
import json
import os
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

params = __PARAMS_JSON__
profile_name = str(params.get("profile_name") or "benchprofile.default-release").strip() or "benchprofile.default-release"
profile_dir_override = str(params.get("profile_dir") or "").strip()
reference_time_iso = str(params.get("reference_time_iso") or "").strip()
required = [str(item).strip() for item in params.get("required_titles") or [] if str(item).strip()]
forbidden = [str(item).strip() for item in params.get("forbidden_titles") or [] if str(item).strip()]
recurrence_checks = {
    str(key).strip(): [str(v).lower() for v in value if str(v).strip()]
    for key, value in dict(params.get("recurrence_checks") or {}).items()
    if str(key).strip()
}
event_expectations = {
    str(key).strip(): dict(value or {})
    for key, value in dict(params.get("event_expectations") or {}).items()
    if str(key).strip() and isinstance(value, dict)
}


def parse_reference_time():
    if not reference_time_iso:
        return datetime.now().astimezone()
    raw = reference_time_iso
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed


REFERENCE_TIME = parse_reference_time()
LOCAL_TZ = REFERENCE_TIME.tzinfo or datetime.now().astimezone().tzinfo
WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_clock(raw):
    text = str(raw or "").strip()
    if not text:
        raise ValueError("start_time is required")
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid start_time: {text}")
    return dt_time(hour=int(parts[0]), minute=int(parts[1]))


def resolve_expected_local_start(spec):
    relative_day = str(spec.get("relative_day") or spec.get("date_kind") or "").strip().lower()
    weekday_name = str(spec.get("weekday") or "").strip().lower()
    days_from_today = spec.get("days_from_today")
    start_clock = parse_clock(spec.get("start_time"))
    ref_date = REFERENCE_TIME.date()

    if relative_day == "tomorrow":
        target_date = ref_date + timedelta(days=1)
    elif relative_day == "today":
        target_date = ref_date
    elif relative_day in {"this_week", "current_week"}:
        if weekday_name not in WEEKDAY_INDEX:
            raise ValueError(f"invalid weekday for this_week expectation: {weekday_name}")
        monday = ref_date - timedelta(days=ref_date.weekday())
        target_date = monday + timedelta(days=WEEKDAY_INDEX[weekday_name])
    elif relative_day == "next_week":
        if weekday_name not in WEEKDAY_INDEX:
            raise ValueError(f"invalid weekday for next_week expectation: {weekday_name}")
        monday = ref_date - timedelta(days=ref_date.weekday()) + timedelta(days=7)
        target_date = monday + timedelta(days=WEEKDAY_INDEX[weekday_name])
    elif days_from_today is not None:
        target_date = ref_date + timedelta(days=int(days_from_today))
    else:
        raise ValueError("event expectation needs relative_day/date_kind or days_from_today")

    return datetime.combine(target_date, start_clock, tzinfo=LOCAL_TZ)


def to_epoch_microseconds(dt):
    return int(round(dt.astimezone(timezone.utc).timestamp() * 1000000))


def matches_timestamp(observed, expected, tolerance_seconds):
    if observed is None or expected is None:
        return False
    try:
        observed_int = int(observed)
    except Exception:
        return False
    return abs(observed_int - expected) <= int(tolerance_seconds) * 1000000


def parse_observed_local_dt(raw_value):
    if raw_value is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw_value) / 1000000, timezone.utc).astimezone(LOCAL_TZ)
    except Exception:
        return None


def seconds_since_midnight(dt_value):
    return (dt_value.hour * 3600) + (dt_value.minute * 60) + dt_value.second


def matches_local_clock(observed_dt, target_clock, tolerance_seconds):
    if observed_dt is None or target_clock is None:
        return False
    target_seconds = (target_clock.hour * 3600) + (target_clock.minute * 60)
    return abs(seconds_since_midnight(observed_dt) - target_seconds) <= int(tolerance_seconds)


def recurrence_keyword_matches(keyword, recurrence_text, observed_start_local, weekday_name):
    keyword_text = str(keyword or "").lower().strip()
    if not keyword_text:
        return True
    if keyword_text in recurrence_text:
        return True
    if not keyword_text.startswith("byday="):
        return False
    if observed_start_local is None:
        return False
    requested_days = [
        item.strip().lower()
        for item in keyword_text.removeprefix("byday=").split(",")
        if item.strip()
    ]
    observed_weekday_code = observed_start_local.strftime("%a").upper()[:2]
    if observed_weekday_code.lower() in requested_days:
        return True
    if weekday_name:
        expected_weekday_index = WEEKDAY_INDEX.get(weekday_name)
        if expected_weekday_index is not None and observed_start_local.weekday() == expected_weekday_index:
            return True
    return False


def evaluate_expectation(title, spec, events_by_title, recurrence_by_item, alarms_by_item):
    hits = []
    errors = []
    recurrence_keywords = [str(item).lower() for item in spec.get("recurrence_keywords") or [] if str(item).strip()]
    alarm_keywords = [str(item).lower() for item in spec.get("alarm_keywords") or [] if str(item).strip()]
    tolerance_seconds = int(spec.get("tolerance_seconds", 90) or 90)
    weekday_name = str(spec.get("weekday") or "").strip().lower()

    try:
        needs_absolute_time = any(
            key in spec and spec.get(key) not in (None, "")
            for key in ("relative_day", "date_kind", "days_from_today")
        )
        expected_start_local = resolve_expected_local_start(spec) if needs_absolute_time else None
        expected_start_utc = to_epoch_microseconds(expected_start_local) if expected_start_local else None
        start_clock = parse_clock(spec.get("start_time")) if spec.get("start_time") not in (None, "") else None
        duration_minutes = spec.get("duration_minutes")
        expected_end_local = (
            expected_start_local + timedelta(minutes=int(duration_minutes))
            if expected_start_local and duration_minutes not in (None, "")
            else None
        )
        expected_end_utc = to_epoch_microseconds(expected_end_local) if expected_end_local else None
    except Exception as exc:
        return [], [f"{title}: {exc}"]

    for event in events_by_title.get(title, []):
        recurrence_payload = recurrence_by_item.get(event["id"], [])
        alarm_payload = alarms_by_item.get(event["id"], [])
        recurrence_text = "\n".join(recurrence_payload).lower()
        alarm_text = "\n".join(alarm_payload).lower()
        observed_start_local = parse_observed_local_dt(event.get("event_start"))
        observed_end_local = parse_observed_local_dt(event.get("event_end"))
        checks = {
            "time": True,
            "duration": True,
            "weekday": True,
            "recurrence": True,
            "alarm": True,
        }

        if expected_start_utc is not None:
            checks["time"] = matches_timestamp(event.get("event_start"), expected_start_utc, tolerance_seconds)
        elif start_clock is not None:
            checks["time"] = matches_local_clock(observed_start_local, start_clock, tolerance_seconds)
        if expected_end_utc is not None:
            checks["duration"] = matches_timestamp(event.get("event_end"), expected_end_utc, tolerance_seconds)
        elif duration_minutes not in (None, "") and observed_start_local and observed_end_local:
            observed_minutes = int(round((observed_end_local - observed_start_local).total_seconds() / 60.0))
            checks["duration"] = abs(observed_minutes - int(duration_minutes)) <= 1
        elif duration_minutes not in (None, ""):
            checks["duration"] = False
        if weekday_name:
            expected_weekday_index = WEEKDAY_INDEX.get(weekday_name)
            if expected_weekday_index is None:
                errors.append(f"{title}: invalid weekday: {weekday_name}")
                continue
            checks["weekday"] = (
                observed_start_local is not None
                and observed_start_local.weekday() == expected_weekday_index
            )
        if recurrence_keywords:
            checks["recurrence"] = all(
                recurrence_keyword_matches(
                    keyword,
                    recurrence_text,
                    observed_start_local,
                    weekday_name,
                )
                for keyword in recurrence_keywords
            )
        if alarm_keywords:
            checks["alarm"] = all(keyword in alarm_text for keyword in alarm_keywords)

        if all(checks.values()):
            hits.append(
                {
                    "event": event,
                    "checks": checks,
                    "observed_start_local": observed_start_local.isoformat() if observed_start_local else None,
                    "observed_end_local": observed_end_local.isoformat() if observed_end_local else None,
                    "expected_start_local": expected_start_local.isoformat() if expected_start_local else None,
                    "expected_end_local": expected_end_local.isoformat() if expected_end_local else None,
                    "expected_start_utc": expected_start_utc,
                    "expected_end_utc": expected_end_utc,
                    "recurrence": recurrence_payload,
                    "alarms": alarm_payload,
                }
            )

    return hits, errors


def resolve_profile_dir():
    if profile_dir_override:
        override = Path(os.path.expanduser(profile_dir_override)).resolve()
        if override.exists():
            return override

    direct = Path(os.path.expanduser(f"~/Library/Thunderbird/Profiles/{profile_name}")).resolve()
    if direct.exists():
        return direct

    profiles_root = Path.home() / "Library" / "Thunderbird" / "Profiles"
    if not profiles_root.exists():
        return None

    for candidate in sorted(profiles_root.glob("*.default*")):
        if candidate.is_dir():
            return candidate.resolve()
    return None


profile_dir = resolve_profile_dir()
result = {
    "status": "pass",
    "message": "Thunderbird calendar checks passed",
    "profile_dir": str(profile_dir) if profile_dir else "",
    "db_path": "",
    "required_hits": {},
    "forbidden_hits": {},
    "recurrence_hits": {},
    "event_expectation_hits": {},
    "missing_required": [],
    "forbidden_present": [],
    "missing_recurrence": [],
    "missing_event_expectations": [],
    "event_expectation_errors": [],
    "reference_time_local": REFERENCE_TIME.isoformat(),
    "reference_timezone": str(LOCAL_TZ),
}

if profile_dir is None:
    result["status"] = "error"
    result["message"] = "Unable to locate Thunderbird profile directory"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

db_path = profile_dir / "calendar-data" / "local.sqlite"
result["db_path"] = str(db_path)
if not db_path.exists():
    result["status"] = "error"
    result["message"] = f"Calendar database not found: {db_path}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

temp_root = Path(tempfile.mkdtemp(prefix="tb-calendar-eval-"))
query_db_path = temp_root / "local.sqlite"
for suffix in ("", "-wal", "-shm"):
    source = Path(str(db_path) + suffix)
    if source.exists():
        shutil.copy2(source, Path(str(query_db_path) + suffix))

try:
    conn = sqlite3.connect(f"file:{query_db_path}?mode=ro", uri=True)
except Exception as exc:
    result["status"] = "error"
    result["message"] = f"Failed to open calendar database: {exc}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

try:
    try:
        event_rows = conn.execute(
            """
            SELECT id, cal_id, title, event_start, event_end, event_start_tz, event_end_tz, last_modified
            FROM cal_events
            """
        ).fetchall()
    except Exception:
        event_rows = []
    try:
        recurrence_rows = conn.execute(
            """
            SELECT item_id, icalString
            FROM cal_recurrence
            """
        ).fetchall()
    except Exception:
        recurrence_rows = []
    try:
        alarm_rows = conn.execute(
            """
            SELECT item_id, icalString
            FROM cal_alarms
            """
        ).fetchall()
    except Exception:
        alarm_rows = []
finally:
    conn.close()

events_by_title = defaultdict(list)
for row in event_rows:
    item_id, cal_id, title, event_start, event_end, event_start_tz, event_end_tz, last_modified = row
    title = str(title or "").strip()
    if not title:
        continue
    events_by_title[title].append(
        {
            "id": str(item_id or ""),
            "cal_id": str(cal_id or ""),
            "title": title,
            "event_start": event_start,
            "event_end": event_end,
            "event_start_tz": str(event_start_tz or ""),
            "event_end_tz": str(event_end_tz or ""),
            "last_modified": last_modified,
        }
    )

recurrence_by_item = defaultdict(list)
for item_id, ical_string in recurrence_rows:
    recurrence_by_item[str(item_id or "")].append(str(ical_string or ""))

alarms_by_item = defaultdict(list)
for item_id, ical_string in alarm_rows:
    alarms_by_item[str(item_id or "")].append(str(ical_string or ""))

required_hits = {title: events_by_title.get(title, []) for title in required}
forbidden_hits = {title: events_by_title.get(title, []) for title in forbidden}
recurrence_hits = {}

for title, keywords in recurrence_checks.items():
    hits = []
    for event in events_by_title.get(title, []):
        combined = "\n".join(
            [
                json.dumps(event, ensure_ascii=False),
                *recurrence_by_item.get(event["id"], []),
                *alarms_by_item.get(event["id"], []),
            ]
        ).lower()
        if all(keyword in combined for keyword in keywords):
            hits.append(
                {
                    "event": event,
                    "matched_keywords": list(keywords),
                    "recurrence": recurrence_by_item.get(event["id"], []),
                    "alarms": alarms_by_item.get(event["id"], []),
                }
            )
    recurrence_hits[title] = hits

missing_required = [title for title in required if not required_hits.get(title)]
forbidden_present = [title for title in forbidden if forbidden_hits.get(title)]
missing_recurrence = [title for title in recurrence_checks if not recurrence_hits.get(title)]
event_expectation_hits = {}
event_expectation_errors = []
missing_event_expectations = []

for title, spec in event_expectations.items():
    hits, errors = evaluate_expectation(title, spec, events_by_title, recurrence_by_item, alarms_by_item)
    event_expectation_hits[title] = hits
    event_expectation_errors.extend(errors)
    if not hits:
        missing_event_expectations.append(title)

result["required_hits"] = required_hits
result["forbidden_hits"] = forbidden_hits
result["recurrence_hits"] = recurrence_hits
result["event_expectation_hits"] = event_expectation_hits
result["missing_required"] = missing_required
result["forbidden_present"] = forbidden_present
result["missing_recurrence"] = missing_recurrence
result["missing_event_expectations"] = missing_event_expectations
result["event_expectation_errors"] = event_expectation_errors

if event_expectation_errors:
    result["status"] = "error"
    result["message"] = f"Invalid event expectation config: {event_expectation_errors}"
elif missing_required:
    result["status"] = "fail"
    result["message"] = f"Missing required calendar titles: {missing_required}"
elif forbidden_present:
    result["status"] = "fail"
    result["message"] = f"Forbidden calendar titles still present: {forbidden_present}"
elif missing_recurrence:
    result["status"] = "fail"
    result["message"] = f"Missing recurrence evidence for: {missing_recurrence}"
elif missing_event_expectations:
    result["status"] = "fail"
    result["message"] = f"Missing expected calendar timing/reminder state for: {missing_event_expectations}"

print(json.dumps(result, ensure_ascii=False))
'''


class ThunderbirdCalendarEvaluator(BaseEvaluator):
    """PASS if Thunderbird calendar storage contains the expected event state."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_python_script is required")

        required_titles = [str(item).strip() for item in params.get("required_titles") or [] if str(item).strip()]
        if not required_titles:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation requires params.required_titles")

        script = dedent(_SCAN_SCRIPT).replace("__PARAMS_JSON__", json.dumps(params, ensure_ascii=False))
        try:
            result = controller.run_python_script(script, timeout=int(params.get("timeout", 60) or 60))
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Calendar evaluation failed to execute: {exc}")

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Calendar evaluator returned non-JSON output",
                metadata={"runtime_result": result},
            )

        status_name = str(payload.get("status") or "").strip().lower()
        eval_status = EvalStatus.PASS if status_name == "pass" else EvalStatus.FAIL if status_name == "fail" else EvalStatus.ERROR
        return EvalResult(
            status=eval_status,
            message=str(payload.get("message") or "Thunderbird calendar evaluation completed"),
            metadata=payload,
        )
