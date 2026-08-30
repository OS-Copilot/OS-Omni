"""
Core iOS task schema plus shared episode/decision data structures.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.specs.types import EvaluationSpec, InitSpec

from platforms.ios.core.task_utils import (
    BaseTaskRegistry,
    load_tasks_from_directory as load_tasks_from_directory_shared,
    parse_success_criteria,
    validate_task_common,
)
from platforms.ios.core.runtime_types import (
    ActionDecision,
    EpisodeResult,
    StepRecord,
    SuccessCriteria,
    TerminalReason,
)


@dataclass
class Task:
    """iOS task definition."""

    id: str
    goal: str
    evaluation: Optional[EvaluationSpec] = None
    init: Optional[InitSpec] = None
    launch_app_bundle_id: Optional[str] = None
    success_criteria: SuccessCriteria = field(default_factory=SuccessCriteria)
    max_steps: int = 30
    step_timeout_seconds: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    description: Optional[str] = None
    source_file: Optional[str] = None
    include_screenshot: bool = True
    oracle_actions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "evaluation": (
                {
                    "evaluator_id": self.evaluation.evaluator_id,
                    "params": dict(self.evaluation.params),
                }
                if self.evaluation is not None
                else None
            ),
            "init": (
                {
                    "initializer_id": self.init.initializer_id,
                    "params": dict(self.init.params),
                }
                if self.init is not None
                else None
            ),
            "launch_app_bundle_id": self.launch_app_bundle_id,
            "success_criteria": self.success_criteria.to_dict(),
            "max_steps": self.max_steps,
            "step_timeout_seconds": self.step_timeout_seconds,
            "tags": self.tags,
            "description": self.description,
            "include_screenshot": self.include_screenshot,
            "oracle_actions": [dict(action) for action in self.oracle_actions],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def load_task_from_dict(data: Dict[str, Any], source_file: Optional[str] = None) -> Task:
    task = _load_v2_task_from_dict(data, source_file=source_file)
    validate_task_common(task, source=source_file or "")
    return task


def load_task_from_file(file_path: str) -> Task:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Task file not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix not in {".yaml", ".yml"}:
        raise ValueError(f"Task file must be YAML (.yaml/.yml): {file_path}")

    data = _load_yaml(path.read_text(encoding="utf-8"), file_path)

    if not isinstance(data, dict):
        raise ValueError(f"Task file must contain an object: {file_path}")

    return load_task_from_dict(data, source_file=str(path.absolute()))


def load_tasks_from_directory(
    dir_path: str,
    recursive: bool = True,
    filter_tags: Optional[List[str]] = None,
) -> List[Task]:
    return load_tasks_from_directory_shared(
        dir_path=dir_path,
        load_task_from_file_fn=load_task_from_file,
        recursive=recursive,
        filter_tags=filter_tags,
        logger_obj=None,
    )


def create_simple_task(task_id: str, goal: str, **kwargs: Any) -> Task:
    return Task(
        id=task_id,
        goal=goal,
        evaluation=kwargs.get("evaluation"),
        init=kwargs.get("init"),
        launch_app_bundle_id=kwargs.get("launch_app_bundle_id"),
        max_steps=kwargs.get("max_steps", 30),
        step_timeout_seconds=kwargs.get("step_timeout_seconds", 300),
        tags=kwargs.get("tags", []),
        description=kwargs.get("description"),
        include_screenshot=kwargs.get("include_screenshot", True),
    )


class TaskRegistry(BaseTaskRegistry[Task]):
    """Registry for managing multiple tasks."""

    def __init__(self):
        super().__init__()

    def load_from_directory(self, dir_path: str, recursive: bool = True) -> None:
        tasks = load_tasks_from_directory(dir_path, recursive)
        for task in tasks:
            self.register(task)


def _load_v2_task_from_dict(data: Dict[str, Any], source_file: Optional[str]) -> Task:
    if not isinstance(data, dict):
        raise ValueError("Task payload must be an object")
    if "task_id" not in data:
        raise ValueError("TaskSpec missing required field: task_id")
    if "instruction" not in data:
        raise ValueError("TaskSpec missing required field: instruction")
    if str(data.get("platform", "")).strip() != "ios":
        raise ValueError("TaskSpec 'platform' must be 'ios'")

    limits = data.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("TaskSpec missing required object field: limits")
    if "max_steps" not in limits:
        raise ValueError("TaskSpec limits must include max_steps")

    evaluation = data.get("evaluation")
    if not isinstance(evaluation, dict):
        raise ValueError("TaskSpec missing required object field: evaluation")
    evaluator_id = str(evaluation.get("evaluator_id", "")).strip()
    if not evaluator_id:
        raise ValueError("TaskSpec evaluation.evaluator_id must be a non-empty string")
    evaluation_params = evaluation.get("params") or {}
    if not isinstance(evaluation_params, dict):
        raise ValueError("TaskSpec evaluation.params must be an object when provided")

    task_id = data["task_id"]
    instruction = data["instruction"]
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("TaskSpec task_id must be a non-empty string")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("TaskSpec instruction must be a non-empty string")

    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    oracle_actions_raw = metadata.get("oracle_actions")
    oracle_actions: List[Dict[str, Any]] = []
    if isinstance(oracle_actions_raw, list):
        for index, action in enumerate(oracle_actions_raw, start=1):
            if not isinstance(action, dict):
                raise ValueError(f"TaskSpec metadata.oracle_actions[{index}] must be an object")
            oracle_actions.append(dict(action))

    init_raw = data.get("init")
    init_spec = None
    init_params: Dict[str, Any] = {}
    if init_raw is not None:
        if not isinstance(init_raw, dict):
            raise ValueError("TaskSpec init must be an object when provided")
        initializer_id = str(init_raw.get("initializer_id", "")).strip()
        if not initializer_id:
            raise ValueError("TaskSpec init.initializer_id must be a non-empty string")
        init_params = init_raw.get("params") or {}
        if not isinstance(init_params, dict):
            raise ValueError("TaskSpec init.params must be an object when provided")
        init_spec = InitSpec(
            initializer_id=initializer_id,
            params=dict(init_params),
        )

    success_payload = metadata.get("success_criteria")
    success_criteria = (
        parse_success_criteria(success_payload)
        if isinstance(success_payload, dict)
        else SuccessCriteria()
    )

    launch_app_bundle_id = (
        init_params.get("launch_app_bundle_id")
        or init_params.get("bundle_id")
    )

    tags = metadata.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    return Task(
        id=task_id,
        goal=instruction,
        evaluation=EvaluationSpec(
            evaluator_id=evaluator_id,
            params=dict(evaluation_params),
        ),
        init=init_spec,
        launch_app_bundle_id=launch_app_bundle_id,
        success_criteria=success_criteria,
        max_steps=limits["max_steps"],
        step_timeout_seconds=limits.get("step_timeout_seconds", 300),
        tags=tags,
        description=metadata.get("description"),
        source_file=source_file,
        include_screenshot=metadata.get("include_screenshot", True),
        oracle_actions=oracle_actions,
    )


def _load_yaml(raw: str, source: str) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            f"Loading YAML task files requires PyYAML. Missing dependency while reading: {source}"
        ) from exc
    return yaml.safe_load(raw)
