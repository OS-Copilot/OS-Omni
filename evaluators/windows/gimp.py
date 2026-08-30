"""Windows GIMP evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class GimpEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "gimp"
