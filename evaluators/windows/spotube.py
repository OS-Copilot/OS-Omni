"""Windows Spotube evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class SpotubeEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "spotube"
