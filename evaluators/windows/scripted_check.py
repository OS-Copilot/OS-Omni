"""Reusable Windows evaluators backed by checked-in PowerShell scripts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


_CHECKS_DIR = Path(__file__).resolve().parent / "checks"


def _safe_artifact_name(remote_path: str) -> str:
    text = str(remote_path or "").strip().replace("\\", "/")
    text = re.sub(r"^[A-Za-z]:/", "", text)
    text = text.strip("/").replace("/", "__")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text or "artifact"


class WindowsScriptedCheckEvaluator(BaseEvaluator):
    """Run a named PowerShell check script on the Windows guest."""

    DEFAULT_TIMEOUT = 30
    CHECK_PREFIX = ""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_powershell_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_powershell_script is required")

        params = dict(context.get("params") or {})
        check_id = str(params.get("check_id") or "").strip()
        if not check_id:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.check_id is required")

        if self.CHECK_PREFIX and not check_id.startswith(f"{self.CHECK_PREFIX}_"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"check_id {check_id!r} does not match evaluator prefix {self.CHECK_PREFIX!r}",
            )

        script_path = _CHECKS_DIR / f"{check_id}.ps1"
        if not script_path.is_file():
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"PowerShell check script not found: {script_path}",
                metadata={"check_id": check_id},
            )

        command = script_path.read_text(encoding="utf-8")
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

        metadata = {"check_id": check_id, "output": output, "returncode": returncode}
        artifact_paths = params.get("artifact_paths") or []
        if artifact_paths:
            metadata["artifacts"] = self._snapshot_artifacts(
                controller=controller,
                run_dir=context.get("run_dir"),
                check_id=check_id,
                artifact_paths=artifact_paths,
            )
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

        return EvalResult(
            status=EvalStatus.PASS,
            message=f"Windows {check_id} check passed",
            metadata=metadata,
        )

    @staticmethod
    def _snapshot_artifacts(
        *,
        controller: Any,
        run_dir: Any,
        check_id: str,
        artifact_paths: Any,
    ) -> list[dict[str, Any]]:
        if run_dir is None:
            return [{"status": "skipped", "error": "run_dir not available"}]

        base_dir = Path(run_dir) / "evaluation_artifacts" / check_id
        base_dir.mkdir(parents=True, exist_ok=True)

        snapshots: list[dict[str, Any]] = []
        for item in artifact_paths:
            if isinstance(item, Mapping):
                remote_path = str(item.get("path") or "").strip()
                label = str(item.get("label") or "").strip()
            else:
                remote_path = str(item or "").strip()
                label = ""
            if not remote_path:
                continue

            local_name = _safe_artifact_name(label or remote_path)
            local_path = base_dir / local_name
            try:
                data = controller.get_file(remote_path)
                local_path.write_bytes(data)
                snapshots.append(
                    {
                        "status": "saved",
                        "remote_path": remote_path,
                        "local_path": str(local_path),
                        "bytes": len(data),
                    }
                )
            except Exception as exc:
                missing_path = local_path.with_suffix(local_path.suffix + ".missing.txt")
                missing_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
                snapshots.append(
                    {
                        "status": "missing_or_error",
                        "remote_path": remote_path,
                        "local_path": str(missing_path),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return snapshots
