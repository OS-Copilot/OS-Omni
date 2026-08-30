"""Windows initializer execution helpers."""

from __future__ import annotations

import logging
import multiprocessing
import os
import queue
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from core.init import InitResult, InitStatus, load_initializer

logger = logging.getLogger(__name__)

DEFAULT_INITIALIZER_TIMEOUT_SECONDS = 180.0
DEFAULT_INITIALIZER_TIMEOUT_RETRIES = 2
INITIALIZER_TIMEOUT_SECONDS_ENV = "HELLOWORLD_WINDOWS_INITIALIZER_TIMEOUT_SECONDS"
INITIALIZER_TIMEOUT_RETRIES_ENV = "HELLOWORLD_WINDOWS_INITIALIZER_TIMEOUT_RETRIES"


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
    """Build the minimal Windows initializer context."""

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


def _env_positive_float(name: str, default: float, active_logger: logging.Logger) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        active_logger.warning("Ignoring invalid %s=%r; using %.0fs", name, raw, default)
        return default
    if value <= 0:
        active_logger.warning("Ignoring non-positive %s=%r; using %.0fs", name, raw, default)
        return default
    return value


def _env_nonnegative_int(name: str, default: int, active_logger: logging.Logger) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        active_logger.warning("Ignoring invalid %s=%r; using %d", name, raw, default)
        return default
    if value < 0:
        active_logger.warning("Ignoring negative %s=%r; using %d", name, raw, default)
        return default
    return value


def _initializer_process_worker(
    initializer_id: str,
    context: dict[str, Any],
    output_queue: multiprocessing.Queue,
) -> None:
    try:
        initializer = load_initializer(initializer_id)
        result = initializer.initialize(context)
        if not isinstance(result, InitResult):
            raise TypeError(
                "initializer.initialize(context) must return InitResult, "
                f"got: {type(result)!r}"
            )
        output_queue.put(
            {
                "kind": "result",
                "status": result.status.value,
                "message": result.message,
                "metadata": dict(result.metadata),
            }
        )
    except Exception as exc:
        output_queue.put(
            {
                "kind": "exception",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
        )


def _run_initializer_once(
    *,
    initializer_id: str,
    context: dict[str, Any],
    timeout_seconds: float,
    attempt: int,
    max_attempts: int,
    active_logger: logging.Logger,
) -> InitResult:
    mp_context = multiprocessing.get_context("spawn" if os.name == "nt" else "fork")
    output_queue = mp_context.Queue(maxsize=1)
    process = mp_context.Process(
        target=_initializer_process_worker,
        args=(initializer_id, context, output_queue),
        daemon=True,
    )

    started_at = time.monotonic()
    process.start()
    process.join(timeout_seconds)
    elapsed = time.monotonic() - started_at

    if process.is_alive():
        active_logger.error(
            "Initializer timed out after %.0fs on attempt %d/%d: %s",
            timeout_seconds,
            attempt,
            max_attempts,
            initializer_id,
        )
        process.terminate()
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        return InitResult(
            status=InitStatus.ERROR,
            message=(
                f"Initializer timed out after {timeout_seconds:.0f}s "
                f"on attempt {attempt}/{max_attempts}: {initializer_id}"
            ),
            metadata={
                "exception_type": "InitializerTimeout",
                "initializer_id": initializer_id,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "timeout_seconds": timeout_seconds,
                "elapsed_seconds": round(elapsed, 3),
            },
        )

    try:
        payload = output_queue.get_nowait()
    except queue.Empty:
        exitcode = process.exitcode
        return InitResult(
            status=InitStatus.ERROR,
            message=f"Initializer process exited without a result (exitcode={exitcode}): {initializer_id}",
            metadata={
                "exception_type": "InitializerProcessExit",
                "initializer_id": initializer_id,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "exitcode": exitcode,
                "elapsed_seconds": round(elapsed, 3),
            },
        )

    if payload.get("kind") == "result":
        metadata = dict(payload.get("metadata") or {})
        metadata.setdefault("initializer_attempt", attempt)
        metadata.setdefault("initializer_max_attempts", max_attempts)
        metadata.setdefault("initializer_elapsed_seconds", round(elapsed, 3))
        return InitResult(
            status=payload.get("status"),
            message=payload.get("message"),
            metadata=metadata,
        )

    exception_type = str(payload.get("exception_type") or "Exception")
    message = str(payload.get("message") or "")
    active_logger.error(
        "Initializer execution failed on attempt %d/%d: %s",
        attempt,
        max_attempts,
        initializer_id,
    )
    return InitResult(
        status=InitStatus.ERROR,
        message=f"{exception_type}: {message}",
        metadata={
            "exception_type": exception_type,
            "initializer_id": initializer_id,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "elapsed_seconds": round(elapsed, 3),
        },
    )


def _run_initializer_with_timeout_retries(
    *,
    initializer_id: str,
    context: dict[str, Any],
    timeout_seconds: float,
    retry_count: int,
    active_logger: logging.Logger,
) -> InitResult:
    max_attempts = 1 + retry_count
    last_result: InitResult | None = None
    for attempt in range(1, max_attempts + 1):
        active_logger.info(
            "Initializer attempt %d/%d: %s (timeout %.0fs)",
            attempt,
            max_attempts,
            initializer_id,
            timeout_seconds,
        )
        result = _run_initializer_once(
            initializer_id=initializer_id,
            context=context,
            timeout_seconds=timeout_seconds,
            attempt=attempt,
            max_attempts=max_attempts,
            active_logger=active_logger,
        )
        last_result = result
        metadata = dict(result.metadata)
        if metadata.get("exception_type") != "InitializerTimeout":
            if attempt > 1:
                metadata["initializer_retried_after_timeout"] = True
                result = InitResult(status=result.status, message=result.message, metadata=metadata)
            return result
        if attempt < max_attempts:
            active_logger.warning(
                "Retrying initializer after timeout (%d/%d): %s",
                attempt,
                max_attempts,
                initializer_id,
            )
            time.sleep(2.0)

    assert last_result is not None
    metadata = dict(last_result.metadata)
    metadata["initializer_retries_exhausted"] = True
    return InitResult(status=last_result.status, message=last_result.message, metadata=metadata)


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
        context = build_initializer_context(
            task=task,
            params=init.params,
            controller=controller,
            run_dir=run_dir,
        )
        result = _run_initializer_with_timeout_retries(
            initializer_id=init.initializer_id,
            context=context,
            timeout_seconds=_env_positive_float(
                INITIALIZER_TIMEOUT_SECONDS_ENV,
                DEFAULT_INITIALIZER_TIMEOUT_SECONDS,
                active_logger,
            ),
            retry_count=_env_nonnegative_int(
                INITIALIZER_TIMEOUT_RETRIES_ENV,
                DEFAULT_INITIALIZER_TIMEOUT_RETRIES,
                active_logger,
            ),
            active_logger=active_logger,
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
