"""Windows calendar evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class CalendarEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "calendar"
