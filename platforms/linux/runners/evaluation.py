"""Linux evaluator execution helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from core.evaluation import EvalResult, EvalStatus, load_evaluator
from core.evaluation.context import with_task_binding

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluationRunResult:
    """Materialized evaluator execution result."""

    result: EvalResult
    summary: dict[str, Any]


_SCRIPT_METHODS = frozenset({"run_python_script", "run_bash_script"})


def normalize_script_result(result: Any) -> Any:
    """Expose a guest script result under every key the Linux evaluators read.

    The Linux guest runtime answers ``/run_python`` with
    ``{"output", "error", "return_code", "status"}`` and ``/run_bash_script``
    with ``{"output", "error", "returncode", "status"}``, while many vendored
    evaluators read ``returncode``/``stdout``/``stderr``.  Missing aliases are
    added; keys the runtime already returned are never overwritten, so
    evaluators reading ``output``/``return_code`` keep working.
    """

    if not isinstance(result, Mapping):
        return result
    normalized = dict(result)
    code = normalized.get("returncode", normalized.get("return_code"))
    try:
        code = int(code)
    except (TypeError, ValueError):
        status = str(normalized.get("status", "")).strip().lower()
        code = 0 if status == "success" else -1
    normalized.setdefault("returncode", code)
    normalized.setdefault("return_code", code)
    normalized.setdefault("stdout", str(normalized.get("output") or ""))
    normalized.setdefault("output", str(normalized.get("stdout") or ""))
    normalized.setdefault("stderr", str(normalized.get("error") or ""))
    normalized.setdefault("error", str(normalized.get("stderr") or ""))
    return normalized


class EvaluatorControllerView:
    """Delegate to the Linux controller, normalizing guest script results."""

    def __init__(self, controller: Any) -> None:
        self._controller = controller

    @property
    def wrapped_controller(self) -> Any:
        return self.__dict__["_controller"]

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.__dict__["_controller"], name)
        if name in _SCRIPT_METHODS and callable(attr):
            def _call(*args: Any, **kwargs: Any) -> Any:
                return normalize_script_result(attr(*args, **kwargs))

            return _call
        return attr


def wrap_evaluator_controller(controller: Any) -> Any:
    if controller is None or isinstance(controller, EvaluatorControllerView):
        return controller
    return EvaluatorControllerView(controller)


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
        "controller": wrap_evaluator_controller(controller),
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
        context = with_task_binding(context, task)
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
