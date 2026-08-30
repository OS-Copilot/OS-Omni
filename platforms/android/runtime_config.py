"""Android runtime config loader."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ANDROID_RUNTIME_CONFIG_PATH = REPO_ROOT / "configs" / "android.yaml"
ENV_ADB_DEVICE = "HELLOWORLD_ANDROID_ADB_DEVICE"
ENV_AVD_NAME = "HELLOWORLD_ANDROID_AVD_NAME"
ENV_EMULATOR_RESET_BETWEEN_TASKS = "HELLOWORLD_ANDROID_EMULATOR_RESET_BETWEEN_TASKS"
ENV_EMULATOR_SNAPSHOT_NAME = "HELLOWORLD_ANDROID_EMULATOR_SNAPSHOT_NAME"


@dataclass(frozen=True)
class AndroidRuntimeConfig:
    source_path: Path
    adb_device: str
    avd_name: str
    auto_launch_emulator: bool
    emulator_boot_timeout: int
    emulator_reset_between_tasks: bool
    emulator_snapshot_name: str | None


def load_execution_handoff(execution_path: str | Path) -> dict[str, Any]:
    source_path = Path(execution_path)
    if not source_path.is_absolute():
        source_path = (REPO_ROOT / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Execution file not found: {source_path}")

    with source_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Execution payload must be an object: {source_path}")

    tasks = [str(t).strip() for t in (raw.get("tasks") or []) if str(t).strip()]
    models = [str(m).strip() for m in (raw.get("models") or []) if str(m).strip()]

    task_paths: list[Path] = []
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


def load_android_runtime_config(
    path: str | Path = ANDROID_RUNTIME_CONFIG_PATH,
) -> AndroidRuntimeConfig:
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = (REPO_ROOT / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Android runtime config not found: {source_path}")

    with source_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Android runtime config must be an object: {source_path}")

    adb_device = str(
        os.getenv(ENV_ADB_DEVICE) or raw.get("adb_device", "emulator-5554")
    ).strip()
    avd_name = str(
        os.getenv(ENV_AVD_NAME) or raw.get("avd_name", "AndroidWorldAvd")
    ).strip()
    auto_launch = bool(raw.get("auto_launch_emulator", True))
    boot_timeout = int(raw.get("emulator_boot_timeout", 120))
    reset_between_tasks = _bool_override(
        ENV_EMULATOR_RESET_BETWEEN_TASKS,
        raw.get("emulator_reset_between_tasks", False),
    )
    snapshot_name = str(
        os.getenv(ENV_EMULATOR_SNAPSHOT_NAME) or raw.get("emulator_snapshot_name") or ""
    ).strip() or None
    if reset_between_tasks and not snapshot_name:
        raise ValueError(
            "Android task reset requires emulator_snapshot_name. "
            "Set emulator_snapshot_name in configs/android.yaml or "
            "HELLOWORLD_ANDROID_EMULATOR_SNAPSHOT_NAME."
        )

    return AndroidRuntimeConfig(
        source_path=source_path,
        adb_device=adb_device,
        avd_name=avd_name,
        auto_launch_emulator=auto_launch,
        emulator_boot_timeout=boot_timeout,
        emulator_reset_between_tasks=reset_between_tasks,
        emulator_snapshot_name=snapshot_name,
    )


def _bool_override(env_name: str, fallback: Any) -> bool:
    raw = os.getenv(env_name)
    if raw is None:
        return bool(fallback)
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return bool(fallback)
