"""Workspace-backed evaluator for VS Code desktop tasks on Linux."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class VSCodeWorkspaceEvaluator(BaseEvaluator):
    """Validate VS Code task outcomes by checking workspace files on disk."""

    DEFAULT_TIMEOUT = 20

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        workspace_path = str(params.get("workspace_path") or "").strip()
        file_expectations = params.get("files")
        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)

        if not workspace_path:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.workspace_path is required")
        if not isinstance(file_expectations, list) or not file_expectations:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.files must be a non-empty list")

        script = f"""python3 - <<'PY'
import json
import pathlib

workspace = pathlib.Path({json.dumps(workspace_path, ensure_ascii=False)})
expectations = json.loads({json.dumps(json.dumps(file_expectations, ensure_ascii=False), ensure_ascii=False)})
results = []
for item in expectations:
    rel_path = str(item.get("path") or "")
    abs_path = workspace / rel_path
    result = {{"path": rel_path, "exists": abs_path.exists()}}
    if abs_path.exists():
        result["content"] = abs_path.read_text(encoding="utf-8")
    results.append(result)
print(json.dumps({{"workspace_path": str(workspace), "results": results}}, ensure_ascii=False))
PY"""
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=output or f"guest command failed with exit code {returncode}",
            )

        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"VS Code evaluator returned invalid JSON: {exc}: {output}")

        by_path = {str(item.get("path") or ""): dict(item) for item in payload.get("results") or []}

        try:
            for expected in file_expectations:
                if not isinstance(expected, Mapping):
                    continue
                rel_path = str(expected.get("path") or "")
                actual = by_path.get(rel_path)
                assert actual is not None, f"missing evaluation payload for {rel_path}"
                assert bool(actual.get("exists")), f"expected file to exist: {rel_path}"
                actual_content = str(actual.get("content") or "")
                if "equals" in expected:
                    expected_content = str(expected.get("equals") or "")
                    assert actual_content == expected_content, f"content mismatch for {rel_path}"
                if "contains" in expected:
                    needle = str(expected.get("contains") or "")
                    assert needle in actual_content, f"expected {rel_path} to contain {needle!r}"
                if "json" in expected:
                    actual_json = json.loads(actual_content)
                    expected_json = expected.get("json")
                    assert actual_json == expected_json, f"JSON mismatch for {rel_path}"
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=payload)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"VS Code evaluator failed: {exc}", metadata=payload)

        return EvalResult(status=EvalStatus.PASS, message="VS Code workspace evaluation passed", metadata=payload)
