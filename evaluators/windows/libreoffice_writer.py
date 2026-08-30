"""Windows LibreOffice Writer evaluators."""

from .scripted_check import WindowsScriptedCheckEvaluator


class LibreOfficeWriterEvaluator(WindowsScriptedCheckEvaluator):
    CHECK_PREFIX = "writer"
