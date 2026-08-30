"""Shared benchmark launcher skeleton.

This module only validates shared inputs and prepares a minimal handoff object
for platform code. It does not load platform runtime config, expand execution
plans, or dispatch into platform runners.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from core.specs import (
    PreparedExecution,
    load_execution_spec,
    load_model_registry,
    load_task_specs,
)


def prepare_execution(
    execution_path: str | Path,
    *,
    models_path: Optional[str | Path] = None,
) -> PreparedExecution:
    execution = load_execution_spec(execution_path)
    tasks = load_task_specs(execution.task_paths)
    platform = tasks[0].platform

    model_registry = load_model_registry(models_path)
    models = [model_registry.get(model_id) for model_id in execution.models]

    return PreparedExecution(
        execution=execution,
        tasks=tasks,
        models=models,
        platform=platform,
    )


def prepare_execution_summary(prepared: PreparedExecution) -> Dict[str, Any]:
    return {
        "execution_path": str(prepared.execution.source_path),
        "platform": prepared.platform,
        "task_count": len(prepared.tasks),
        "tasks": [
            {
                "task_id": task.task_id,
                "path": str(task.source_path),
            }
            for task in prepared.tasks
        ],
        "model_count": len(prepared.models),
        "models": [model.model_id for model in prepared.models],
        "action_mode": prepared.execution.action_mode,
        "observation_mode": prepared.execution.observation_mode,
        "history_window": prepared.execution.history_window,
    }
