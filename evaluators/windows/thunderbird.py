"""Windows Thunderbird evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class ThunderbirdEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "thunderbird"
