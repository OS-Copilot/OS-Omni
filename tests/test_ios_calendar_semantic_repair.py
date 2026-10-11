"""Semantic repair pins for the two iOS Calendar tasks.

Independent, device-free fixture checks only. No GUI, no model calls, no
formal logs/results inspected. Three layers:

1. YAML pins: instructions must visibly limit the final seeded directory to
   the four expected task events (``exact_count: 4`` in both tasks, "no
   other events" sentence, device-local times) and only the originally
   unchanged events (Pharmacy/EveningWalk/Commute) may opt in to
   ``exact_description: true``. Edited/new events carry no description
   constraint, absent lists stay plain stale-summary guards, and neither
   task pins a hidden ``timezone`` (device-local reading preserved).
2. Fixture checks: ``IOSCalendarStore.event_matches_spec`` plus the
   ``CalendarEventStateEvaluator`` (with ``list_events`` stubbed to
   in-memory fixtures) must PASS the canonical correct four-event refs and
   FAIL every defect class: extra 5th event (closed-world count), modified
   note on an unchanged event, wrong date/time/location/summary, missing
   event, stale absent summary still present. The default (no opt-in flags)
   must remain legacy open-world/subset behavior.
3. Timezone resolver checks: ``default_timezone_name`` must honor a valid
   ``TZ`` env (Singapore), fall through on an invalid ``TZ``, resolve the
   ``tzinfo.key`` (Los Angeles, DST-independent IANA key), resolve the
   ``/etc/localtime`` zoneinfo symlink (Darwin), and keep the legacy
   ``Asia/Shanghai`` default only when nothing resolves. An invalid
   explicit ``timezone`` must be rejected visibly, never silently adopted.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

import platforms.ios.calendar_store as calendar_store_mod
from core.evaluation import EvalStatus
from evaluators.ios.calendar_event_state import CalendarEventStateEvaluator
from platforms.ios.calendar_store import (
    DEFAULT_TIMEZONE_NAME,
    CalendarEventRecord,
    IOSCalendarStore,
    coerce_event_specs,
    default_timezone_name,
)

REPO = Path(__file__).resolve().parent.parent
UPDATE_YAML = REPO / "tasks" / "v1" / "ios" / "calendar_update_and_create_followup.yaml"
FINALIZE_YAML = REPO / "tasks" / "v1" / "ios" / "calendar_finalize_schedule_with_two_followups.yaml"

SGT = "Asia/Singapore"


def _load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _base_date():
    return datetime.now(ZoneInfo(SGT)).date()


def _record(summary, day_offset, start, end, location="", description="", rowid=1, calendar_id=1):
    return CalendarEventRecord(
        rowid=rowid,
        summary=summary,
        local_date=(_base_date() + timedelta(days=day_offset)).isoformat(),
        start_time=start,
        end_time=end,
        location=location,
        description=description,
        calendar_id=calendar_id,
    )


def _records_for_specs(specs, descriptions=None, start_rowid=1):
    descriptions = descriptions or {}
    return [
        _record(
            spec.summary,
            spec.day_offset,
            spec.start_time,
            spec.end_time,
            location=spec.location,
            description=descriptions.get(spec.summary, ""),
            rowid=start_rowid + index,
        )
        for index, spec in enumerate(specs)
    ]


def _update_specs():
    return coerce_event_specs(_load_yaml(UPDATE_YAML)["evaluation"]["params"]["present_events"])


def _finalize_specs():
    return coerce_event_specs(_load_yaml(FINALIZE_YAML)["evaluation"]["params"]["present_events"])


def _patch_list_events(monkeypatch, all_records):
    def fake(self, summaries=None, *, visible_calendars_only=False):
        records = [
            record for record in all_records
            if not visible_calendars_only or record.calendar_id != 3
        ]
        if summaries is None:
            return list(records)
        wanted = {IOSCalendarStore._normalize_text(item) for item in summaries}
        return [
            record for record in records
            if IOSCalendarStore._normalize_text(record.summary) in wanted
        ]

    monkeypatch.setattr(IOSCalendarStore, "list_events", fake)


def _eval_params(doc, **overrides):
    params = dict(doc["evaluation"]["params"])
    params["db_path"] = "/tmp/nonexistent-calendar-semantic-repair-test.db"
    params["timezone"] = SGT
    params["timeout_seconds"] = 0
    params["poll_interval_seconds"] = 0
    params.update(overrides)
    return params


def _evaluate(monkeypatch, doc, all_records, **overrides):
    _patch_list_events(monkeypatch, all_records)
    evaluator = CalendarEventStateEvaluator()
    return evaluator.evaluate({"controller": None, "params": _eval_params(doc, **overrides)})


# 1. YAML pins ----------------------------------------------------------------

def test_update_yaml_limits_final_directory_to_four():
    doc = _load_yaml(UPDATE_YAML)
    assert doc["init"]["params"]["disable_subscribed_calendars"] is True
    instruction = doc["instruction"]
    assert "exactly these four events" in instruction
    assert "no other events" in instruction
    assert "device-local" in instruction
    for summary in (
        "Bench Volunteer Briefing Updated",
        "Bench Volunteer Debrief",
        "Bench Pharmacy Run",
        "Bench Evening Walk",
    ):
        assert summary in instruction, summary
    params = doc["evaluation"]["params"]
    assert params.get("exact_count") == 4
    assert len(params["present_events"]) == 4
    for spec in params["present_events"]:
        if spec["summary"] in ("Bench Pharmacy Run", "Bench Evening Walk"):
            assert spec.get("exact_description") is True, spec
        else:
            assert spec.get("exact_description") in (None, False), spec
    assert params["absent_summaries"] == ["Bench Volunteer Briefing"]
    assert "timezone" not in params
    assert "timezone" not in doc["init"]["params"]


def test_finalize_yaml_limits_final_directory_to_four():
    doc = _load_yaml(FINALIZE_YAML)
    assert doc["init"]["params"]["disable_subscribed_calendars"] is True
    instruction = doc["instruction"]
    assert "exactly these four events" in instruction
    assert "no other events" in instruction
    assert "device-local" in instruction
    for summary in (
        "Bench Outreach Briefing Final",
        "Bench Outreach Supply Pickup",
        "Bench Outreach Debrief",
        "Bench Commute",
    ):
        assert summary in instruction, summary
    params = doc["evaluation"]["params"]
    assert params.get("exact_count") == 4
    assert len(params["present_events"]) == 4
    for spec in params["present_events"]:
        if spec["summary"] == "Bench Commute":
            assert spec.get("exact_description") is True, spec
        else:
            assert spec.get("exact_description") in (None, False), spec
    assert params["absent_summaries"] == [
        "Bench Outreach Briefing Draft",
        "Bench Outreach Draft Hold",
    ]
    assert "timezone" not in params
    assert "timezone" not in doc["init"]["params"]


# 2. store-level matching -------------------------------------------------------

def test_update_correct_refs_match():
    store = IOSCalendarStore("/tmp/nonexistent-calendar-test.db", timezone_name=SGT)
    for spec, record in zip(_update_specs(), _records_for_specs(_update_specs())):
        assert store.event_matches_spec(record, spec) is True, spec.summary


def test_finalize_correct_refs_match():
    store = IOSCalendarStore("/tmp/nonexistent-calendar-test.db", timezone_name=SGT)
    for spec, record in zip(_finalize_specs(), _records_for_specs(_finalize_specs())):
        assert store.event_matches_spec(record, spec) is True, spec.summary


def test_unchanged_note_modified_fails_under_exact():
    store = IOSCalendarStore("/tmp/nonexistent-calendar-test.db", timezone_name=SGT)
    specs = {spec.summary: spec for spec in _update_specs()}
    pharmacy = specs["Bench Pharmacy Run"]
    assert pharmacy.exact_description is True
    clean = _record("Bench Pharmacy Run", 0, "18:10", "18:30", "Market Street", "", rowid=3)
    noted = _record(
        "Bench Pharmacy Run", 0, "18:10", "18:30", "Market Street",
        "Take with food.", rowid=3,
    )
    assert store.event_matches_spec(clean, pharmacy) is True
    assert store.event_matches_spec(noted, pharmacy) is False


def test_edited_event_description_unconstrained():
    store = IOSCalendarStore("/tmp/nonexistent-calendar-test.db", timezone_name=SGT)
    specs = {spec.summary: spec for spec in _update_specs()}
    updated = specs["Bench Volunteer Briefing Updated"]
    assert updated.exact_description is False
    junk = _record(
        "Bench Volunteer Briefing Updated", 0, "18:15", "19:00", "Cedar Room",
        "Anything the UI exposes is ungraded.", rowid=1,
    )
    assert store.event_matches_spec(junk, updated) is True


def test_default_remains_legacy_subset():
    store = IOSCalendarStore("/tmp/nonexistent-calendar-test.db", timezone_name=SGT)
    (legacy,) = coerce_event_specs([
        {"summary": "Bench Commute", "day_offset": 0,
         "start_time": "18:30", "end_time": "18:50", "location": "Station"}
    ])
    assert legacy.exact_description is False
    extra = _record(
        "Bench Commute", 0, "18:30", "18:50", "Station",
        "Extra notes are accepted without the opt-in.", rowid=4,
    )
    assert store.event_matches_spec(extra, legacy) is True


def test_wrong_date_time_location_summary_fail():
    store = IOSCalendarStore("/tmp/nonexistent-calendar-test.db", timezone_name=SGT)
    (spec,) = coerce_event_specs([
        {"summary": "Bench Commute", "day_offset": 0,
         "start_time": "18:30", "end_time": "18:50", "location": "Station"}
    ])
    assert store.event_matches_spec(
        _record("Bench Commute", 1, "18:30", "18:50", "Station"), spec) is False
    assert store.event_matches_spec(
        _record("Bench Commute", 0, "18:31", "18:50", "Station"), spec) is False
    assert store.event_matches_spec(
        _record("Bench Commute", 0, "18:30", "18:50", "Depot"), spec) is False
    assert store.event_matches_spec(
        _record("bench commute", 0, "18:30", "18:50", "Station"), spec) is False


# 3. evaluator closed-world count -------------------------------------------------

def test_finalize_expected_four_passes(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    result = _evaluate(monkeypatch, doc, _records_for_specs(_finalize_specs()))
    assert result.status == EvalStatus.PASS, result.metadata
    assert result.metadata["event_count"] == 4
    assert result.metadata["expected_event_count"] == 4


def test_update_expected_four_passes(monkeypatch):
    doc = _load_yaml(UPDATE_YAML)
    result = _evaluate(monkeypatch, doc, _records_for_specs(_update_specs()))
    assert result.status == EvalStatus.PASS, result.metadata


def test_extra_fifth_event_fails(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    records = _records_for_specs(_finalize_specs()) + [
        _record("Bench Outreach Spam", 0, "23:00", "23:30", "Lobby", "", rowid=9)
    ]
    result = _evaluate(monkeypatch, doc, records)
    assert result.status == EvalStatus.FAIL, result.metadata
    assert result.metadata["event_count"] == 5
    assert "count_mismatch" in result.metadata


def test_missing_event_fails(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    records = _records_for_specs(_finalize_specs())[:3]
    result = _evaluate(monkeypatch, doc, records)
    assert result.status == EvalStatus.FAIL, result.metadata
    assert result.metadata["event_count"] == 3


def test_unchanged_note_modified_fails_evaluator(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    records = _records_for_specs(
        _finalize_specs(), descriptions={"Bench Commute": "Bring a book."}
    )
    result = _evaluate(monkeypatch, doc, records)
    assert result.status == EvalStatus.FAIL, result.metadata
    assert any("Bench Commute" in item for item in result.metadata["missing_events"])


def test_stale_absent_summary_still_fails(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    records = _records_for_specs(_finalize_specs()) + [
        _record("Bench Outreach Draft Hold", 0, "17:40", "18:00", "Lobby", "", rowid=9)
    ]
    result = _evaluate(monkeypatch, doc, records)
    assert result.status == EvalStatus.FAIL, result.metadata
    assert "Bench Outreach Draft Hold" in result.metadata["unexpected_summaries"]


def test_hidden_system_subscription_does_not_pollute_visible_calendar_result(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    task_records = _records_for_specs(_finalize_specs())
    hidden_system_events = [
        _record(f"System Holiday {i}", 0, "00:00", "23:59", rowid=100+i, calendar_id=3)
        for i in range(122)
    ]
    result = _evaluate(monkeypatch, doc, task_records + hidden_system_events)
    assert result.status == EvalStatus.PASS, result.metadata
    assert result.metadata["event_count"] == 4
    assert result.metadata["visible_calendars_only"] is True


def test_visible_extra_event_still_fails_closed_world_calendar_task(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    records = _records_for_specs(_finalize_specs()) + [
        _record("Unexpected Visible Event", 0, "12:00", "12:30", rowid=99)
    ]
    result = _evaluate(monkeypatch, doc, records)
    assert result.status == EvalStatus.FAIL, result.metadata
    assert result.metadata["event_count"] == 5


def test_required_event_hidden_in_disabled_calendar_does_not_pass(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    records = _records_for_specs(_finalize_specs())
    records[-1] = _record(
        records[-1].summary, 0, records[-1].start_time, records[-1].end_time,
        "Station", rowid=records[-1].rowid, calendar_id=3,
    )
    result = _evaluate(monkeypatch, doc, records)
    assert result.status == EvalStatus.FAIL, result.metadata
    assert result.metadata["event_count"] == 3
    assert any("Bench Commute" in item for item in result.metadata["missing_events"])


def test_absent_flag_retains_legacy_open_world(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    records = _records_for_specs(_finalize_specs()) + [
        _record("Bench Outreach Spam", 0, "23:00", "23:30", "Lobby", "", rowid=9)
    ]
    result = _evaluate(monkeypatch, doc, records, exact_count=None)
    assert result.status == EvalStatus.PASS, result.metadata
    assert "event_count" not in result.metadata


def test_invalid_exact_count_rejected(monkeypatch):
    doc = _load_yaml(FINALIZE_YAML)
    result = _evaluate(
        monkeypatch, doc, _records_for_specs(_finalize_specs()), exact_count="four"
    )
    assert result.status == EvalStatus.ERROR


# 4. timezone resolver --------------------------------------------------------------

def test_valid_tz_env_wins(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Singapore")
    assert default_timezone_name() == "Asia/Singapore"


def test_colon_tz_env_wins(monkeypatch):
    monkeypatch.setenv("TZ", ":Asia/Singapore")
    assert default_timezone_name() == "Asia/Singapore"


def test_invalid_tz_env_falls_through_to_tzinfo_key(monkeypatch):
    monkeypatch.setenv("TZ", "Not/AZone")
    monkeypatch.setattr(os, "readlink", lambda _path: (_ for _ in ()).throw(
        OSError("no symlink")))
    monkeypatch.setattr(
        calendar_store_mod, "datetime", _FakeDateTime("America/Los_Angeles"))
    assert default_timezone_name() == "America/Los_Angeles"


def test_tzinfo_key_used_without_tz_env(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(os, "readlink", lambda _path: (_ for _ in ()).throw(
        OSError("no symlink")))
    monkeypatch.setattr(
        calendar_store_mod, "datetime", _FakeDateTime("Asia/Singapore"))
    assert default_timezone_name() == "Asia/Singapore"


def test_localtime_symlink_resolves_iana_key_with_dst(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(
        calendar_store_mod, "datetime", _FakeDateTime(None))
    monkeypatch.setattr(
        os, "readlink",
        lambda _path: "/var/db/timezone/zoneinfo/America/Los_Angeles")
    assert default_timezone_name() == "America/Los_Angeles"
    zone = ZoneInfo("America/Los_Angeles")
    assert datetime(2026, 7, 1, tzinfo=zone).utcoffset() == timedelta(hours=-7)
    assert datetime(2026, 1, 1, tzinfo=zone).utcoffset() == timedelta(hours=-8)


def test_posix_tz_string_ignored(monkeypatch):
    monkeypatch.setenv("TZ", "EST5EDT,M3.2.0,M11.1.0")
    monkeypatch.setattr(os, "readlink", lambda _path: (_ for _ in ()).throw(
        OSError("no symlink")))
    monkeypatch.setattr(
        calendar_store_mod, "datetime", _FakeDateTime("Asia/Singapore"))
    assert default_timezone_name() == "Asia/Singapore"


def test_keyless_tzinfo_without_symlink_keeps_legacy_fallback(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(
        calendar_store_mod, "datetime", _FakeDateTime(None))
    monkeypatch.setattr(os, "readlink", lambda _path: (_ for _ in ()).throw(
        OSError("no symlink")))
    assert default_timezone_name() == DEFAULT_TIMEZONE_NAME
    assert DEFAULT_TIMEZONE_NAME == "Asia/Shanghai"


def test_invalid_explicit_timezone_rejected_visibly(monkeypatch):
    try:
        IOSCalendarStore("/tmp/nonexistent-calendar-test.db",
                         timezone_name="Mars/Olympus")
    except Exception as exc:
        assert "Mars/Olympus" in str(exc)
    else:  # pragma: no cover - ZoneInfo must reject unknown zones
        raise AssertionError("invalid explicit timezone was silently adopted")
    doc = _load_yaml(FINALIZE_YAML)
    _patch_list_events(monkeypatch, _records_for_specs(_finalize_specs()))
    evaluator = CalendarEventStateEvaluator()
    params = _eval_params(doc, timezone="Mars/Olympus")
    result = evaluator.evaluate({"controller": None, "params": params})
    assert result.status == EvalStatus.ERROR


class _FakeDateTime:
    """Minimal stand-in for the store module's ``datetime`` with a fixed key."""

    def __init__(self, key):
        self._key = key

    def now(self, *args, **kwargs):
        outer = self

        class _Local:
            def astimezone(self, *args, **kwargs):
                return self

            @property
            def tzinfo(self):
                if outer._key is None:
                    return _KeylessTzInfo()
                return _KeyedTzInfo(outer._key)

        return _Local()


class _KeyedTzInfo:
    def __init__(self, key):
        self.key = key


class _KeylessTzInfo:
    pass
