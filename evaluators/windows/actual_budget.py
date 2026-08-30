"""Windows Actual Budget evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class ActualBudgetEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "budget"
