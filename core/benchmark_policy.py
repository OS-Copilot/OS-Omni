"""Shared benchmark/oracle policy helpers.

This module centralizes the lightweight policy used by task authors:

- benchmark prompts should default to a minimal "benchmark" profile
- verbose/task-specific hints belong to an explicit "debug" profile
- task difficulty is derived from deterministic oracle step counts
- every benchmark task should map to a real oracle task/script
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

BENCHMARK_PROMPT_PROFILE = "benchmark"
DEBUG_PROMPT_PROFILE = "debug"
DEFAULT_PROMPT_PROFILE = BENCHMARK_PROMPT_PROFILE
VALID_PROMPT_PROFILES = {BENCHMARK_PROMPT_PROFILE, DEBUG_PROMPT_PROFILE}

EASY_MAX_ORACLE_STEPS = 10
HARD_MIN_ORACLE_STEPS = 20
REPO_ROOT = Path(__file__).resolve().parents[1]


def normalize_prompt_profile(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return DEFAULT_PROMPT_PROFILE
    if text not in VALID_PROMPT_PROFILES:
        raise ValueError(
            f"Unsupported prompt_profile: {raw!r}. "
            f"Expected one of: {', '.join(sorted(VALID_PROMPT_PROFILES))}."
        )
    return text


def is_debug_prompt_profile(raw: Any) -> bool:
    return normalize_prompt_profile(raw) == DEBUG_PROMPT_PROFILE


def is_benchmark_prompt_profile(raw: Any) -> bool:
    return normalize_prompt_profile(raw) == BENCHMARK_PROMPT_PROFILE


def difficulty_from_oracle_steps(step_count: int) -> str:
    if step_count <= 0:
        raise ValueError(f"oracle step count must be positive, got {step_count!r}")
    if step_count <= EASY_MAX_ORACLE_STEPS:
        return "easy"
    if step_count < HARD_MIN_ORACLE_STEPS:
        return "medium"
    return "hard"


def is_oracle_task_path(task_path: str | Path) -> bool:
    path = Path(task_path)
    return "oracle" in path.parts or path.stem.endswith("_oracle")


def extract_declared_oracle_task_ref(task_payload: Mapping[str, Any]) -> str | None:
    metadata = task_payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return None

    explicit_task = metadata.get("oracle_task")
    if isinstance(explicit_task, str) and explicit_task.strip():
        return explicit_task.strip()

    oracle_meta = metadata.get("oracle")
    if isinstance(oracle_meta, Mapping):
        nested_task = oracle_meta.get("task")
        if isinstance(nested_task, str) and nested_task.strip():
            return nested_task.strip()
    return None


def default_oracle_task_path(task_path: str | Path) -> Path:
    path = Path(task_path)
    return path.parent / "oracle" / f"{path.stem}_oracle{path.suffix or '.yaml'}"


def resolve_declared_oracle_task_path(task_path: str | Path, explicit_ref: str) -> Path:
    explicit = Path(str(explicit_ref).strip())
    if explicit.is_absolute():
        return explicit.resolve()

    task_dir = Path(task_path).resolve().parent
    task_relative = (task_dir / explicit).resolve()
    if task_relative.exists():
        return task_relative
    return (REPO_ROOT / explicit).resolve()


def resolve_oracle_task_path(task_path: str | Path, task_payload: Mapping[str, Any]) -> Path:
    explicit_ref = extract_declared_oracle_task_ref(task_payload)
    if explicit_ref:
        return resolve_declared_oracle_task_path(task_path, explicit_ref)
    return default_oracle_task_path(task_path)


def oracle_steps_from_task_payload(task_payload: Mapping[str, Any]) -> int:
    metadata = task_payload.get("metadata")
    if isinstance(metadata, Mapping):
        human_steps = metadata.get("human_steps")
        if isinstance(human_steps, int) and human_steps > 0:
            return human_steps

    limits = task_payload.get("limits")
    if isinstance(limits, Mapping):
        max_steps = limits.get("max_steps")
        if isinstance(max_steps, int) and max_steps > 0:
            return max_steps

    if isinstance(metadata, Mapping):
        oracle_actions = metadata.get("oracle_actions")
        if isinstance(oracle_actions, list):
            executable_actions = [
                item
                for item in oracle_actions
                if isinstance(item, Mapping)
                and str(item.get("type") or "").strip().lower() not in {"success", "fail"}
            ]
            if executable_actions:
                return len(executable_actions)

    raise ValueError("oracle task is missing a positive limits.max_steps")
