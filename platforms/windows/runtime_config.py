"""Windows runtime config loader for platform-specific execution settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_RUNTIME_CONFIG_PATH = REPO_ROOT / "configs" / "windows.yaml"
ENV_VM_IP = "HELLOWORLD_WINDOWS_VM_IP"
ENV_RUNTIME_PORT = "HELLOWORLD_WINDOWS_RUNTIME_PORT"
ENV_RUNTIME_TOKEN = "HELLOWORLD_WINDOWS_RUNTIME_TOKEN"
ENV_VM_PROVIDER = "HELLOWORLD_WINDOWS_VM_PROVIDER"
ENV_VM_PATH = "HELLOWORLD_WINDOWS_VM_PATH"
ENV_VM_PASSWORD = "HELLOWORLD_WINDOWS_VM_PASSWORD"
ENV_VM_SNAPSHOT_NAME = "HELLOWORLD_WINDOWS_VM_SNAPSHOT_NAME"
ENV_VM_HEADLESS = "HELLOWORLD_WINDOWS_VM_HEADLESS"
ENV_VM_STOP_ON_EXIT = "HELLOWORLD_WINDOWS_VM_STOP_ON_EXIT"
ENV_VM_USE_PROVIDER_IP = "HELLOWORLD_WINDOWS_VM_USE_PROVIDER_IP"
ENV_VM_RESET_BETWEEN_TASKS = "HELLOWORLD_WINDOWS_VM_RESET_BETWEEN_TASKS"
ENV_VM_BOOTSTRAP_RUNTIME = "HELLOWORLD_WINDOWS_VM_BOOTSTRAP_RUNTIME"
ENV_VM_GUEST_USERNAME = "HELLOWORLD_WINDOWS_VM_GUEST_USERNAME"
ENV_VM_GUEST_PASSWORD = "HELLOWORLD_WINDOWS_VM_GUEST_PASSWORD"


@dataclass(frozen=True)
class WindowsRuntimeConfig:
    source_path: Path
    vm_ip: str
    runtime_port: int
    runtime_token: str
    vm_provider: str | None = None
    vm_path: str | None = None
    vm_password: str | None = None
    vm_snapshot_name: str | None = None
    vm_headless: bool = True
    vm_stop_on_exit: bool = True
    vm_use_provider_ip: bool = False
    vm_reset_between_tasks: bool = False
    vm_bootstrap_runtime: bool = True
    vm_guest_username: str | None = None
    vm_guest_password: str | None = None


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
        "max_steps": raw.get("max_steps"),
        "timeout": raw.get("timeout"),
        "reuse_vm_session": bool(raw.get("reuse_vm_session", False)),
        "metadata": dict(metadata),
    }


def load_windows_runtime_config(path: str | Path = WINDOWS_RUNTIME_CONFIG_PATH) -> WindowsRuntimeConfig:
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = (REPO_ROOT / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Windows runtime config not found: {source_path}")

    with source_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Windows runtime config must be an object: {source_path}")

    vm_provider = _optional_string(_env_or_raw(ENV_VM_PROVIDER, raw, "vm_provider"))
    vm_use_provider_ip = _as_bool(_env_or_raw(ENV_VM_USE_PROVIDER_IP, raw, "vm_use_provider_ip"), default=False)
    raw_vm_ip = os.getenv(ENV_VM_IP, raw.get("vm_ip"))
    if vm_provider and vm_use_provider_ip and (raw_vm_ip is None or not str(raw_vm_ip).strip()):
        vm_ip = ""
    else:
        vm_ip = _as_non_empty_string(
            raw_vm_ip if raw_vm_ip is not None else _require_field(raw, "vm_ip", field="vm_ip", source_path=source_path),
            field="vm_ip",
            source_path=source_path,
        )
    runtime_port = _as_positive_int(
        _coerce_port_override(os.getenv(ENV_RUNTIME_PORT), raw, source_path),
        field="runtime_port",
        source_path=source_path,
    )
    runtime_token = _as_non_empty_string(
        os.getenv(
            ENV_RUNTIME_TOKEN,
            _require_field(raw, "runtime_token", field="runtime_token", source_path=source_path),
        ),
        field="runtime_token",
        source_path=source_path,
    )

    return WindowsRuntimeConfig(
        source_path=source_path,
        vm_ip=vm_ip,
        runtime_port=runtime_port,
        runtime_token=runtime_token,
        vm_provider=vm_provider,
        vm_path=_optional_string(_env_or_raw(ENV_VM_PATH, raw, "vm_path")),
        vm_password=_optional_string(_env_or_raw(ENV_VM_PASSWORD, raw, "vm_password")),
        vm_snapshot_name=_optional_string(_env_or_raw(ENV_VM_SNAPSHOT_NAME, raw, "vm_snapshot_name")),
        vm_headless=_as_bool(_env_or_raw(ENV_VM_HEADLESS, raw, "vm_headless"), default=True),
        vm_stop_on_exit=_as_bool(_env_or_raw(ENV_VM_STOP_ON_EXIT, raw, "vm_stop_on_exit"), default=True),
        vm_use_provider_ip=vm_use_provider_ip,
        vm_reset_between_tasks=_as_bool(
            _env_or_raw(ENV_VM_RESET_BETWEEN_TASKS, raw, "vm_reset_between_tasks"),
            default=False,
        ),
        vm_bootstrap_runtime=_as_bool(
            _env_or_raw(ENV_VM_BOOTSTRAP_RUNTIME, raw, "vm_bootstrap_runtime"),
            default=True,
        ),
        vm_guest_username=_optional_string(_env_or_raw(ENV_VM_GUEST_USERNAME, raw, "vm_guest_username")),
        vm_guest_password=_optional_string(_env_or_raw(ENV_VM_GUEST_PASSWORD, raw, "vm_guest_password")),
    )


def _require_field(data: Mapping[str, Any], key: str, *, field: str, source_path: Path) -> Any:
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


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _env_or_raw(env_name: str, raw: Mapping[str, Any], key: str) -> Any:
    env_value = os.getenv(env_name)
    if env_value is not None:
        return env_value
    return raw.get(key)


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _as_positive_int(value: Any, *, field: str, source_path: Path) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer in {source_path}")
    return value


def _coerce_port_override(env_value: str | None, raw: Mapping[str, Any], source_path: Path) -> Any:
    if env_value is None or not str(env_value).strip():
        return _require_field(raw, "runtime_port", field="runtime_port", source_path=source_path)
    try:
        return int(str(env_value).strip())
    except ValueError as exc:
        raise ValueError(f"runtime_port override must be an integer in env {ENV_RUNTIME_PORT}") from exc
