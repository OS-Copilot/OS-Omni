"""Windows LibreOffice Impress evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class LibreOfficeImpressEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "impress"
