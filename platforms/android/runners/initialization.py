"""Android initializer execution helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from core.init import InitResult, InitStatus, load_initializer
from platforms.android.oracle_support import apply_android_oracle_completion, is_android_oracle_model

logger = logging.getLogger(__name__)


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
    """Build the Android initializer context."""

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


def run_task_initialization(
    *,
    task: Any,
    controller: Any,
    model_id: str,
    run_dir: Path,
    logger_obj: Optional[logging.Logger] = None,
) -> Optional[InitializationRunResult]:
    """Execute the configured initializer for an Android task."""

    init = getattr(task, "init", None)
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

    summary = _build_summary(result)
    if result.status == InitStatus.PASS and is_android_oracle_model(model_id):
        try:
            oracle_summary = apply_android_oracle_completion(
                task=task,
                controller=controller,
                run_dir=run_dir,
                logger_obj=active_logger,
            )
            summary.setdefault("metadata", {})["oracle"] = oracle_summary
        except Exception as exc:
            active_logger.exception("Android oracle completion failed: %s", getattr(task, "id", ""))
            result = InitResult(
                status=InitStatus.ERROR,
                message=f"Android oracle completion failed: {type(exc).__name__}: {exc}",
                metadata={"exception_type": type(exc).__name__, "phase": "oracle_completion"},
            )
            summary = _build_summary(result)

    active_logger.info(
        "Initializer result: %s (%s)",
        result.status.value,
        init.initializer_id,
    )
    return InitializationRunResult(
        result=result,
        summary=summary,
    )
