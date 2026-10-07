"""OS-Omni binding for the CUA-Tasks-Review evaluator base.

The reviewed evaluators rely on the check accumulator and helper methods of the
release's ``BaseEvaluator`` (``_record``, ``_context_params``, ...), while the
OS-Omni runners only accept subclasses of :class:`core.evaluation.BaseEvaluator`
returning :class:`core.evaluation.EvalResult`.  This module combines both: the
helpers come from the generated upstream copy, and the result types are the
OS-Omni ones.
"""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator as _OSOmniBaseEvaluator
from core.evaluation import EvalResult, EvalStatus

from . import _upstream_evaluation as _upstream

EvaluationResult = EvalResult


class BaseEvaluator(_upstream.BaseEvaluator, _OSOmniBaseEvaluator):
    """Release evaluator helpers on top of the OS-Omni evaluator contract."""

    def build_result(self, context: Mapping[str, Any] | None = None) -> EvalResult:
        result = super().build_result(context)
        return EvalResult(
            status=result.status_value,
            message=result.message,
            metadata=dict(result.metadata),
        )


__all__ = ["BaseEvaluator", "EvalResult", "EvaluationResult", "EvalStatus"]
