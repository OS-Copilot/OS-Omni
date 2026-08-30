"""Evaluator for Android LibreOffice notes append task."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class LibreOfficeNotesAppendEvaluator(BaseEvaluator):
    """PASS when required task lines appear in the saved notes ODT content."""

    DEFAULT_FILENAME = "notes.odt"
    DEFAULT_REMOTE_CANDIDATES = (
        "/sdcard/Documents",
        "/sdcard/Download",
        "/sdcard/Downloads",
        "/sdcard",
    )
    DEFAULT_REQUIRED_LINES = (
        "Task A completed",
        "Task B completed",
        "Task C completed",
    )

    @classmethod
    def _find_remote_odt(cls, *, controller: Any, filename: str) -> str:
        if controller is None or not hasattr(controller, "execute_adb"):
            return ""
        for base in cls.DEFAULT_REMOTE_CANDIDATES:
            remote = f"{base.rstrip('/')}/{filename}"
            out = str(controller.execute_adb(["shell", "ls", remote]) or "").strip()
            if out == remote or out.endswith(filename):
                return remote
        lookup = f"find /sdcard -type f -name '{filename}' 2>/dev/null | head -n 1"
        out = str(controller.execute_adb(["shell", "sh", "-c", lookup]) or "").strip()
        if out.endswith(filename):
            return out
        return ""

    @staticmethod
    def _pull_content_xml(*, controller: Any, remote_path: str) -> tuple[str, str]:
        local_dir = Path.cwd() / "_evaluator"
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / Path(remote_path).name
        controller.execute_adb(["pull", remote_path, str(local_path)])
        if not local_path.exists() or local_path.stat().st_size <= 0:
            return "", str(local_path)
        try:
            with zipfile.ZipFile(local_path, "r") as zf:
                with zf.open("content.xml") as f:
                    content_xml = f.read().decode("utf-8", errors="ignore")
            return content_xml, str(local_path)
        except Exception:
            return "", str(local_path)

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")

        filename = str(params.get("expected_filename") or self.DEFAULT_FILENAME).strip()
        required_lines_raw = params.get("required_lines")
        if isinstance(required_lines_raw, list) and required_lines_raw:
            required_lines = [str(item).strip() for item in required_lines_raw if str(item).strip()]
        else:
            required_lines = list(self.DEFAULT_REQUIRED_LINES)
        require_exact_line_counts = bool(params.get("require_exact_line_counts", True))
        expected_line_count = int(params.get("expected_line_count", 1) or 1)

        if not filename or not required_lines:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params expected_filename and required_lines are required",
            )

        remote_path = self._find_remote_odt(controller=controller, filename=filename)
        if not remote_path:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Could not locate {filename} on device storage",
                metadata={"expected_filename": filename},
            )

        content_xml, local_path = self._pull_content_xml(controller=controller, remote_path=remote_path)
        if not content_xml:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Failed to read saved ODT content.xml",
                metadata={"remote_path": remote_path, "local_pulled_path": local_path},
            )

        missing_lines = [line for line in required_lines if line not in content_xml]
        line_counts = {line: content_xml.count(line) for line in required_lines}
        if missing_lines:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Required task lines not found in saved document: {missing_lines}",
                metadata={
                    "remote_path": remote_path,
                    "local_pulled_path": local_path,
                    "required_lines": required_lines,
                    "missing_lines": missing_lines,
                    "line_counts": line_counts,
                },
            )
        wrong_counts = {
            line: count
            for line, count in line_counts.items()
            if count != expected_line_count
        }
        if require_exact_line_counts and wrong_counts:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    "Required task lines were found, but not exactly once each "
                    f"as requested: {wrong_counts}"
                ),
                metadata={
                    "remote_path": remote_path,
                    "local_pulled_path": local_path,
                    "required_lines": required_lines,
                    "line_counts": line_counts,
                    "expected_line_count": expected_line_count,
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="notes.odt contains all required task lines in saved content",
            metadata={
                "remote_path": remote_path,
                "local_pulled_path": local_path,
                "required_lines": required_lines,
                "line_counts": line_counts,
            },
        )
