"""Windows LibreOffice Calc evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class LibreOfficeCalcEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "calc"
