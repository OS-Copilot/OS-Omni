"""Windows cross-application scripted evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class CrossAppEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "cross_app"
