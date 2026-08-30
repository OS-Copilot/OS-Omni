"""Windows Chrome evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class ChromeEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "chrome"
