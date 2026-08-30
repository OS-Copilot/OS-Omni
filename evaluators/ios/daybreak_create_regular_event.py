"""Template evaluator for DayBreak create-event task."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class DayBreakCreateRegularEventEvaluator(BaseEvaluator):
    """Check DayBreak calendar DB fields for the created event."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        expected = {
            "summary": str(params.get("expected_summary", "BMK Budget Review")),
            "location": str(params.get("expected_location", "Room 301")),
            "all_day": int(params.get("expected_all_day", 0)),
            "start_local": str(params.get("expected_start_local", "2026-04-16 15:00")),
            "end_local": str(params.get("expected_end_local", "2026-04-16 16:00")),
        }

        # TODO: locate DayBreak calendar DB from context and assert a matching row exists:
        # summary, location, all_day, start_local, end_local.
        return EvalResult(
            status=EvalStatus.UNDETERMINED,
            message="Template evaluator: implement DayBreak calendar DB row validation.",
            metadata={
                "template": True,
                "expected": expected,
            },
        )
