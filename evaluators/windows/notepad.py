"""Windows Notepad evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class NotepadEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "notepad"
