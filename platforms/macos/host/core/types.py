"""
Core macOS task schema plus shared episode/decision data structures.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.specs.types import EvaluationSpec, InitSpec

from platforms.macos.host.core.task_utils import (
    BaseTaskRegistry,
    load_tasks_from_directory as load_tasks_from_directory_shared,
    parse_success_criteria,
    validate_task_common,
)
from platforms.macos.host.core.runtime_types import (
    ActionDecision,
    EpisodeResult,
    StepRecord,
    SuccessCriteria,
    TerminalReason,
)

logger = logging.getLogger(__name__)


@dataclass
class InitialState:
    """Initial state requirements for a macOS task."""

    start_from_home: bool = True
    launch_app: Optional[str] = None
    terminate_apps: List[str] = field(default_factory=list)
    wait_ms: int = 500

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_from_home": self.start_from_home,
            "launch_app": self.launch_app,
            "terminate_apps": self.terminate_apps,
            "wait_ms": self.wait_ms,
        }


@dataclass
class Task:
    """macOS task definition."""

    id: str
    goal: str
    evaluation: Optional[EvaluationSpec] = None
    init: Optional[InitSpec] = None
    app_bundle_id: Optional[str] = None
    initial_state: InitialState = field(default_factory=InitialState)
    success_criteria: SuccessCriteria = field(default_factory=SuccessCriteria)
    max_steps: int = 100
    step_timeout_seconds: Optional[float] = 120
    tags: List[str] = field(default_factory=list)
    description: Optional[str] = None
    source_file: Optional[str] = None
    include_screenshot: bool = True
    auto_evaluate_after_action: bool = False

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
            "app_bundle_id": self.app_bundle_id,
            "initial_state": self.initial_state.to_dict(),
            "success_criteria": self.success_criteria.to_dict(),
            "max_steps": self.max_steps,
            "step_timeout_seconds": self.step_timeout_seconds,
            "tags": self.tags,
            "description": self.description,
            "include_screenshot": self.include_screenshot,
            "auto_evaluate_after_action": self.auto_evaluate_after_action,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def _parse_initial_state(data: Dict[str, Any]) -> InitialState:
    if not data:
        return InitialState()
    return InitialState(
        start_from_home=data.get("start_from_home", True),
        launch_app=data.get("launch_app"),
        terminate_apps=data.get("terminate_apps", []),
        wait_ms=data.get("wait_ms", 500),
    )


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
        logger_obj=logger,
    )


def create_simple_task(task_id: str, goal: str, **kwargs: Any) -> Task:
    return Task(
        id=task_id,
        goal=goal,
        evaluation=kwargs.get("evaluation"),
        init=kwargs.get("init"),
        app_bundle_id=kwargs.get("app_bundle_id"),
        max_steps=kwargs.get("max_steps", 100),
        step_timeout_seconds=kwargs.get("step_timeout_seconds", 120),
        tags=kwargs.get("tags", []),
        description=kwargs.get("description"),
        include_screenshot=kwargs.get("include_screenshot", True),
        auto_evaluate_after_action=kwargs.get("auto_evaluate_after_action", False),
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
    if str(data.get("platform", "")).strip() != "macos":
        raise ValueError("TaskSpec 'platform' must be 'macos'")

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

    tags = metadata.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    initial_state = InitialState(
        start_from_home=bool(init_params.get("start_from_home", True)),
        launch_app=(
            init_params.get("launch_app")
            or init_params.get("app_name")
            or init_params.get("bundle_id")
        ),
        terminate_apps=(
            init_params.get("terminate_apps", [])
            if isinstance(init_params.get("terminate_apps", []), list)
            else []
        ),
        wait_ms=init_params.get("wait_ms") or 500,
    )

    return Task(
        id=task_id,
        goal=instruction,
        evaluation=EvaluationSpec(
            evaluator_id=evaluator_id,
            params=dict(evaluation_params),
        ),
        init=init_spec,
        app_bundle_id=metadata.get("app_bundle_id"),
        initial_state=initial_state,
        success_criteria=success_criteria,
        max_steps=limits["max_steps"],
        step_timeout_seconds=limits.get("step_timeout_seconds", 120),
        tags=tags,
        description=metadata.get("description"),
        source_file=source_file,
        include_screenshot=metadata.get("include_screenshot", True),
        auto_evaluate_after_action=metadata.get("auto_evaluate_after_action", False),
    )


def _load_yaml(raw: str, source: str) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            f"Loading YAML task files requires PyYAML. Missing dependency while reading: {source}"
        ) from exc
    return yaml.safe_load(raw)
