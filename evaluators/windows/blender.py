"""Windows Blender evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class BlenderEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "blender"
