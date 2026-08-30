"""Template evaluator for DayBreak detect-event task."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class DayBreakDetectZoomEventEvaluator(BaseEvaluator):
    """Check that detection output contains all required UI markers."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        expected_texts = list(
            params.get(
                "expected_texts",
                ["Event Detected!", "\U0001F4C5 BMK team sync", "2PM - 2PM", "Zoom"],
            )
        )

        # TODO: parse final UI tree text nodes and assert every expected marker exists.
        return EvalResult(
            status=EvalStatus.UNDETERMINED,
            message="Template evaluator: implement UI-tree marker checks for detect result.",
            metadata={
                "template": True,
                "expected_texts": expected_texts,
            },
        )
