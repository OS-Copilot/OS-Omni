"""Windows Draw.io evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class DrawIOEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "drawio"
