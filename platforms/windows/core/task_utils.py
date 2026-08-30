"""Shared task-loading helpers for Windows platform task schemas."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from .runtime_types import SuccessCriteria

TaskT = TypeVar("TaskT")


def parse_success_criteria(data: Dict[str, Any]) -> SuccessCriteria:
    """Parse `success_criteria` payload with common defaults."""
    if not data:
        return SuccessCriteria()
    return SuccessCriteria(
        llm_judge=data.get("llm_judge", True),
        ui_checks=data.get("ui_checks", []),
        foreground_app=data.get("foreground_app"),
    )


def validate_task_common(task: Any, source: str = "") -> None:
    """Validate fields shared by desktop/mobile task schemas."""
    ctx = f" (from {source})" if source else ""
    if not isinstance(task.id, str) or not task.id.strip():
        raise ValueError(f"Task 'id' must be a non-empty string{ctx}")
    if not isinstance(task.goal, str) or not task.goal.strip():
        raise ValueError(f"Task 'goal' must be a non-empty string{ctx}")
    if not isinstance(task.max_steps, int) or task.max_steps < 1:
        raise ValueError(f"Task 'max_steps' must be a positive integer, got {task.max_steps!r}{ctx}")
    step_timeout_seconds = getattr(task, "step_timeout_seconds", None)
    if step_timeout_seconds is not None and (
        not isinstance(step_timeout_seconds, (int, float)) or step_timeout_seconds <= 0
    ):
        raise ValueError(
            f"Task 'step_timeout_seconds' must be positive, got {step_timeout_seconds!r}{ctx}"
        )


def load_tasks_from_directory(
    *,
    dir_path: str,
    load_task_from_file_fn: Callable[[str], TaskT],
    recursive: bool = True,
    filter_tags: Optional[List[str]] = None,
    logger_obj: Optional[logging.Logger] = None,
) -> List[TaskT]:
    """Load tasks from YAML files using a platform-specific task parser."""
    path = Path(dir_path)
    if not path.exists():
        raise FileNotFoundError(f"Task directory not found: {dir_path}")

    patterns = ["**/*.yaml", "**/*.yml"] if recursive else ["*.yaml", "*.yml"]
    tasks: List[TaskT] = []

    for pattern in patterns:
        for task_file in path.glob(pattern):
            try:
                task = load_task_from_file_fn(str(task_file))
            except Exception as e:
                if logger_obj is not None:
                    logger_obj.warning("Failed to load task from %s: %s", task_file, e)
                else:
                    print(f"Warning: Failed to load task from {task_file}: {e}")
                continue

            tags = list(getattr(task, "tags", []))
            if filter_tags and not any(tag in tags for tag in filter_tags):
                continue
            tasks.append(task)

    return tasks


class BaseTaskRegistry(Generic[TaskT]):
    """Shared in-memory registry for platform Task objects."""

    def __init__(self):
        self._tasks: Dict[str, TaskT] = {}

    def register(self, task: TaskT) -> None:
        self._tasks[getattr(task, "id")] = task

    def get(self, task_id: str) -> Optional[TaskT]:
        return self._tasks.get(task_id)

    def get_all(self) -> List[TaskT]:
        return list(self._tasks.values())

    def filter_by_tags(self, tags: List[str]) -> List[TaskT]:
        return [
            task
            for task in self._tasks.values()
            if any(tag in getattr(task, "tags", []) for tag in tags)
        ]

    def __len__(self) -> int:
        return len(self._tasks)

    def __iter__(self):
        return iter(self._tasks.values())
