"""Evaluator that checks the final screenshot for visual confirmation."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class ScreenshotCheckEvaluator(BaseEvaluator):
    """Check that a final screenshot was captured and is non-empty.

    This is a minimal baseline evaluator, useful as a fallback when no
    PowerShell-based validation is available.  More advanced screenshot-based
    evaluation (e.g., OCR or visual diff) can be added as a subclass.
    """

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        final_observation = context.get("final_observation")
        if final_observation is None:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="No final observation available",
            )

        screenshot_data = getattr(final_observation, "screenshot_data", None)
        if not screenshot_data:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Final observation contains no screenshot data",
            )

        params = dict(context.get("params") or {})
        min_size = int(params.get("min_screenshot_bytes", 1000) or 1000)
        if len(screenshot_data) < min_size:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Screenshot too small ({len(screenshot_data)} bytes < {min_size})",
                metadata={"screenshot_bytes": len(screenshot_data)},
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message=f"Screenshot captured ({len(screenshot_data)} bytes)",
            metadata={"screenshot_bytes": len(screenshot_data)},
        )
