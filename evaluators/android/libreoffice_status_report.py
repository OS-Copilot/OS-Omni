"""Evaluator for Android LibreOffice status_report update task."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_DEBUG_LOG_PATH = Path("debug-9381fa.log")
_DEBUG_SESSION_ID = "9381fa"


def _debug_log(*, run_id: str, hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    payload = {
        "sessionId": _DEBUG_SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _collect_strings(ui_nodes: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(ui_nodes, list):
        return out
    for node in ui_nodes:
        if isinstance(node, dict):
            for key in ("text", "content_description", "content-desc"):
                raw = node.get(key)
                if raw is not None and str(raw).strip():
                    out.append(str(raw))
    return out


class LibreOfficeStatusReportEvaluator(BaseEvaluator):
    """PASS when saved ODT contains completed status and no pending status."""

    DEFAULT_FILENAME = "status_report.odt"
    DEFAULT_REMOTE_CANDIDATES = (
        "/sdcard/Documents",
        "/sdcard/Download",
        "/sdcard/Downloads",
        "/sdcard",
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
        final_observation = context.get("final_observation")
        run_id = str(params.get("debug_run_id") or f"eval-{int(time.time() * 1000)}")

        filename = str(params.get("expected_filename") or self.DEFAULT_FILENAME).strip()
        old_text = str(params.get("old_text") or "Status: Pending").strip()
        new_text = str(params.get("new_text") or "Status: Completed").strip()
        require_filename_visible = bool(params.get("require_filename_visible", False))

        if not filename or not old_text or not new_text:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params expected_filename, old_text, and new_text are required",
            )

        remote_path = self._find_remote_odt(controller=controller, filename=filename)
        # region agent log
        _debug_log(
            run_id=run_id,
            hypothesis_id="H3",
            location="evaluators/android/libreoffice_status_report.py:evaluate",
            message="Resolved remote ODT path for evaluation",
            data={"filename": filename, "remote_path": remote_path},
        )
        # endregion
        if not remote_path:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Could not locate {filename} on device storage",
                metadata={"expected_filename": filename},
            )

        content_xml, local_path = self._pull_content_xml(controller=controller, remote_path=remote_path)
        # region agent log
        _debug_log(
            run_id=run_id,
            hypothesis_id="H1",
            location="evaluators/android/libreoffice_status_report.py:evaluate",
            message="Pulled saved ODT and inspected content.xml markers",
            data={
                "remote_path": remote_path,
                "local_path": local_path,
                "content_xml_size": len(content_xml),
                "contains_old_text": old_text in content_xml if content_xml else False,
                "contains_new_text": new_text in content_xml if content_xml else False,
                "contains_pending_literal": "Status: Pending" in content_xml if content_xml else False,
                "contains_completed_literal": "Status: Completed" in content_xml if content_xml else False,
            },
        )
        # endregion
        if not content_xml:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Failed to read saved ODT content.xml",
                metadata={"remote_path": remote_path, "local_pulled_path": local_path},
            )

        marker_metadata = {
            "remote_path": remote_path,
            "local_pulled_path": local_path,
            "contains_old_text": old_text in content_xml,
            "contains_new_text": new_text in content_xml,
            "old_text_count": content_xml.count(old_text),
            "new_text_count": content_xml.count(new_text),
        }

        if new_text not in content_xml:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Updated text {new_text!r} not found in saved document",
                metadata=marker_metadata,
            )
        if old_text in content_xml:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Old text {old_text!r} still present in saved document",
                metadata=marker_metadata,
            )

        if require_filename_visible:
            ui_nodes = list(getattr(final_observation, "ui_nodes", None) or [])
            ui_strings = _collect_strings(ui_nodes)
            haystack = "\n".join(ui_strings)
            # region agent log
            _debug_log(
                run_id=run_id,
                hypothesis_id="H5",
                location="evaluators/android/libreoffice_status_report.py:evaluate",
                message="Checked filename visibility in final UI tree",
                data={
                    "require_filename_visible": require_filename_visible,
                    "filename_visible": filename in haystack,
                    "ui_string_count": len(ui_strings),
                },
            )
            # endregion
            if filename not in haystack:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Saved content is correct, but {filename!r} not visible in final UI",
                    metadata={"remote_path": remote_path, "local_pulled_path": local_path},
                )

        # region agent log
        _debug_log(
            run_id=run_id,
            hypothesis_id="H4",
            location="evaluators/android/libreoffice_status_report.py:evaluate",
            message="Evaluation pass path reached",
            data={"remote_path": remote_path, "local_path": local_path},
        )
        # endregion
        return EvalResult(
            status=EvalStatus.PASS,
            message="status_report.odt was updated and saved successfully",
            metadata={"remote_path": remote_path, "local_pulled_path": local_path},
        )
