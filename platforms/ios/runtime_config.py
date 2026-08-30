"""iOS runtime config loader for platform-specific execution settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
IOS_RUNTIME_CONFIG_PATH = REPO_ROOT / "configs" / "ios.yaml"


@dataclass(frozen=True)
class IOSRuntimeConfig:
    source_path: Path
    appium_host: str
    appium_port: int
    source_simulator_udid: str


def load_ios_runtime_config() -> IOSRuntimeConfig:
    source_path = IOS_RUNTIME_CONFIG_PATH.resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"iOS runtime config not found: {source_path}")

    with source_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"iOS runtime config must be an object: {source_path}")

    appium_host = _as_non_empty_string(
        raw.get("appium_host"),
        field="appium_host",
        source_path=source_path,
    )
    appium_port = _as_positive_int(
        raw.get("appium_port"),
        field="appium_port",
        source_path=source_path,
    )

    source_simulator_udid = _as_non_empty_string(
        raw.get("source_simulator_udid"),
        field="source_simulator_udid",
        source_path=source_path,
    )

    return IOSRuntimeConfig(
        source_path=source_path,
        appium_host=appium_host,
        appium_port=appium_port,
        source_simulator_udid=source_simulator_udid,
    )


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

    raw_tasks = raw.get("tasks")
    raw_models = raw.get("models")
    tasks = _to_string_list(raw_tasks)
    models = _to_string_list(raw_models)

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
