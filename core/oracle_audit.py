"""Audit helpers for benchmark/oracle task pairing and difficulty policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import yaml

from .benchmark_policy import (
    HARD_MIN_ORACLE_STEPS,
    difficulty_from_oracle_steps,
    extract_declared_oracle_task_ref,
    is_oracle_task_path,
    oracle_steps_from_task_payload,
    resolve_oracle_task_path,
)


@dataclass(frozen=True)
class OracleAuditFinding:
    benchmark_task_path: Path
    benchmark_task_id: str
    benchmark_difficulty: str | None
    oracle_source: str
    oracle_task_path: Path | None
    oracle_steps: int | None
    derived_difficulty: str | None
    oracle_execution_style: str | None
    oracle_real_gui: bool | None
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def real_gui_ok(self) -> bool:
        return self.oracle_real_gui is True


def audit_task_tree(tasks_root: str | Path) -> list[OracleAuditFinding]:
    root = Path(tasks_root)
    findings: list[OracleAuditFinding] = []
    for task_path in sorted(root.rglob("*.yaml")):
        if "archive" in task_path.parts or is_oracle_task_path(task_path):
            continue
        findings.append(audit_benchmark_task(task_path))
    return findings


def audit_benchmark_task(task_path: str | Path) -> OracleAuditFinding:
    path = Path(task_path).resolve()
    payload = _load_yaml_mapping(path)
    benchmark_task_id = str(payload.get("task_id") or "").strip()
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    benchmark_difficulty = _optional_text(metadata.get("difficulty")) if isinstance(metadata, Mapping) else None
    benchmark_oracle_model = _optional_text(metadata.get("oracle_model")) if isinstance(metadata, Mapping) else None

    issues: list[str] = []
    oracle_task_path: Optional[Path] = None
    oracle_source = "none"
    oracle_steps: Optional[int] = None
    derived_difficulty: Optional[str] = None
    oracle_execution_style: Optional[str] = None
    oracle_real_gui: Optional[bool] = None
    declared_oracle_ref = extract_declared_oracle_task_ref(payload)
    oracle_task_path = resolve_oracle_task_path(path, payload)
    oracle_source = "metadata.oracle_task" if declared_oracle_ref else "default_oracle_path"

    if oracle_task_path.exists():
        oracle_payload = _load_yaml_mapping(oracle_task_path)
        oracle_execution_style, oracle_real_gui = _classify_oracle_execution_style(
            oracle_payload,
            benchmark_oracle_model=benchmark_oracle_model,
        )
        try:
            oracle_steps = oracle_steps_from_task_payload(oracle_payload)
            derived_difficulty = difficulty_from_oracle_steps(oracle_steps)
        except Exception as exc:
            issues.append(f"oracle-step-count-invalid: {exc}")
        _append_oracle_identity_issues(
            issues=issues,
            benchmark_task_id=benchmark_task_id or path.stem,
            oracle_payload=oracle_payload,
        )
    else:
        issues.append(f"missing-oracle-task: {oracle_task_path}")

    if benchmark_difficulty and derived_difficulty and benchmark_difficulty != derived_difficulty:
        issues.append(
            "difficulty-mismatch:"
            f" benchmark={benchmark_difficulty} oracle={derived_difficulty} steps={oracle_steps}"
        )

    if benchmark_difficulty == "hard" and isinstance(oracle_steps, int) and oracle_steps < HARD_MIN_ORACLE_STEPS:
        issues.append(f"hard-requires->={HARD_MIN_ORACLE_STEPS}-oracle-steps: got {oracle_steps}")

    if benchmark_difficulty is None:
        issues.append("missing-benchmark-difficulty")

    return OracleAuditFinding(
        benchmark_task_path=path,
        benchmark_task_id=benchmark_task_id or path.stem,
        benchmark_difficulty=benchmark_difficulty,
        oracle_source=oracle_source,
        oracle_task_path=oracle_task_path,
        oracle_steps=oracle_steps,
        derived_difficulty=derived_difficulty,
        oracle_execution_style=oracle_execution_style,
        oracle_real_gui=oracle_real_gui,
        issues=tuple(issues),
    )


def _load_yaml_mapping(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, Mapping):
        raise ValueError(f"task payload must be an object: {path}")
    return payload


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _append_oracle_identity_issues(
    *,
    issues: list[str],
    benchmark_task_id: str,
    oracle_payload: Mapping[str, Any],
) -> None:
    metadata = oracle_payload.get("metadata")
    oracle_task_id = str(oracle_payload.get("task_id") or "").strip()
    if not oracle_task_id:
        issues.append("oracle-task-missing-task_id")

    oracle_for = ""
    oracle_tags: list[Any] = []
    if isinstance(metadata, Mapping):
        oracle_for = str(metadata.get("oracle_for") or "").strip()
        raw_tags = metadata.get("tags")
        if isinstance(raw_tags, list):
            oracle_tags = raw_tags

    if not oracle_for:
        issues.append("oracle-task-missing-metadata.oracle_for")
    elif oracle_for != benchmark_task_id:
        issues.append(
            "oracle-for-mismatch:"
            f" oracle_for={oracle_for} benchmark={benchmark_task_id}"
        )

    lowered_tags = {str(tag).strip().lower() for tag in oracle_tags if str(tag).strip()}
    if "oracle" not in lowered_tags:
        issues.append("oracle-task-missing-oracle-tag")


def summarize_findings(findings: Iterable[OracleAuditFinding]) -> dict[str, Any]:
    items = list(findings)
    execution_styles: dict[str, int] = {}
    real_gui_count = 0
    non_real_gui_count = 0
    unknown_gui_count = 0
    for item in items:
        if item.oracle_execution_style:
            execution_styles[item.oracle_execution_style] = execution_styles.get(item.oracle_execution_style, 0) + 1
        if item.oracle_real_gui is True:
            real_gui_count += 1
        elif item.oracle_real_gui is False:
            non_real_gui_count += 1
        else:
            unknown_gui_count += 1
    return {
        "total": len(items),
        "ok": sum(1 for item in items if item.ok),
        "failing": sum(1 for item in items if not item.ok),
        "issues": sum(len(item.issues) for item in items),
        "oracle_execution_styles": execution_styles,
        "real_gui_oracles": real_gui_count,
        "non_real_gui_oracles": non_real_gui_count,
        "unknown_gui_oracles": unknown_gui_count,
    }


def filter_findings(
    findings: Iterable[OracleAuditFinding],
    *,
    task_id_prefixes: Iterable[str] | None = None,
    oracle_execution_styles: Iterable[str] | None = None,
) -> list[OracleAuditFinding]:
    items = list(findings)
    normalized_prefixes = [
        str(prefix).strip().lower()
        for prefix in (task_id_prefixes or [])
        if str(prefix).strip()
    ]
    normalized_styles = {
        str(style).strip().lower()
        for style in (oracle_execution_styles or [])
        if str(style).strip()
    }

    filtered: list[OracleAuditFinding] = []
    for item in items:
        task_id = item.benchmark_task_id.strip().lower()
        if normalized_prefixes and not any(task_id.startswith(prefix) for prefix in normalized_prefixes):
            continue
        style = str(item.oracle_execution_style or "").strip().lower()
        if normalized_styles and style not in normalized_styles:
            continue
        filtered.append(item)
    return filtered


def real_gui_gap_findings(findings: Iterable[OracleAuditFinding]) -> list[OracleAuditFinding]:
    return [item for item in findings if not item.real_gui_ok]


_GUI_ACTION_TYPES = {
    "tap",
    "double_tap",
    "right_click",
    "scroll",
    "drag",
    "type_text",
    "replace_text",
    "select_text",
    "toggle_italic",
    "keyboard",
    "hotkey",
    "launch_app",
}
_SCRIPTED_GUI_MARKERS = (
    "osascript",
    "system events",
    "click menu bar item",
    "click menu item",
    "click button",
    "click radio button",
    "click checkbox",
    "set position of window",
    "set size of window",
    "keystroke ",
    " key code ",
    "open -a ",
)
_GUI_STUB_MARKERS = (
    "import tkinter",
    "tk.tk()",
    "tk.toplevel(",
    "_oracle_stub.py",
    "root.title(",
    "root.mainloop()",
)
_MATERIALIZE_MARKERS = (
    "path.write_text(",
    "path.write_bytes(",
    "base64.b64decode",
    "sqlite3 ",
    "global-store.json",
)
_ORACLE_MODEL_CLASSIFICATIONS: dict[str, tuple[str, bool]] = {
    "macos_spotube_oracle": ("provider_db_state", False),
    "macos_openshop_oracle": ("provider_local_api", False),
    "macos_blender_oracle": ("provider_background_app", False),
}


def _classify_oracle_execution_style(
    oracle_payload: Mapping[str, Any],
    *,
    benchmark_oracle_model: str | None = None,
) -> tuple[str | None, bool | None]:
    metadata = oracle_payload.get("metadata") if isinstance(oracle_payload.get("metadata"), Mapping) else {}
    evaluation = oracle_payload.get("evaluation") if isinstance(oracle_payload.get("evaluation"), Mapping) else {}
    params = evaluation.get("params") if isinstance(evaluation.get("params"), Mapping) else {}
    oracle_model = str((metadata or {}).get("oracle_model") or benchmark_oracle_model or "").strip().lower()
    actions = (metadata or {}).get("oracle_actions")

    model_classification = _ORACLE_MODEL_CLASSIFICATIONS.get(oracle_model)
    if model_classification is not None:
        return model_classification

    if isinstance(actions, list):
        executable_actions = [
            dict(item)
            for item in actions
            if isinstance(item, Mapping)
            and str(item.get("type") or "").strip().lower() not in {"success", "fail"}
        ]
        action_types = {
            str(item.get("type") or "").strip().lower()
            for item in executable_actions
            if str(item.get("type") or "").strip()
        }
        if action_types & _GUI_ACTION_TYPES:
            return "gui_actions", True

        combined_script = "\n".join(
            str(item.get("script") or "")
            for item in executable_actions
            if str(item.get("type") or "").strip().lower() == "run_bash_script"
        ).lower()
        if combined_script:
            if any(marker in combined_script for marker in _GUI_STUB_MARKERS):
                return "gui_stub", False
            if any(marker in combined_script for marker in _SCRIPTED_GUI_MARKERS):
                return "scripted_gui", True
            if _looks_like_materialize_oracle(metadata, params, combined_script):
                return "artifact_materialize", False
            return "guest_script", False

    if _looks_like_materialize_oracle(metadata, params, ""):
        return "artifact_materialize", False
    return "unknown", None


def _looks_like_materialize_oracle(
    metadata: Mapping[str, Any],
    params: Mapping[str, Any],
    combined_script: str,
) -> bool:
    if isinstance(metadata.get("oracle_fixture"), Mapping):
        return True
    materialize_keys = {
        "actual_path",
        "output_path",
        "expected_path",
        "expected_image_path",
        "expected_root",
        "workspace_root",
        "compare_paths",
        "artifacts",
    }
    if any(key in params for key in materialize_keys):
        return True
    return any(marker in combined_script for marker in _MATERIALIZE_MARKERS)
