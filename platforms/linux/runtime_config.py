"""Linux runtime config loader for platform-specific execution settings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
LINUX_RUNTIME_CONFIG_PATH = REPO_ROOT / "configs" / "linux.yaml"
ENV_VM_IP = "HELLOWORLD_LINUX_VM_IP"
ENV_RUNTIME_PORT = "HELLOWORLD_LINUX_RUNTIME_PORT"
ENV_RUNTIME_TOKEN = "HELLOWORLD_LINUX_RUNTIME_TOKEN"
ENV_VM_PROVIDER = "HELLOWORLD_LINUX_VM_PROVIDER"
ENV_VM_PATH = "HELLOWORLD_LINUX_VM_PATH"
ENV_VM_SNAPSHOT_NAME = "HELLOWORLD_LINUX_VM_SNAPSHOT_NAME"
ENV_VM_HEADLESS = "HELLOWORLD_LINUX_VM_HEADLESS"
ENV_VM_STOP_ON_EXIT = "HELLOWORLD_LINUX_VM_STOP_ON_EXIT"
ENV_VM_USE_PROVIDER_IP = "HELLOWORLD_LINUX_VM_USE_PROVIDER_IP"
ENV_VM_BOOTSTRAP_RUNTIME = "HELLOWORLD_LINUX_VM_BOOTSTRAP_RUNTIME"
ENV_VM_RESET_BETWEEN_TASKS = "HELLOWORLD_LINUX_VM_RESET_BETWEEN_TASKS"
ENV_VM_GUEST_USERNAME = "HELLOWORLD_LINUX_VM_GUEST_USERNAME"
ENV_VM_GUEST_PASSWORD = "HELLOWORLD_LINUX_VM_GUEST_PASSWORD"
ENV_VM_GUEST_PYTHON_BIN = "HELLOWORLD_LINUX_VM_GUEST_PYTHON_BIN"
ENV_VM_GUEST_RUNTIME_DIR = "HELLOWORLD_LINUX_VM_GUEST_RUNTIME_DIR"
ENV_VM_GUEST_INSTALL_DEPS = "HELLOWORLD_LINUX_VM_GUEST_INSTALL_DEPS"
ENV_VM_STORAGE_DIR = "HELLOWORLD_LINUX_VM_STORAGE_DIR"
ENV_VM_IMAGE_URL = "HELLOWORLD_LINUX_VM_IMAGE_URL"
ENV_VM_IMAGE_ARCHIVE_NAME = "HELLOWORLD_LINUX_VM_IMAGE_ARCHIVE_NAME"
ENV_VM_IMAGE_NAME = "HELLOWORLD_LINUX_VM_IMAGE_NAME"


@dataclass(frozen=True)
class LinuxRuntimeConfig:
    source_path: Path
    vm_ip: str
    runtime_port: int
    runtime_token: str
    vm_provider: str | None = None
    vm_path: str | None = None
    vm_snapshot_name: str | None = None
    vm_headless: bool = True
    vm_stop_on_exit: bool = True
    vm_use_provider_ip: bool = True
    vm_bootstrap_runtime: bool = True
    vm_reset_between_tasks: bool = True
    vm_guest_username: str | None = None
    vm_guest_password: str | None = None
    vm_guest_python_bin: str = "python3"
    vm_guest_runtime_dir: str = "/tmp/helloworld_linux_runtime"
    vm_guest_install_deps: bool = True
    vm_storage_dir: str = str(REPO_ROOT / "platforms" / "linux" / "vmware_vm_data")
    vm_image_url: str | None = None
    vm_image_archive_name: str | None = None
    vm_image_name: str | None = None


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
    reuse_vm_session = _optional_execution_bool(raw, "reuse_vm_session", default=False, source_path=source_path)

    return {
        "source_path": source_path,
        "task_paths": task_paths,
        "models": models,
        "action_mode": raw.get("action_mode"),
        "observation_mode": raw.get("observation_mode"),
        "history_window": raw.get("history_window"),
        "max_steps": raw.get("max_steps"),
        "timeout": raw.get("timeout"),
        "reuse_vm_session": reuse_vm_session,
        "metadata": dict(metadata),
    }


def load_linux_runtime_config(path: str | Path = LINUX_RUNTIME_CONFIG_PATH) -> LinuxRuntimeConfig:
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = (REPO_ROOT / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Linux runtime config not found: {source_path}")

    with source_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Linux runtime config must be an object: {source_path}")

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
    runtime_token = _as_non_empty_string(
        os.getenv(
            ENV_RUNTIME_TOKEN,
            _require_field(raw, "runtime_token", field="runtime_token", source_path=source_path),
        ),
        field="runtime_token",
        source_path=source_path,
    )
    vm_provider = _optional_string_override(raw, "vm_provider", ENV_VM_PROVIDER, source_path=source_path)
    if vm_provider is not None:
        vm_provider = vm_provider.lower()
    vm_path = _optional_path_override(raw, "vm_path", ENV_VM_PATH, source_path=source_path)
    vm_snapshot_name = _optional_string_override(
        raw,
        "vm_snapshot_name",
        ENV_VM_SNAPSHOT_NAME,
        source_path=source_path,
    )
    vm_headless = _optional_bool_override(raw, "vm_headless", ENV_VM_HEADLESS, default=True, source_path=source_path)
    vm_stop_on_exit = _optional_bool_override(
        raw,
        "vm_stop_on_exit",
        ENV_VM_STOP_ON_EXIT,
        default=True,
        source_path=source_path,
    )
    vm_use_provider_ip = _optional_bool_override(
        raw,
        "vm_use_provider_ip",
        ENV_VM_USE_PROVIDER_IP,
        default=True,
        source_path=source_path,
    )
    vm_bootstrap_runtime = _optional_bool_override(
        raw,
        "vm_bootstrap_runtime",
        ENV_VM_BOOTSTRAP_RUNTIME,
        default=True,
        source_path=source_path,
    )
    vm_reset_between_tasks = _optional_bool_override(
        raw,
        "vm_reset_between_tasks",
        ENV_VM_RESET_BETWEEN_TASKS,
        default=True,
        source_path=source_path,
    )
    vm_guest_username = _optional_string_override(
        raw,
        "vm_guest_username",
        ENV_VM_GUEST_USERNAME,
        source_path=source_path,
    )
    vm_guest_password = _optional_string_override(
        raw,
        "vm_guest_password",
        ENV_VM_GUEST_PASSWORD,
        source_path=source_path,
    )
    vm_guest_python_bin = (
        _optional_string_override(
            raw,
            "vm_guest_python_bin",
            ENV_VM_GUEST_PYTHON_BIN,
            source_path=source_path,
        )
        or "python3"
    )
    vm_guest_runtime_dir = (
        _optional_string_override(
            raw,
            "vm_guest_runtime_dir",
            ENV_VM_GUEST_RUNTIME_DIR,
            source_path=source_path,
        )
        or "/tmp/helloworld_linux_runtime"
    )
    vm_guest_install_deps = _optional_bool_override(
        raw,
        "vm_guest_install_deps",
        ENV_VM_GUEST_INSTALL_DEPS,
        default=True,
        source_path=source_path,
    )
    vm_storage_dir = (
        _optional_path_override(
            raw,
            "vm_storage_dir",
            ENV_VM_STORAGE_DIR,
            source_path=source_path,
        )
        or str((REPO_ROOT / "platforms" / "linux" / "vmware_vm_data").resolve())
    )
    vm_image_url = _optional_string_override(
        raw,
        "vm_image_url",
        ENV_VM_IMAGE_URL,
        source_path=source_path,
    )
    vm_image_archive_name = _optional_string_override(
        raw,
        "vm_image_archive_name",
        ENV_VM_IMAGE_ARCHIVE_NAME,
        source_path=source_path,
    )
    vm_image_name = _optional_string_override(
        raw,
        "vm_image_name",
        ENV_VM_IMAGE_NAME,
        source_path=source_path,
    )
    if vm_provider and not vm_path and not vm_image_url:
        existing_vmx = _find_existing_vmx(vm_storage_dir, preferred_name=vm_image_name)
        if existing_vmx is None:
            raise ValueError(
                f"vm_path is required in {source_path} when vm_provider is configured, "
                f"unless vm_image_url is set or an existing .vmx is already present under vm_storage_dir."
            )

    return LinuxRuntimeConfig(
        source_path=source_path,
        vm_ip=vm_ip,
        runtime_port=runtime_port,
        runtime_token=runtime_token,
        vm_provider=vm_provider,
        vm_path=vm_path,
        vm_snapshot_name=vm_snapshot_name,
        vm_headless=vm_headless,
        vm_stop_on_exit=vm_stop_on_exit,
        vm_use_provider_ip=vm_use_provider_ip,
        vm_bootstrap_runtime=vm_bootstrap_runtime,
        vm_reset_between_tasks=vm_reset_between_tasks,
        vm_guest_username=vm_guest_username,
        vm_guest_password=vm_guest_password,
        vm_guest_python_bin=vm_guest_python_bin,
        vm_guest_runtime_dir=vm_guest_runtime_dir,
        vm_guest_install_deps=vm_guest_install_deps,
        vm_storage_dir=vm_storage_dir,
        vm_image_url=vm_image_url,
        vm_image_archive_name=vm_image_archive_name,
        vm_image_name=vm_image_name,
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


def _as_positive_int(value: Any, *, field: str, source_path: Path) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer in {source_path}")
    return value


def _optional_execution_bool(
    raw: Mapping[str, Any],
    key: str,
    *,
    default: bool,
    source_path: Path,
) -> bool:
    value = raw.get(key)
    if value is None:
        return default
    return _parse_bool(value, field=key, source_path=source_path)


def _coerce_port_override(env_value: str | None, raw: Mapping[str, Any], source_path: Path) -> Any:
    if env_value is None or not str(env_value).strip():
        return _require_field(raw, "runtime_port", field="runtime_port", source_path=source_path)
    try:
        return int(str(env_value).strip())
    except ValueError as exc:
        raise ValueError(f"runtime_port override must be an integer in env {ENV_RUNTIME_PORT}") from exc


def _optional_string_override(
    raw: Mapping[str, Any],
    key: str,
    env_name: str,
    *,
    source_path: Path,
) -> str | None:
    env_value = os.getenv(env_name)
    if env_value is not None:
        text = str(env_value).strip()
        return text or None

    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string when provided in {source_path}")
    text = value.strip()
    return text or None


def _optional_bool_override(
    raw: Mapping[str, Any],
    key: str,
    env_name: str,
    *,
    default: bool,
    source_path: Path,
) -> bool:
    env_value = os.getenv(env_name)
    if env_value is not None:
        return _parse_bool(env_value, field=env_name, source_path=source_path)

    value = raw.get(key)
    if value is None:
        return default
    return _parse_bool(value, field=key, source_path=source_path)


def _optional_path_override(
    raw: Mapping[str, Any],
    key: str,
    env_name: str,
    *,
    source_path: Path,
) -> str | None:
    text = _optional_string_override(raw, key, env_name, source_path=source_path)
    if text is None:
        return None
    if _looks_like_windows_vmware_path(text):
        return text
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return str(path)


def _looks_like_windows_vmware_path(text: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", str(text).strip()))


def _parse_bool(value: Any, *, field: str, source_path: Path) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{field} must be a boolean in {source_path}")


def _find_existing_vmx(storage_dir: str, *, preferred_name: str | None) -> str | None:
    root = Path(storage_dir).expanduser()
    if not root.exists():
        return None
    vmx_files = sorted(root.rglob("*.vmx"))
    if not vmx_files:
        return None
    if preferred_name:
        preferred = preferred_name.strip().lower()
        for candidate in vmx_files:
            if candidate.stem.lower() == preferred or candidate.parent.name.lower() == preferred:
                return str(candidate.resolve())
    if len(vmx_files) == 1:
        return str(vmx_files[0].resolve())
    return None
