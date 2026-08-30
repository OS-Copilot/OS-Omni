"""Backward-compatible alias for the generic Reminder list-state evaluator."""

from __future__ import annotations

from evaluators.ios.reminder_list_state import ReminderListStateEvaluator


class DeleteSpecificReminderEvaluator(ReminderListStateEvaluator):
    """Compatibility shim for older Reminder delete task imports."""
