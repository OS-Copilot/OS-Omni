"""Generic Windows evaluator backed by an inline PowerShell command."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class PowerShellCheckEvaluator(BaseEvaluator):
    """Run an inline PowerShell check script on the Windows guest."""

    DEFAULT_TIMEOUT = 30

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_powershell_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_powershell_script is required")

        params = dict(context.get("params") or {})
        command = str(params.get("command") or params.get("script") or "").strip()
        if not command:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.command is required")

        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)
        expected_exit_code = int(params.get("expected_exit_code", 0))
        stdout_contains = str(params.get("stdout_contains") or "").strip()
        stdout_not_contains = str(params.get("stdout_not_contains") or "").strip()

        result = controller.run_powershell_script(command, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", ""))
        output_excerpt = output.strip()
        if len(output_excerpt) > 1200:
            output_excerpt = output_excerpt[:1200] + "...<truncated>"

        metadata = {"output": output, "returncode": returncode}
        if returncode != expected_exit_code:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    f"Expected exit code {expected_exit_code}, got {returncode}. "
                    f"Output: {output_excerpt or '<empty>'}"
                ),
                metadata=metadata,
            )
        if "EVAL_RESULT:FAIL" in output:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"stdout contains failure marker. Output: {output_excerpt or '<empty>'}",
                metadata=metadata,
            )
        if stdout_contains and stdout_contains not in output:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    f"stdout does not contain expected text: {stdout_contains}. "
                    f"Output: {output_excerpt or '<empty>'}"
                ),
                metadata=metadata,
            )
        if stdout_not_contains and stdout_not_contains in output:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    f"stdout unexpectedly contains text: {stdout_not_contains}. "
                    f"Output: {output_excerpt or '<empty>'}"
                ),
                metadata=metadata,
            )

        return EvalResult(status=EvalStatus.PASS, message="PowerShell check passed", metadata=metadata)
