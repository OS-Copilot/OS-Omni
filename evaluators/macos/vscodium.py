"""Evaluate macOS VSCodium tasks."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath
from textwrap import dedent
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_SCAN_SCRIPT = r'''
import json
import os
import re
from pathlib import Path

params = json.loads(__PARAMS_JSON__)
settings_path = Path(os.path.expanduser(str(params.get("settings_path") or "~/Library/Application Support/VSCodium/User/settings.json")))
expected_values = dict(params.get("expected_values") or {})
result = {
    "status": "fail",
    "message": "VSCodium checks failed",
    "settings_path": str(settings_path),
    "expected_values": expected_values,
}

if not expected_values:
    result["status"] = "error"
    result["message"] = "VSCodium evaluator requires expected_values"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

if not settings_path.exists():
    result["message"] = f"settings.json missing: {settings_path}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

raw = settings_path.read_text(encoding="utf-8")
result["raw_length"] = len(raw)


def strip_jsonc(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


try:
    settings = json.loads(raw)
except Exception:
    try:
        settings = json.loads(strip_jsonc(raw))
    except Exception as exc:
        result["status"] = "error"
        result["message"] = f"failed to parse settings.json: {exc}"
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0)

result["settings"] = settings
failures = []
observed_values = {}
for key, expected in expected_values.items():
    observed = settings.get(key, "__MISSING__")
    observed_values[key] = observed
    if observed == "__MISSING__":
        failures.append(f"missing setting: {key}")
    elif observed != expected:
        failures.append(
            f"setting mismatch for {key}: expected {expected!r}, observed {observed!r}"
        )

result["observed_values"] = observed_values
if failures:
    result["status"] = "fail"
    result["message"] = "; ".join(failures)
else:
    result["status"] = "pass"
    result["message"] = "VSCodium settings match expected values"

print(json.dumps(result, ensure_ascii=False))
'''


def _strip_jsonc(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _load_json_relaxed(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return json.loads(_strip_jsonc(text))


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip("\n")


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


class VSCodiumSettingsEvaluator(BaseEvaluator):
    """Guest-side evaluator for VSCodium settings tasks on macOS."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_python_script is required")

        script = dedent(_SCAN_SCRIPT).replace(
            "__PARAMS_JSON__",
            repr(json.dumps(params, ensure_ascii=False)),
        )
        try:
            result = controller.run_python_script(script, timeout=int(params.get("timeout", 60) or 60))
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"VSCodium evaluation failed: {exc}")

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="VSCodium evaluator returned non-JSON output",
                metadata={"runtime_result": result},
            )

        status_name = str(payload.get("status") or "").strip().lower()
        eval_status = (
            EvalStatus.PASS
            if status_name == "pass"
            else EvalStatus.FAIL
            if status_name == "fail"
            else EvalStatus.ERROR
        )
        return EvalResult(
            status=eval_status,
            message=str(payload.get("message") or "VSCodium evaluation completed"),
            metadata=payload,
        )


class VSCodiumWorkspaceEvaluator(BaseEvaluator):
    """Compare saved workspace files against expected fixtures."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        task = context.get("task")
        run_dir = context.get("run_dir")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.get_file is required")

        workspace_root = str(params.get("workspace_root") or "").strip()
        expected_root_raw = str(params.get("expected_root") or "").strip()
        compare_paths = [
            str(item).strip()
            for item in list(params.get("compare_paths") or [])
            if str(item).strip()
        ]
        if not workspace_root or not expected_root_raw:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires workspace_root and expected_root",
            )

        expected_root = _resolve_local_path(expected_root_raw, task=task, run_dir=run_dir)
        if not expected_root.exists() or not expected_root.is_dir():
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"expected_root does not exist: {expected_root}",
            )

        if not compare_paths:
            compare_paths = [
                path.relative_to(expected_root).as_posix()
                for path in sorted(expected_root.rglob("*"))
                if path.is_file()
            ]

        failures: list[str] = []
        observed: dict[str, Any] = {}
        for relative in compare_paths:
            expected_path = expected_root / relative
            if not expected_path.exists() or not expected_path.is_file():
                failures.append(f"expected fixture missing: {relative}")
                continue

            remote_path = str(PurePosixPath(workspace_root) / PurePosixPath(relative))
            try:
                actual_bytes = controller.get_file(remote_path)
            except Exception as exc:
                failures.append(f"failed to fetch {relative}: {exc}")
                continue

            try:
                actual_text = actual_bytes.decode("utf-8")
                expected_text = expected_path.read_text(encoding="utf-8")
            except Exception as exc:
                failures.append(f"failed to decode {relative}: {exc}")
                continue

            suffix = expected_path.suffix.lower()
            if suffix == ".json":
                try:
                    actual_value = _load_json_relaxed(actual_text)
                except Exception as exc:
                    failures.append(f"{relative}: actual JSON parse failed: {exc}")
                    continue
                try:
                    expected_value = _load_json_relaxed(expected_text)
                except Exception as exc:
                    return EvalResult(
                        status=EvalStatus.ERROR,
                        message=f"{relative}: expected JSON fixture is invalid: {exc}",
                    )

                observed[relative] = {"kind": "json", "actual": actual_value}
                if actual_value != expected_value:
                    failures.append(f"{relative}: JSON content does not match expected fixture")
                continue

            normalized_actual = _normalize_text(actual_text)
            normalized_expected = _normalize_text(expected_text)
            observed[relative] = {
                "kind": "text",
                "actual_preview": normalized_actual.splitlines()[:8],
            }
            if normalized_actual != normalized_expected:
                failures.append(f"{relative}: text content does not match expected fixture")

        if failures:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="; ".join(failures),
                metadata={
                    "workspace_root": workspace_root,
                    "expected_root": str(expected_root),
                    "compare_paths": compare_paths,
                    "observed": observed,
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="VSCodium workspace matches expected fixture files",
            metadata={
                "workspace_root": workspace_root,
                "expected_root": str(expected_root),
                "compare_paths": compare_paths,
                "observed": observed,
            },
        )
