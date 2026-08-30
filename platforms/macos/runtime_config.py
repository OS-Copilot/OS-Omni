"""macOS runtime config loader for platform-specific execution settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MACOS_RUNTIME_CONFIG_PATH = REPO_ROOT / "configs" / "macos.yaml"
ENV_VM_IP = "HELLOWORLD_MACOS_VM_IP"
ENV_RUNTIME_PORT = "HELLOWORLD_MACOS_RUNTIME_PORT"
ENV_VM_TOKEN = "HELLOWORLD_MACOS_VM_TOKEN"
ENV_BASE_VM_NAME = "HELLOWORLD_MACOS_BASE_VM_NAME"
ENV_VM_PROVIDER = "HELLOWORLD_MACOS_VM_PROVIDER"
ENV_TART_HOME = "HELLOWORLD_MACOS_TART_HOME"


@dataclass(frozen=True)
class MacOSRuntimeConfig:
    source_path: Path
    vm_ip: str
    runtime_port: int
    vm_token: str
    base_vm_name: str
    vm_provider: str = "tart"
    tart_home: str | None = None



def load_execution_handoff(execution_path: str | Path) -> Dict[str, Any]:
    source_path = Path(execution_path)
    if not source_path.is_absolute():
        source_path = (REPO_ROOT / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Execution file not found: {source_path}")

    with source_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Execution payload must be an object: {source_path}")

    tasks = _to_string_list(raw.get("tasks"))
    models = _to_string_list(raw.get("models"))

    task_paths: List[Path] = []
    for item in tasks:
        path = Path(item)
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        task_paths.append(path)

    metadata = raw.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    return {
        "source_path": source_path,
        "task_paths": task_paths,
        "models": models,
        "action_mode": raw.get("action_mode"),
        "observation_mode": raw.get("observation_mode"),
        "history_window": raw.get("history_window"),
        "metadata": dict(metadata),
    }



def load_macos_runtime_config(path: str | Path) -> MacOSRuntimeConfig:
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = (REPO_ROOT / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"macOS runtime config not found: {source_path}")

    with source_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"macOS runtime config must be an object: {source_path}")

    vm_ip = _as_non_empty_string(
        os.getenv(ENV_VM_IP, _require_field(raw, "vm_ip", field="vm_ip", source_path=source_path)),
        field="vm_ip",
        source_path=source_path,
    )
    runtime_port = _as_positive_int(
        _coerce_port_override(os.getenv(ENV_RUNTIME_PORT), raw, source_path),
        field="runtime_port",
        source_path=source_path,
    )
    vm_token = _as_non_empty_string(
        os.getenv(ENV_VM_TOKEN, _require_field(raw, "vm_token", field="vm_token", source_path=source_path)),
        field="vm_token",
        source_path=source_path,
    )
    base_vm_name = _as_non_empty_string(
        os.getenv(ENV_BASE_VM_NAME, _require_field(raw, "base_vm_name", field="base_vm_name", source_path=source_path)),
        field="base_vm_name",
        source_path=source_path,
    )
    vm_provider = (
        _optional_string_override(raw, "vm_provider", ENV_VM_PROVIDER, source_path=source_path)
        or "tart"
    ).strip().lower()
    if vm_provider not in {"virtualbuddy", "tart"}:
        raise ValueError(f"vm_provider must be 'virtualbuddy' or 'tart' in {source_path}")
    tart_home = _optional_string_override(raw, "tart_home", ENV_TART_HOME, source_path=source_path)

    return MacOSRuntimeConfig(
        source_path=source_path,
        vm_ip=vm_ip,
        runtime_port=runtime_port,
        vm_token=vm_token,
        base_vm_name=base_vm_name,
        vm_provider=vm_provider,
        tart_home=tart_home,
    )



def _require_field(
    data: Mapping[str, Any],
    key: str,
    *,
    field: str,
    source_path: Path,
) -> Any:
    if key not in data:
        raise ValueError(f"{field} is required in {source_path}")
    return data.get(key)



def _as_non_empty_string(value: Any, *, field: str, source_path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string in {source_path}")
    return value.strip()



def _to_string_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []



def _as_positive_int(value: Any, *, field: str, source_path: Path) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer in {source_path}")
    return value



def _optional_string_override(
    raw: Mapping[str, Any],
    key: str,
    env_name: str,
    *,
    source_path: Path,
) -> str | None:
    value = os.getenv(env_name)
    if value is None:
        value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string in {source_path}")
    return value.strip()



def _coerce_port_override(env_value: str | None, raw: Mapping[str, Any], source_path: Path) -> Any:
    if env_value is None:
        return _require_field(raw, "runtime_port", field="runtime_port", source_path=source_path)
    try:
        return int(env_value)
    except ValueError as exc:
        raise ValueError(f"runtime_port must be an integer in {source_path}") from exc
