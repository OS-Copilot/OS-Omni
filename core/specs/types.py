"""Core dataclasses for benchmark spec preparation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.llm.types import ModelSpec


@dataclass(frozen=True)
class InitSpec:
    initializer_id: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationSpec:
    evaluator_id: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LimitsSpec:
    max_steps: int
    step_timeout_seconds: Optional[float] = None


@dataclass(frozen=True)
class TaskSpec:
    source_path: Path
    task_id: str
    platform: str
    instruction: str
    evaluation: EvaluationSpec
    limits: LimitsSpec
    init: Optional[InitSpec] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionSpec:
    source_path: Path
    task_paths: List[Path]
    models: List[str]
    action_mode: Optional[str] = None
    observation_mode: Optional[str] = None
    history_window: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedExecution:
    execution: ExecutionSpec
    tasks: List[TaskSpec]
    models: List[ModelSpec]
    platform: str
