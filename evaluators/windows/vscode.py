"""Windows VS Code evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class VSCodeEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "vscode"
