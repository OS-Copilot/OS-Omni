"""Evaluator that validates Linux state through a guest-side command."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class CommandCheckEvaluator(BaseEvaluator):
    """Run one bash command on the guest and validate exit code/stdout."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        command = str(params.get("command") or "").strip()
        if not command:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.command is required")

        timeout = int(params.get("timeout", 15) or 15)
        expected_exit_code = int(params.get("expected_exit_code", 0))
        stdout_contains = str(params.get("stdout_contains") or "").strip()
        stdout_not_contains = str(params.get("stdout_not_contains") or "").strip()

        result = controller.run_bash_script(command, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", ""))

        if returncode != expected_exit_code:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Expected exit code {expected_exit_code}, got {returncode}",
                metadata={"output": output, "returncode": returncode},
            )
        if stdout_contains and stdout_contains not in output:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"stdout does not contain expected text: {stdout_contains}",
                metadata={"output": output, "returncode": returncode},
            )
        if stdout_not_contains and stdout_not_contains in output:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"stdout unexpectedly contains text: {stdout_not_contains}",
                metadata={"output": output, "returncode": returncode},
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Guest-side command check passed",
            metadata={"output": output, "returncode": returncode},
        )
