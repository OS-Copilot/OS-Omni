"""Helpers for persisting per-run input snapshots alongside trajectories."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_CONFIG_PATH = REPO_ROOT / "configs" / "models.yaml"


def write_run_args_snapshot(
    run_dir: str | Path,
    *,
    platform: str,
    task: Any,
    model_id: str,
    action_mode: str,
    observation_mode: str,
    history_window: int,
    prompt_profile: str | None = None,
    execution_file: str | Path | None = None,
    models_config_path: str | Path | None = None,
    platform_config_path: str | Path | None = None,
) -> Path:
    """Write args.json into one run directory.

    The snapshot stores the input files used by this run.
    """
    run_dir_path = Path(run_dir)
    run_dir_path.mkdir(parents=True, exist_ok=True)

    task_path = _resolve_optional_path(getattr(task, "source_file", None))
    execution_path = _resolve_optional_path(execution_file)
    models_path = _resolve_optional_path(models_config_path) or DEFAULT_MODELS_CONFIG_PATH.resolve()
    platform_path = _resolve_optional_path(platform_config_path)

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task": {
            "path": str(task_path) if task_path is not None else None,
            "snapshot": _load_task_snapshot(task, task_path),
        },
        "execution": (
            {
                "path": str(execution_path),
                "snapshot": _load_yaml_object(execution_path),
            }
            if execution_path is not None
            else None
        ),
        "model": {
            "path": str(models_path),
            "snapshot": _load_model_snapshot(models_path, model_id),
        },
        "agent": {
            "action_mode": action_mode,
            "observation_mode": observation_mode,
            "history_window": history_window,
            "prompt_profile": prompt_profile,
        },
        "platform_config": (
            {
                "path": str(platform_path),
                "snapshot": _load_yaml_object(platform_path),
            }
            if platform_path is not None
            else None
        ),
    }

    output_path = run_dir_path / "args.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _resolve_optional_path(raw_path: Any) -> Optional[Path]:
    if raw_path is None:
        return None
    text = str(raw_path).strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    else:
        path = path.resolve()
    return path


def _load_yaml_object(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Snapshot source file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_task_snapshot(task: Any, task_path: Optional[Path]) -> Any:
    if task_path is not None:
        snapshot = _load_yaml_object(task_path)
    else:
        task_to_dict = getattr(task, "to_dict", None)
        if callable(task_to_dict):
            snapshot = task_to_dict()
        else:
            snapshot = None
    return _normalize_task_snapshot(snapshot)


def _normalize_task_snapshot(snapshot: Any) -> Any:
    if not isinstance(snapshot, dict):
        return snapshot
    normalized = dict(snapshot)
    normalized.pop("timeout_seconds", None)
    limits = normalized.get("limits")
    if isinstance(limits, dict):
        limits_normalized = dict(limits)
        limits_normalized.pop("timeout_seconds", None)
        normalized["limits"] = limits_normalized
    return normalized


def _load_model_snapshot(models_path: Path, model_id: str) -> Mapping[str, Any]:
    raw = _load_yaml_object(models_path)
    if not isinstance(raw, Mapping):
        raise ValueError(f"models config must be an object: {models_path}")
    raw_models = raw.get("models")
    if not isinstance(raw_models, Mapping):
        raise ValueError(f"models config missing top-level 'models': {models_path}")
    model_snapshot = raw_models.get(model_id)
    if not isinstance(model_snapshot, Mapping):
        raise KeyError(f"model_id not found in models config: {model_id}")
    return dict(model_snapshot)
