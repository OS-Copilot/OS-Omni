"""macOS evaluator execution helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from core.benchmark_policy import REPO_ROOT, is_oracle_task_path, resolve_oracle_task_path
from core.evaluation import EvalResult, EvalStatus, load_evaluator
from core.evaluation.context import with_task_binding
from core.specs.types import EvaluationSpec
from platforms.macos.host.core.oracle_specs import load_oracle_spec_from_path

logger = logging.getLogger(__name__)

_ORACLE_EVAL_MODEL_IDS = {
    "macos_script_oracle",
    "macos_spotube_oracle",
    "macos_openshop_oracle",
    "macos_blender_oracle",
}

_LOCAL_EVAL_PATH_PARAM_KEYS = {
    "expected_image_path",
    "expected_path",
    "expected_root",
}


@dataclass(frozen=True)
class EvaluationRunResult:
    """Materialized evaluator execution result."""

    result: EvalResult
    summary: dict[str, Any]


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


def _load_task_payload(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            f"Loading macOS task YAML requires PyYAML. Missing dependency while reading: {path}"
        ) from exc

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Task file must contain an object: {path}")
    return payload


def _evaluation_spec_from_payload(payload: Mapping[str, Any]) -> Optional[EvaluationSpec]:
    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, Mapping):
        return None
    evaluator_id = str(evaluation.get("evaluator_id") or "").strip()
    params = evaluation.get("params") or {}
    if not evaluator_id or not isinstance(params, Mapping):
        return None
    return EvaluationSpec(evaluator_id=evaluator_id, params=dict(params))


def _normalize_eval_params_relative_paths(
    params: Mapping[str, Any],
    *,
    base_dir: Path,
) -> dict[str, Any]:
    normalized = dict(params)
    for key in _LOCAL_EVAL_PATH_PARAM_KEYS:
        raw_value = normalized.get(key)
        raw_text = str(raw_value or "").strip()
        if not raw_text:
            continue
        path = Path(raw_text).expanduser()
        if path.is_absolute():
            continue
        base_candidate = (base_dir / path).resolve()
        repo_candidate = (REPO_ROOT / path).resolve()
        task_macos_candidate = (REPO_ROOT / "tasks" / "v1" / "macos" / path).resolve()
        if base_candidate.exists():
            normalized[key] = str(base_candidate)
        elif repo_candidate.exists():
            normalized[key] = str(repo_candidate)
        elif task_macos_candidate.exists():
            normalized[key] = str(task_macos_candidate)
        elif path.parts and path.parts[0] in {"files", "tasks", "platforms", "configs"}:
            normalized[key] = (
                str(task_macos_candidate)
                if not repo_candidate.exists() and task_macos_candidate.exists()
                else str(repo_candidate)
            )
        else:
            normalized[key] = str(base_candidate)
    return normalized


def resolve_effective_evaluation_spec(task: Any, model_id: str) -> Optional[EvaluationSpec]:
    evaluation = getattr(task, "evaluation", None)
    if evaluation is None or model_id not in _ORACLE_EVAL_MODEL_IDS:
        return evaluation

    source_file = str(getattr(task, "source_file", "") or "").strip()
    if not source_file:
        return evaluation

    source_path = Path(source_file).resolve()
    if is_oracle_task_path(source_path):
        return evaluation

    try:
        raw_spec = _load_task_payload(source_path)
        oracle_path = resolve_oracle_task_path(source_path, raw_spec)
        if not oracle_path.exists():
            return evaluation
        oracle_spec = load_oracle_spec_from_path(oracle_path)
        oracle_evaluation = _evaluation_spec_from_payload(oracle_spec)
        if oracle_evaluation is None:
            return evaluation
        return EvaluationSpec(
            evaluator_id=oracle_evaluation.evaluator_id,
            params=_normalize_eval_params_relative_paths(
                oracle_evaluation.params,
                base_dir=oracle_path.parent,
            ),
        )
    except Exception:
        logger.exception("Failed to resolve macOS oracle evaluator for task: %s", source_file)
        return evaluation


def run_task_evaluation(
    *,
    task: Any,
    build_context: Callable[[], Mapping[str, Any]],
    model_id: str,
    run_dir: Path,
    trajectory_path: Optional[Path] = None,
    logger_obj: Optional[logging.Logger] = None,
) -> Optional[EvaluationRunResult]:
    """Execute the configured evaluator."""

    del run_dir, trajectory_path
    evaluation = resolve_effective_evaluation_spec(task, model_id)
    if evaluation is None:
        return None

    active_logger = logger_obj or logger
    active_logger.info("Running evaluator: %s", evaluation.evaluator_id)
    try:
        raw_context = build_context()
        if not isinstance(raw_context, Mapping):
            raise TypeError(
                "build_context() must return a mapping, "
                f"got: {type(raw_context)!r}"
            )
        context = dict(raw_context)
        context["params"] = dict(evaluation.params)
        context = with_task_binding(context, task)
        active_logger.info("Evaluator context keys: %s", sorted(context.keys()))
        evaluator = load_evaluator(evaluation.evaluator_id)
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
