"""Android evaluator execution helpers."""

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


def build_evaluator_context(
    *,
    params: Optional[Mapping[str, Any]],
    controller: Any,
    final_observation: Any,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the Android evaluator context."""

    return {
        "params": dict(params or {}),
        "controller": controller,
        "final_observation": final_observation,
        "run_dir": str(run_dir) if run_dir is not None else None,
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
    """Execute the configured evaluator for an Android task."""

    del model_id, trajectory_path
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
        )
        context = with_task_binding(context, task)
        # Preserve actual end-state independently of the verdict for later audits.
        package = evaluation.params.get('app_package', '')
        if not package:
            app_name = str(getattr(task, 'id', '')).split('.')
            if len(app_name) > 1 and app_name[1].startswith('open'):
                package = 'com.killt.' + app_name[1]
        if package.startswith('com.killt.open') and package != 'com.killt.opendriver':
            try:
                from evaluators.cua_review.platforms.android.webview_devtools import WebViewDevTools
                import json
                page = WebViewDevTools(controller, package)
                snapshot = page.evaluate('JSON.stringify({url:location.href,storage:Object.fromEntries(Object.entries(localStorage))})')
                (run_dir/'end-state.json').write_text(snapshot, encoding='utf-8')
            except Exception as exc:
                (run_dir/'end-state-error.json').write_text(json.dumps({'error':str(exc)}), encoding='utf-8')
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
