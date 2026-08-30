"""Cross-app initializer for Calendar + Reminders benchmark tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.ios.calendar_seed_open_app import CalendarSeedOpenAppInitializer
from initializers.ios.reminder_seed_open_app import ReminderSeedOpenAppInitializer


class CalendarRemindersCrossAppInitializer(BaseInitializer):
    """Seed Reminders first, then launch Calendar with its seeded events."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        params = dict(context.get("params") or {})
        reminder_params = dict(params.get("reminder_params") or {})
        calendar_params = dict(params.get("calendar_params") or {})

        if not reminder_params or not calendar_params:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires non-empty reminder_params and calendar_params",
            )

        reminder_result = self._run_child_initializer(
            ReminderSeedOpenAppInitializer(),
            context=context,
            params=reminder_params,
        )
        if reminder_result.status is not InitStatus.PASS:
            return InitResult(
                status=reminder_result.status,
                message=f"Reminders initialization failed: {reminder_result.message}",
                metadata={"stage": "reminders", "child_metadata": dict(reminder_result.metadata)},
            )

        calendar_result = self._run_child_initializer(
            CalendarSeedOpenAppInitializer(),
            context=context,
            params=calendar_params,
        )
        if calendar_result.status is not InitStatus.PASS:
            return InitResult(
                status=calendar_result.status,
                message=f"Calendar initialization failed: {calendar_result.message}",
                metadata={"stage": "calendar", "child_metadata": dict(calendar_result.metadata)},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Calendar and Reminders for the cross-app task",
            metadata={
                "stage": "complete",
                "calendar": dict(calendar_result.metadata),
                "reminders": dict(reminder_result.metadata),
            },
        )

    @staticmethod
    def _run_child_initializer(
        initializer: BaseInitializer,
        *,
        context: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> InitResult:
        child_context = dict(context)
        child_context["params"] = dict(params)
        return initializer.initialize(child_context)
