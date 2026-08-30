"""Shared benchmark spec loading and validation."""

from .errors import SpecValidationError
from .loader import (
    REPO_ROOT,
    load_execution_spec,
    load_model_registry,
    load_task_spec,
    load_task_specs,
)
from .types import (
    EvaluationSpec,
    ExecutionSpec,
    InitSpec,
    LimitsSpec,
    PreparedExecution,
    TaskSpec,
)

__all__ = [
    "EvaluationSpec",
    "ExecutionSpec",
    "InitSpec",
    "LimitsSpec",
    "PreparedExecution",
    "SpecValidationError",
    "TaskSpec",
    "REPO_ROOT",
    "load_execution_spec",
    "load_model_registry",
    "load_task_spec",
    "load_task_specs",
]
