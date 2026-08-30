"""Cross-VM task and execution loaders."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CrossVmTransferSpec:
    """Host-mediated transfer from one guest to another guest."""

    source_guest_path: str
    target_guest_path: str
    host_filename: str
    windows_guest_path: str | None = None
    linux_guest_path: str | None = None
    android_guest_path: str | None = None


@dataclass(frozen=True)
class CrossVmTaskSpec:
    """One sequential cross-VM task."""

    source_path: Path
    task_id: str
    instruction: str
    source_platform: str
    target_platform: str
    source_task_path: Path
    target_task_path: Path
    transfer: CrossVmTransferSpec
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def windows_task_path(self) -> Path:
        if self.source_platform == "windows":
            return self.source_task_path
        if self.target_platform == "windows":
            return self.target_task_path
        raise AttributeError("Cross-VM task does not include a Windows child task")

    @property
    def linux_task_path(self) -> Path:
        if self.source_platform == "linux":
            return self.source_task_path
        if self.target_platform == "linux":
            return self.target_task_path
        raise AttributeError("Cross-VM task does not include a Linux child task")

    @property
    def android_task_path(self) -> Path:
        if self.source_platform == "android":
            return self.source_task_path
        if self.target_platform == "android":
            return self.target_task_path
        raise AttributeError("Cross-VM task does not include an Android child task")


@dataclass(frozen=True)
class CrossVmExecutionSpec:
    """Execution handoff for cross-VM tasks."""

    source_path: Path
    task_paths: list[Path]
    models: list[str]
    action_mode: str | None = None
    observation_mode: str | None = None
    history_window: int | None = None
    max_steps: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def load_cross_vm_task(path: str | Path) -> CrossVmTaskSpec:
    raw, source_path = _load_yaml_mapping(path)
    task_id = _require_string(raw, "task_id", source_path)
    platform = _require_string(raw, "platform", source_path)
    if platform != "cross_vm":
        raise ValueError(f"Cross-VM task platform must be 'cross_vm': {source_path}")
    instruction = _require_string(raw, "instruction", source_path)
    android_task_raw = _optional_string(raw, "android_task")
    windows_task_raw = _optional_string(raw, "windows_task")
    linux_task_raw = _optional_string(raw, "linux_task")

    if android_task_raw and windows_task_raw and not linux_task_raw:
        source_platform = "android"
        target_platform = "windows"
        source_task_path = _resolve_repo_path(android_task_raw)
        target_task_path = _resolve_repo_path(windows_task_raw)
    elif windows_task_raw and linux_task_raw and not android_task_raw:
        source_platform = "windows"
        target_platform = "linux"
        source_task_path = _resolve_repo_path(windows_task_raw)
        target_task_path = _resolve_repo_path(linux_task_raw)
    else:
        raise ValueError(
            "Cross-VM task must define exactly one supported route: "
            "windows_task+linux_task or android_task+windows_task"
        )

    transfer_raw = raw.get("transfer")
    if not isinstance(transfer_raw, Mapping):
        raise ValueError(f"cross_vm transfer block is required: {source_path}")
    windows_guest_path = _optional_string(transfer_raw, "windows_guest_path")
    linux_guest_path = _optional_string(transfer_raw, "linux_guest_path")
    android_guest_path = _optional_string(transfer_raw, "android_guest_path")
    if source_platform == "windows":
        source_guest_path = _require_string(transfer_raw, "windows_guest_path", source_path)
        target_guest_path = _require_string(transfer_raw, "linux_guest_path", source_path)
    elif source_platform == "android":
        source_guest_path = _require_string(transfer_raw, "android_guest_path", source_path)
        target_guest_path = _require_string(transfer_raw, "windows_guest_path", source_path)
    else:
        raise ValueError(f"Unsupported source platform: {source_platform}")
    host_filename = str(transfer_raw.get("host_filename") or "").strip()
    if not host_filename:
        if "\\" in target_guest_path or ":" in target_guest_path:
            host_filename = PureWindowsPath(target_guest_path).name
        else:
            host_filename = Path(target_guest_path).name

    metadata = raw.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"cross_vm metadata must be an object when provided: {source_path}")

    return CrossVmTaskSpec(
        source_path=source_path,
        task_id=task_id,
        instruction=instruction,
        source_platform=source_platform,
        target_platform=target_platform,
        source_task_path=source_task_path,
        target_task_path=target_task_path,
        transfer=CrossVmTransferSpec(
            source_guest_path=source_guest_path,
            target_guest_path=target_guest_path,
            host_filename=host_filename,
            windows_guest_path=windows_guest_path,
            linux_guest_path=linux_guest_path,
            android_guest_path=android_guest_path,
        ),
        metadata=dict(metadata),
        raw=dict(raw),
    )


def load_cross_vm_execution(path: str | Path) -> CrossVmExecutionSpec:
    raw, source_path = _load_yaml_mapping(path)
    task_paths_raw = raw.get("tasks")
    if not isinstance(task_paths_raw, list) or not task_paths_raw:
        raise ValueError(f"cross_vm execution.tasks must be a non-empty array: {source_path}")
    task_paths = [_resolve_repo_path(str(item).strip()) for item in task_paths_raw if str(item).strip()]
    models = [str(item).strip() for item in (raw.get("models") or []) if str(item).strip()]
    if not models:
        raise ValueError(f"cross_vm execution.models must be a non-empty array: {source_path}")
    metadata = raw.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"cross_vm execution.metadata must be an object when provided: {source_path}")
    history_window = raw.get("history_window")
    if history_window is not None:
        if isinstance(history_window, bool) or not isinstance(history_window, int) or history_window <= 0:
            raise ValueError(f"cross_vm execution.history_window must be a positive integer: {source_path}")
    max_steps = raw.get("max_steps")
    if max_steps is not None:
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
            raise ValueError(f"cross_vm execution.max_steps must be a positive integer: {source_path}")
    return CrossVmExecutionSpec(
        source_path=source_path,
        task_paths=task_paths,
        models=models,
        action_mode=str(raw.get("action_mode") or "").strip() or None,
        observation_mode=str(raw.get("observation_mode") or "").strip() or None,
        history_window=history_window,
        max_steps=max_steps,
        metadata=dict(metadata),
        raw=dict(raw),
    )


def _load_yaml_mapping(path: str | Path) -> tuple[dict[str, Any], Path]:
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = (REPO_ROOT / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"YAML file not found: {source_path}")
    with source_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"YAML payload must be an object: {source_path}")
    return dict(raw), source_path


def _resolve_repo_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return path


def _require_string(data: Mapping[str, Any], key: str, source_path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing non-empty string field '{key}' in {source_path}")
    return value.strip()


def _optional_string(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None

