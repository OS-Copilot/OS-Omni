"""iOS initializer execution helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from core.init import InitResult, InitStatus, load_initializer

logger = logging.getLogger(__name__)


_RETURN_HOME_EXCLUDED_INITIALIZERS = {
    "initializers.ios.add_reminder:addreminderinitializer",
    "initializers.ios.reminder_setup:remindersetupinitializer",
    "initializers.ios.reminder_seed_open_app:reminderseedopenappinitializer",
    "initializers.ios.safari_prepare_open_app:safariprepareopenappinitializer",
}

_RETURN_HOME_EXCLUDED_BUNDLE_IDS = {
    "com.apple.mobilesafari",
    "com.apple.reminders",
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
    """Build the minimal iOS initializer context."""

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


def _bool_param(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _should_return_home_after_initialization(
    *,
    initializer_id: str,
    params: Mapping[str, Any],
) -> bool:
    explicit = params.get("return_home_after_init")
    if explicit is not None:
        return _bool_param(explicit)

    normalized_initializer_id = initializer_id.strip().lower()
    if normalized_initializer_id in _RETURN_HOME_EXCLUDED_INITIALIZERS:
        return False

    bundle_id = str(params.get("bundle_id") or "").strip().lower()
    if bundle_id in _RETURN_HOME_EXCLUDED_BUNDLE_IDS:
        return False

    return True


def _return_home_after_initialization(
    *,
    result: InitResult,
    initializer_id: str,
    params: Mapping[str, Any],
    controller: Any,
    logger_obj: logging.Logger,
) -> InitResult:
    if result.status is not InitStatus.PASS:
        return result

    if not _should_return_home_after_initialization(
        initializer_id=initializer_id,
        params=params,
    ):
        result.metadata["return_home_after_init"] = "skipped"
        return result

    try:
        controller.press_home()
    except Exception as exc:
        logger_obj.exception("Post-initialization return home failed: %s", initializer_id)
        metadata = dict(result.metadata)
        metadata["return_home_after_init"] = "failed"
        metadata["return_home_after_init_error"] = type(exc).__name__
        return InitResult(
            status=InitStatus.ERROR,
            message=(
                "Post-initialization return home failed: "
                f"{type(exc).__name__}: {exc}"
            ),
            metadata=metadata,
        )

    result.metadata["return_home_after_init"] = "done"
    return result


def run_task_initialization(
    *,
    task: Any,
    controller: Any,
    model_id: str,
    run_dir: Path,
    logger_obj: Optional[logging.Logger] = None,
) -> Optional[InitializationRunResult]:
    """Execute the configured initializer."""

    del model_id
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

    result = _return_home_after_initialization(
        result=result,
        initializer_id=init.initializer_id,
        params=dict(init.params or {}),
        controller=controller,
        logger_obj=active_logger,
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
