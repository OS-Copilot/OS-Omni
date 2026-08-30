"""Android evaluator for exact text files on shared storage."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class AndroidTextFileEvaluator(BaseEvaluator):
    """Validate that an Android file exists and contains exact text."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.execute_adb is required")

        remote_path = str(params.get("path") or "").strip()
        expected_text = str(params.get("expected_text") or "")
        if not remote_path:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.path is required")

        try:
            exists = str(
                controller.execute_adb(
                    ["shell", f"if [ -f {remote_path!r} ]; then echo EXISTS; else echo MISSING; fi"]
                )
                or ""
            )
            if "EXISTS" not in exists:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Android text file not found: {remote_path}",
                    metadata={"path": remote_path, "exists_output": exists},
                )
            actual = str(controller.execute_adb(["shell", "cat", remote_path]) or "")
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to inspect Android text file: {type(exc).__name__}: {exc}",
                metadata={"path": remote_path},
            )

        if self._normalize(actual) != self._normalize(expected_text):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Android text file content mismatch",
                metadata={
                    "path": remote_path,
                    "expected_text": expected_text,
                    "actual_text": actual,
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Android text file matches expected content",
            metadata={"path": remote_path},
        )

    @staticmethod
    def _normalize(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()
