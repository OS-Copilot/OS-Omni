"""Windows Wireshark evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class WiresharkEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "wireshark"
