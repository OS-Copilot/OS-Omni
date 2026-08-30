"""Linux initializer execution helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from core.init import InitResult, InitStatus, load_initializer
from core.specs.types import InitSpec
from platforms.linux.core.oracle_specs import derive_base_task_id, find_task_path, load_task_spec_from_path

logger = logging.getLogger(__name__)

_GUI_ORACLE_MODEL_IDS = {
    "linux_oracle_wait",
    "gimp_oracle",
    "openshop_oracle",
    "deltachat_oracle",
    "linux_wireshark_oracle",
}


@dataclass(frozen=True)
class InitializationRunResult:
    """Materialized initializer execution result."""

    result: InitResult
    summary: dict[str, Any]


def build_initializer_context(
    *,
    task: Any,
    params: Optional[Mapping[str, Any]],
    controller: Any,
    run_dir: Path,
) -> dict[str, Any]:
    """Build the minimal Linux initializer context."""

    return {
        "task": task,
        "params": dict(params or {}),
        "controller": controller,
        "run_dir": run_dir,
    }


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


def resolve_effective_init_spec(task: Any, model_id: str) -> Optional[InitSpec]:
    init = getattr(task, "init", None)
    if init is None or model_id not in _GUI_ORACLE_MODEL_IDS:
        return init

    source_file = str(getattr(task, "source_file", "") or "").strip()
    if not source_file:
        return init

    try:
        raw_spec = load_task_spec_from_path(source_file)
        raw_init = raw_spec.get("init")
        raw_initializer_id = ""
        if isinstance(raw_init, dict):
            raw_initializer_id = str(raw_init.get("initializer_id") or "").strip()
        if raw_initializer_id.endswith("DesktopSetupInitializer"):
            return init
        base_task_id = derive_base_task_id(raw_spec)
        if not base_task_id:
            return init
        base_task_path = find_task_path(base_task_id)
        if base_task_path is None:
            return init
        base_spec = load_task_spec_from_path(base_task_path)
        base_init = base_spec.get("init")
        if not isinstance(base_init, dict):
            return init
        initializer_id = str(base_init.get("initializer_id") or "").strip()
        params = base_init.get("params") or {}
        if not initializer_id or not isinstance(params, dict):
            return init
        return InitSpec(initializer_id=initializer_id, params=dict(params))
    except Exception:
        logger.exception("Failed to resolve base initializer for oracle task: %s", source_file)
        return init


def run_task_initialization(
    *,
    task: Any,
    controller: Any,
    model_id: str,
    run_dir: Path,
    logger_obj: Optional[logging.Logger] = None,
) -> Optional[InitializationRunResult]:
    """Execute the configured initializer."""

    init = resolve_effective_init_spec(task, model_id)
    if init is None:
        return None

    active_logger = logger_obj or logger
    active_logger.info("Running initializer: %s", init.initializer_id)
    try:
        initializer = load_initializer(init.initializer_id)
        context = build_initializer_context(
            task=task,
            params=init.params,
            controller=controller,
            run_dir=run_dir,
        )
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
