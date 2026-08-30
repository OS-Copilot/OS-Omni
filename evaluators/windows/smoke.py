"""Windows smoke-task evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class SmokeEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "smoke"
