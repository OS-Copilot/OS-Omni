"""Linux evaluator execution helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from core.evaluation import EvalResult, EvalStatus, load_evaluator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluationRunResult:
    """Materialized evaluator execution result."""

    result: EvalResult
    summary: dict[str, Any]


def build_evaluator_context(
    *,
    params: Optional[Mapping[str, Any]],
    controller: Any,
    final_observation: Any,
    run_dir: Optional[Path] = None,
    trajectory_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Build the minimal Linux evaluator context."""

    return {
        "params": dict(params or {}),
        "controller": controller,
        "final_observation": final_observation,
        "run_dir": run_dir,
        "trajectory_path": trajectory_path,
    }


def evaluation_to_episode_outcome(
    result: EvalResult,
) -> tuple[str, Optional[str]]:
    """Convert evaluator status to top-level result status plus message."""

    if result.status == EvalStatus.PASS:
        return "PASS", None
    if result.status == EvalStatus.FAIL:
        return "FAIL", result.message
    if result.message:
        return "ERROR", result.message
    return "ERROR", f"Evaluator returned {result.status.value}"


def _build_summary(result: EvalResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "message": result.message,
        "metadata": dict(result.metadata),
    }


def run_task_evaluation(
    *,
    task: Any,
    controller: Any,
    final_observation: Any,
    model_id: str,
    run_dir: Path,
    trajectory_path: Optional[Path] = None,
    logger_obj: Optional[logging.Logger] = None,
) -> Optional[EvaluationRunResult]:
    """Execute the configured evaluator."""

    del model_id
    evaluation = getattr(task, "evaluation", None)
    if evaluation is None:
        return None

    active_logger = logger_obj or logger
    try:
        evaluator = load_evaluator(evaluation.evaluator_id)
        context = build_evaluator_context(
            params=evaluation.params,
            controller=controller,
            final_observation=final_observation,
            run_dir=run_dir,
            trajectory_path=trajectory_path,
        )
        result = evaluator.evaluate(context)
        if not isinstance(result, EvalResult):
            raise TypeError(
                "evaluator.evaluate(context) must return EvalResult, "
                f"got: {type(result)!r}"
            )
    except Exception as exc:
        active_logger.exception("Evaluator execution failed: %s", evaluation.evaluator_id)
        result = EvalResult(
            status=EvalStatus.ERROR,
            message=f"{type(exc).__name__}: {exc}",
            metadata={"exception_type": type(exc).__name__},
        )

    active_logger.info(
        "Evaluator result: %s (%s)",
        result.status.value,
        evaluation.evaluator_id,
    )
    return EvaluationRunResult(
        result=result,
        summary=_build_summary(result),
    )
