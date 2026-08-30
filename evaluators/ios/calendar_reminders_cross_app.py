"""Cross-app evaluator for Calendar + Reminders benchmark tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.ios.calendar_event_state import CalendarEventStateEvaluator
from evaluators.ios.reminder_list_state import ReminderListStateEvaluator


class CalendarRemindersCrossAppEvaluator(BaseEvaluator):
    """Require both Calendar DB state and the final Reminders UI state to match."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        calendar_params = dict(params.get("calendar_params") or {})
        reminder_params = dict(params.get("reminder_params") or {})

        if not calendar_params or not reminder_params:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires non-empty calendar_params and reminder_params",
            )

        calendar_result = self._run_child_evaluator(
            CalendarEventStateEvaluator(),
            context=context,
            params=calendar_params,
        )
        reminder_result = self._run_child_evaluator(
            ReminderListStateEvaluator(),
            context=context,
            params=reminder_params,
        )

        if calendar_result.status is EvalStatus.ERROR or reminder_result.status is EvalStatus.ERROR:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Cross-app Calendar/Reminders evaluation hit an error",
                metadata={
                    "calendar": calendar_result.to_dict(),
                    "reminders": reminder_result.to_dict(),
                },
            )

        if calendar_result.status is not EvalStatus.PASS or reminder_result.status is not EvalStatus.PASS:
            failures: list[str] = []
            if calendar_result.status is not EvalStatus.PASS:
                failures.append(f"Calendar: {calendar_result.message}")
            if reminder_result.status is not EvalStatus.PASS:
                failures.append(f"Reminders: {reminder_result.message}")
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Cross-app Calendar/Reminders state does not match the expected outcome",
                metadata={
                    "failures": failures,
                    "calendar": calendar_result.to_dict(),
                    "reminders": reminder_result.to_dict(),
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Calendar and Reminders both match the expected cross-app outcome",
            metadata={
                "calendar": calendar_result.to_dict(),
                "reminders": reminder_result.to_dict(),
            },
        )

    @staticmethod
    def _run_child_evaluator(
        evaluator: BaseEvaluator,
        *,
        context: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> EvalResult:
        child_context = dict(context)
        child_context["params"] = dict(params)
        return evaluator.evaluate(child_context)
