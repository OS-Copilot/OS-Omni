"""macOS initializer execution helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from core.benchmark_policy import is_oracle_task_path, resolve_oracle_task_path
from core.init import InitResult, InitStatus, load_initializer
from core.specs.types import InitSpec
from platforms.macos.host.core.oracle_specs import load_oracle_spec_from_path

logger = logging.getLogger(__name__)

_ORACLE_INIT_MODEL_IDS = {"macos_script_oracle", "macos_spotube_oracle"}


@dataclass(frozen=True)
class InitializationRunResult:
    """Materialized initializer execution result."""

    result: InitResult
    summary: dict[str, Any]


def initialization_to_episode_failure_message(
    result: InitResult,
) -> Optional[str]:
    """Convert initializer status to an episode-level failure message."""

    if result.status == InitStatus.PASS:
        return None

    if result.message:
        return result.message

    return f"Initializer returned {result.status.value}"


def _build_summary(result: InitResult) -> dict[str, Any]:
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


def _init_spec_from_payload(payload: Mapping[str, Any]) -> Optional[InitSpec]:
    init = payload.get("init")
    if not isinstance(init, Mapping):
        return None
    initializer_id = str(init.get("initializer_id") or "").strip()
    params = init.get("params") or {}
    if not initializer_id or not isinstance(params, Mapping):
        return None
    return InitSpec(initializer_id=initializer_id, params=dict(params))


def _normalize_init_params_relative_paths(params: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    normalized = dict(params)
    steps = normalized.get("steps")
    if not isinstance(steps, list):
        return normalized

    rewritten_steps: list[Any] = []
    for step in steps:
        if not isinstance(step, Mapping):
            rewritten_steps.append(step)
            continue
        step_dict = dict(step)
        if str(step_dict.get("type") or "").strip() == "upload_file":
            raw_local_path = str(step_dict.get("local_path") or "").strip()
            if raw_local_path:
                local_path = Path(raw_local_path).expanduser()
                if not local_path.is_absolute():
                    step_dict["local_path"] = str((base_dir / local_path).resolve())
        rewritten_steps.append(step_dict)
    normalized["steps"] = rewritten_steps
    return normalized


def resolve_effective_init_spec(task: Any, model_id: str) -> Optional[InitSpec]:
    init = getattr(task, "init", None)
    if init is None or model_id not in _ORACLE_INIT_MODEL_IDS:
        return init

    source_file = str(getattr(task, "source_file", "") or "").strip()
    if not source_file:
        return init

    source_path = Path(source_file).resolve()
    if is_oracle_task_path(source_path):
        return init

    try:
        raw_spec = _load_task_payload(source_path)
        oracle_path = resolve_oracle_task_path(source_path, raw_spec)
        if not oracle_path.exists():
            return init
        oracle_spec = load_oracle_spec_from_path(oracle_path)
        oracle_init = _init_spec_from_payload(oracle_spec)
        if oracle_init is None:
            return init
        return InitSpec(
            initializer_id=oracle_init.initializer_id,
            params=_normalize_init_params_relative_paths(oracle_init.params, base_dir=oracle_path.parent),
        )
    except Exception:
        logger.exception("Failed to resolve macOS oracle initializer for task: %s", source_file)
        return init


def run_task_initialization(
    *,
    task: Any,
    build_context: Callable[[], Mapping[str, Any]],
    model_id: str,
    run_dir: Path,
    logger_obj: Optional[logging.Logger] = None,
) -> Optional[InitializationRunResult]:
    """Execute the configured initializer."""

    del run_dir
    init = resolve_effective_init_spec(task, model_id)
    if init is None:
        return None

    active_logger = logger_obj or logger
    active_logger.info("Running initializer: %s", init.initializer_id)
    try:
        raw_context = build_context()
        if not isinstance(raw_context, Mapping):
            raise TypeError(
                "build_context() must return a mapping, "
                f"got: {type(raw_context)!r}"
            )
        context = dict(raw_context)
        context["params"] = dict(init.params)
        active_logger.info("Initializer context keys: %s", sorted(context.keys()))
        initializer = load_initializer(init.initializer_id)
        result = initializer.initialize(context)
        if not isinstance(result, InitResult):
            raise TypeError(
                "initializer.initialize(context) must return InitResult, "
                f"got: {type(result)!r}"
            )
    except Exception as exc:
        active_logger.exception("Initializer execution failed: %s", init.initializer_id)
        result = InitResult(
            status=InitStatus.ERROR,
            message=f"{type(exc).__name__}: {exc}",
            metadata={"exception_type": type(exc).__name__},
        )

    active_logger.info(
        "Initializer result: %s (%s)",
        result.status.value,
        init.initializer_id,
    )
    return InitializationRunResult(
        result=result,
        summary=_build_summary(result),
    )
