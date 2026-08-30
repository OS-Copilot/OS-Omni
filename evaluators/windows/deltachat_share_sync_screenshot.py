"""Evaluator for the Windows Delta Chat share-sync task."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult
from evaluators.windows.deltachat_send_message import DeltaChatSendMessageEvaluator


class DeltaChatShareSyncScreenshotEvaluator(BaseEvaluator):
    """Alias evaluator that checks multiple GreenMail deliveries (no OCR required)."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        return DeltaChatSendMessageEvaluator().evaluate(context)
