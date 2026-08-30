"""Windows Zotero evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class ZoteroEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "zotero"
