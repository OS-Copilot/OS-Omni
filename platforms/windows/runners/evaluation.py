"""Windows evaluator execution helpers."""

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
    run_dir: Optional[Path] = None,
    trajectory_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Build the minimal Windows evaluator context."""

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


def _normalize_text_for_exact_check(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _run_supplemental_checks(
    *,
    controller: Any,
    params: Mapping[str, Any],
) -> Optional[EvalResult]:
    checks = params.get("supplemental_checks")
    if not isinstance(checks, Mapping):
        return None

    file_checks = checks.get("files") or []
    if not isinstance(file_checks, list):
        return EvalResult(
            status=EvalStatus.ERROR,
            message="evaluation.params.supplemental_checks.files must be a list",
        )
    powershell_checks = checks.get("powershell") or []
    if not isinstance(powershell_checks, list):
        return EvalResult(
            status=EvalStatus.ERROR,
            message="evaluation.params.supplemental_checks.powershell must be a list",
        )

    checked: list[dict[str, Any]] = []
    for item in file_checks:
        if not isinstance(item, Mapping):
            return EvalResult(status=EvalStatus.ERROR, message="supplemental file check must be an object")
        remote_path = str(item.get("path") or "").strip()
        contains = str(item.get("contains") or "").strip()
        exact_text = str(item.get("exact_text") or "").strip()
        if not remote_path:
            return EvalResult(status=EvalStatus.ERROR, message="supplemental file check missing path")
        if not contains and not exact_text:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"supplemental file check for {remote_path} must set contains or exact_text",
            )

        try:
            raw = controller.get_file(remote_path)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"supplemental file missing or unreadable: {remote_path} ({type(exc).__name__}: {exc})",
                metadata={"supplemental_checks": checked},
            )
        text = raw.decode("utf-8", errors="replace")
        checked.append({"path": remote_path, "bytes": len(raw)})
        if exact_text and _normalize_text_for_exact_check(text) != _normalize_text_for_exact_check(exact_text):
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"supplemental file exact text mismatch: {remote_path}",
                metadata={"supplemental_checks": checked, "actual_text": text[:1000]},
            )
        if contains and contains not in text:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"supplemental file does not contain expected text: {remote_path}",
                metadata={"supplemental_checks": checked, "expected_contains": contains, "actual_text": text[:1000]},
            )

    for index, item in enumerate(powershell_checks, start=1):
        if not isinstance(item, Mapping):
            return EvalResult(status=EvalStatus.ERROR, message="supplemental powershell check must be an object")
        script = str(item.get("script") or "").strip()
        stdout_contains = str(item.get("stdout_contains") or "").strip()
        expected_exit_code = int(item.get("expected_exit_code", 0))
        timeout = int(item.get("timeout", 60) or 60)
        label = str(item.get("label") or f"powershell_{index}").strip()
        if not script:
            return EvalResult(status=EvalStatus.ERROR, message=f"supplemental powershell check {label} missing script")
        if not hasattr(controller, "run_powershell_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_powershell_script is required")
        try:
            result = controller.run_powershell_script(script, timeout=timeout)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"supplemental powershell check {label} failed to run: {type(exc).__name__}: {exc}",
                metadata={"supplemental_checks": checked},
            )
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "") or "")
        error = str(result.get("error", "") or "")
        checked.append({"powershell": label, "returncode": returncode, "output": output[:1000], "error": error[:1000]})
        if returncode != expected_exit_code:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"supplemental powershell check {label} exit code {returncode}, expected {expected_exit_code}",
                metadata={"supplemental_checks": checked},
            )
        if stdout_contains and stdout_contains not in output:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"supplemental powershell check {label} missing expected stdout text: {stdout_contains}",
                metadata={"supplemental_checks": checked},
            )

    return EvalResult(
        status=EvalStatus.PASS,
        message="supplemental checks passed",
        metadata={"supplemental_checks": checked},
    )


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
        if result.status == EvalStatus.PASS:
            supplemental_result = _run_supplemental_checks(
                controller=controller,
                params=dict(evaluation.params or {}),
            )
            if supplemental_result is not None:
                metadata = dict(result.metadata)
                metadata["supplemental"] = dict(supplemental_result.metadata)
                if supplemental_result.status != EvalStatus.PASS:
                    result = EvalResult(
                        status=supplemental_result.status,
                        message=supplemental_result.message,
                        metadata=metadata,
                    )
                else:
                    result = EvalResult(
                        status=result.status,
                        message=result.message,
                        metadata=metadata,
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
