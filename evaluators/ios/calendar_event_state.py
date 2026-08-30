"""Evaluator for iOS Calendar tasks backed by Calendar.sqlitedb."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.ios.calendar_store import IOSCalendarStore, coerce_event_specs, default_timezone_name


class CalendarEventStateEvaluator(BaseEvaluator):
    DEFAULT_TIMEOUT_SECONDS = 8.0
    DEFAULT_POLL_INTERVAL_SECONDS = 0.5

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        present_events = coerce_event_specs(params.get("present_events"))
        absent_summaries = self._coerce_text_list(params.get("absent_summaries"))
        if not present_events and not absent_summaries:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires present_events or absent_summaries",
            )

        timezone_name = str(params.get("timezone") or default_timezone_name()).strip() or default_timezone_name()
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        try:
            store = self._build_store(controller=controller, params=params, timezone_name=timezone_name)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to resolve Calendar store: {type(exc).__name__}: {exc}",
            )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_records = []
        last_missing: list[str] = []
        last_unexpected: list[str] = []

        wanted_summaries = sorted({*absent_summaries, *(event.summary for event in present_events)})

        while True:
            attempts += 1
            try:
                last_records = store.list_events(wanted_summaries)
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to query Calendar database: {type(exc).__name__}: {exc}",
                )

            matched_by_summary: dict[str, list[Any]] = {}
            for record in last_records:
                matched_by_summary.setdefault(record.summary, []).append(record)

            last_missing = []
            matched_rowids: dict[str, int] = {}
            for spec in present_events:
                candidates = matched_by_summary.get(spec.summary, [])
                matched_record = next((record for record in candidates if store.event_matches_spec(record, spec)), None)
                if matched_record is None:
                    last_missing.append(self._describe_spec(spec))
                    continue
                matched_rowids[spec.summary] = matched_record.rowid

            last_unexpected = [
                summary for summary in absent_summaries if matched_by_summary.get(summary)
            ]

            if not last_missing and not last_unexpected:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Calendar database matches the expected task outcome",
                    metadata={
                        "attempts": attempts,
                        "matched_rowids": matched_rowids,
                        "observed_summaries": [record.summary for record in last_records],
                    },
                )

            if time.time() >= deadline:
                break

            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Calendar database does not match the expected task outcome",
            metadata={
                "attempts": attempts,
                "missing_events": last_missing,
                "unexpected_summaries": last_unexpected,
                "observed_summaries": [record.summary for record in last_records],
            },
        )

    @staticmethod
    def _build_store(controller: Any, params: Mapping[str, Any], timezone_name: str) -> IOSCalendarStore:
        db_path = str(params.get("db_path") or "").strip()
        if db_path:
            return IOSCalendarStore(db_path, timezone_name=timezone_name)

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("Calendar evaluator needs params.db_path or a controller with runtime.udid")
        return IOSCalendarStore.from_simulator(udid, timezone_name=timezone_name)

    @staticmethod
    def _coerce_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        values: list[str] = []
        for item in raw:
            text = " ".join(str(item or "").strip().split())
            if text:
                values.append(text)
        return values

    @staticmethod
    def _describe_spec(spec: Any) -> str:
        return (
            f"{spec.summary} (day_offset={spec.day_offset}, "
            f"{spec.start_time}-{spec.end_time}, location={spec.location or '<any>'})"
        )
