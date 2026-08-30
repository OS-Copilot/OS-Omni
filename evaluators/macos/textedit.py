"""Evaluate macOS TextEdit plain-text file tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


def _resolve_local_path(raw_path: str, *, task: Any, run_dir: Any) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path

    task_source = getattr(task, "source_file", None)
    if task_source:
        candidate = (Path(task_source).expanduser().resolve().parent / path).resolve()
        if candidate.exists():
            return candidate

    if run_dir is not None:
        candidate = (Path(run_dir) / path).resolve()
        if candidate.exists():
            return candidate

    return (Path.cwd() / path).resolve()


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip("\n")


class TextEditFileEvaluator(BaseEvaluator):
    """Compare a saved guest text file against an expected local fixture."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        task = context.get("task")
        run_dir = context.get("run_dir")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.get_file is required")

        actual_path = str(params.get("actual_path") or "").strip()
        expected_path_raw = str(params.get("expected_path") or "").strip()
        if not actual_path or not expected_path_raw:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="TextEdit evaluation requires actual_path and expected_path",
            )

        expected_path = _resolve_local_path(expected_path_raw, task=task, run_dir=run_dir)
        if not expected_path.exists() or not expected_path.is_file():
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"expected fixture missing: {expected_path}",
            )

        try:
            actual_bytes = controller.get_file(actual_path)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"failed to fetch actual text file: {exc}",
                metadata={"actual_path": actual_path},
            )

        try:
            actual_text = actual_bytes.decode("utf-8")
            expected_text = expected_path.read_text(encoding="utf-8")
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"failed to decode text file: {exc}")

        normalized_actual = _normalize_text(actual_text)
        normalized_expected = _normalize_text(expected_text)
        if normalized_actual == normalized_expected:
            return EvalResult(
                status=EvalStatus.PASS,
                message="TextEdit file matches expected content",
                metadata={
                    "actual_path": actual_path,
                    "expected_path": str(expected_path),
                    "actual_text": normalized_actual,
                    "expected_text": normalized_expected,
                },
            )

        actual_lines = normalized_actual.split("\n") if normalized_actual else []
        expected_lines = normalized_expected.split("\n") if normalized_expected else []
        mismatch = None
        for idx, (expected_line, actual_line) in enumerate(zip(expected_lines, actual_lines), start=1):
            if expected_line != actual_line:
                mismatch = {
                    "line": idx,
                    "expected": expected_line,
                    "actual": actual_line,
                }
                break
        if mismatch is None and len(actual_lines) != len(expected_lines):
            mismatch = {
                "line": min(len(actual_lines), len(expected_lines)) + 1,
                "expected": expected_lines[len(actual_lines)] if len(expected_lines) > len(actual_lines) else "<no line>",
                "actual": actual_lines[len(expected_lines)] if len(actual_lines) > len(expected_lines) else "<no line>",
            }

        message = "TextEdit file content mismatch"
        if mismatch is not None:
            message = (
                f"TextEdit file mismatch at line {mismatch['line']}: "
                f"expected {mismatch['expected']!r}, observed {mismatch['actual']!r}"
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message=message,
            metadata={
                "actual_path": actual_path,
                "expected_path": str(expected_path),
                "actual_text": normalized_actual,
                "expected_text": normalized_expected,
                "mismatch": mismatch,
            },
        )
