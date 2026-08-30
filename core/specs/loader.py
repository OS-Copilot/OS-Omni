"""Spec loading and validation for benchmark inputs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional

import yaml

from core.llm.llm_client import LLMClientManager
from core.llm.model_registry import ModelRegistry
from core.llm.types import ModelSpec

from .errors import SpecValidationError
from .types import EvaluationSpec, ExecutionSpec, InitSpec, LimitsSpec, TaskSpec


REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_YAML_PATH = REPO_ROOT / "configs" / "models.yaml"

TASK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
ALLOWED_PLATFORMS = {"ios", "macos", "android", "windows", "linux", "web"}
ALLOWED_OBSERVATION_MODES = {
    "screenshot_only",
    "a11y_tree_only",
    "screenshot_and_a11y_tree",
}
ALLOWED_MODEL_PARAMETER_KEYS = {"temperature", "max_output_tokens", "top_p"}


def load_execution_spec(path: str | Path) -> ExecutionSpec:
    raw, source_path = _load_yaml_mapping(path, base_dir=Path.cwd())
    return _parse_execution_spec(raw, source_path)


def load_task_spec(path: str | Path) -> TaskSpec:
    raw, source_path = _load_yaml_mapping(path, base_dir=REPO_ROOT)
    return _parse_task_spec(raw, source_path)


def load_task_specs(paths: Iterable[str | Path]) -> List[TaskSpec]:
    task_specs = [load_task_spec(path) for path in paths]
    if not task_specs:
        raise SpecValidationError("Execution must contain at least one task.")
    platforms = {task.platform for task in task_specs}
    if len(platforms) != 1:
        raise SpecValidationError(
            "All tasks in one execution must target the same platform.",
            details={"platforms": sorted(platforms)},
        )
    return task_specs


def load_model_registry(path: Optional[str | Path] = None) -> ModelRegistry:
    registry_path = Path(path) if path is not None else MODELS_YAML_PATH
    if not registry_path.is_absolute():
        registry_path = (REPO_ROOT / registry_path).resolve()
    registry = ModelRegistry.load(str(registry_path))
    _validate_model_specs(registry)
    return registry


def _parse_execution_spec(raw: Mapping[str, Any], source_path: Path) -> ExecutionSpec:
    task_paths_raw = raw.get("tasks")
    if not isinstance(task_paths_raw, list) or not task_paths_raw:
        raise SpecValidationError(
            "execution.tasks must be a non-empty array.",
            details={"path": str(source_path)},
        )
    task_paths = [_resolve_path(item, base_dir=REPO_ROOT, field_name="tasks") for item in task_paths_raw]

    models = _require_non_empty_string_list(raw, "models", source_path)
    if "agent" in raw:
        raise SpecValidationError(
            "execution.agent has been removed; use top-level action_mode / observation_mode / history_window.",
            details={"path": str(source_path)},
        )
    runtime_fields = _parse_execution_runtime_fields(raw, source_path)

    metadata = raw.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise SpecValidationError(
            "execution.metadata must be an object when provided.",
            details={"path": str(source_path)},
        )

    return ExecutionSpec(
        source_path=source_path,
        task_paths=task_paths,
        models=models,
        action_mode=runtime_fields["action_mode"],
        observation_mode=runtime_fields["observation_mode"],
        history_window=runtime_fields["history_window"],
        metadata=dict(metadata),
        raw=dict(raw),
    )


def _parse_task_spec(raw: Mapping[str, Any], source_path: Path) -> TaskSpec:
    task_id = _require_string(raw, "task_id", source_path)
    if not TASK_ID_PATTERN.match(task_id):
        raise SpecValidationError(
            "task.task_id format is invalid.",
            details={"path": str(source_path), "task_id": task_id},
        )

    platform = _require_string(raw, "platform", source_path)
    if platform not in ALLOWED_PLATFORMS:
        raise SpecValidationError(
            "task.platform is invalid.",
            details={"path": str(source_path), "platform": platform},
        )

    instruction = _require_string(raw, "instruction", source_path)

    init_raw = raw.get("init")
    init_spec: Optional[InitSpec] = None
    if init_raw is not None:
        if not isinstance(init_raw, Mapping):
            raise SpecValidationError(
                "task.init must be an object when provided.",
                details={"path": str(source_path)},
            )
        init_spec = InitSpec(
            initializer_id=_require_string(init_raw, "initializer_id", source_path, namespace="task.init"),
            params=_optional_open_object(init_raw, "params", source_path, namespace="task.init"),
        )

    evaluation_raw = raw.get("evaluation")
    if not isinstance(evaluation_raw, Mapping):
        raise SpecValidationError(
            "task.evaluation is required and must be an object.",
            details={"path": str(source_path)},
        )
    evaluation = EvaluationSpec(
        evaluator_id=_require_string(
            evaluation_raw,
            "evaluator_id",
            source_path,
            namespace="task.evaluation",
        ),
        params=_optional_open_object(evaluation_raw, "params", source_path, namespace="task.evaluation"),
    )

    limits_raw = raw.get("limits")
    if not isinstance(limits_raw, Mapping):
        raise SpecValidationError(
            "task.limits is required and must be an object.",
            details={"path": str(source_path)},
        )
    step_timeout_seconds_raw = limits_raw.get("step_timeout_seconds")
    if step_timeout_seconds_raw is None:
        step_timeout_seconds_raw = {
            "android": 120,
            "linux": 120,
            "macos": 300,
            "ios": 300,
            "windows": 300,
        }.get(platform, 300)
    if not isinstance(step_timeout_seconds_raw, (int, float)) or step_timeout_seconds_raw <= 0:
        step_timeout_seconds_raw = 120
    limits = LimitsSpec(
        max_steps=_require_positive_int(limits_raw, "max_steps", source_path, namespace="task.limits"),
        step_timeout_seconds=float(step_timeout_seconds_raw),
    )

    metadata = raw.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise SpecValidationError(
            "task.metadata must be an object when provided.",
            details={"path": str(source_path)},
        )

    return TaskSpec(
        source_path=source_path,
        task_id=task_id,
        platform=platform,
        instruction=instruction,
        init=init_spec,
        evaluation=evaluation,
        limits=limits,
        metadata=dict(metadata),
        raw=dict(raw),
    )


def _parse_execution_runtime_fields(
    raw: Mapping[str, Any],
    source_path: Path,
) -> Dict[str, Any]:
    if "decision_backend" in raw:
        raise SpecValidationError(
            "execution.decision_backend has been removed; use top-level action_mode instead.",
            details={"path": str(source_path)},
        )
    action_mode = raw.get("action_mode")
    if action_mode is not None:
        if not isinstance(action_mode, str) or not action_mode.strip():
            raise SpecValidationError(
                "execution.action_mode must be a non-empty string when provided.",
                details={"path": str(source_path)},
            )
        action_mode = action_mode.strip()

    observation_mode = raw.get("observation_mode")
    if observation_mode is not None:
        if not isinstance(observation_mode, str) or not observation_mode.strip():
            raise SpecValidationError(
                "execution.observation_mode must be a non-empty string when provided.",
                details={"path": str(source_path)},
            )
        observation_mode = observation_mode.strip().lower()
        if observation_mode not in ALLOWED_OBSERVATION_MODES:
            raise SpecValidationError(
                "execution.observation_mode is invalid.",
                details={"path": str(source_path), "observation_mode": observation_mode},
            )

    history_window = raw.get("history_window")
    if history_window is not None:
        if not isinstance(history_window, int) or history_window <= 0:
            raise SpecValidationError(
                "execution.history_window must be a positive integer when provided.",
                details={"path": str(source_path), "history_window": history_window},
            )

    return {
        "action_mode": action_mode,
        "observation_mode": observation_mode,
        "history_window": history_window,
    }


def _validate_model_specs(registry: ModelRegistry) -> None:
    provider_registry = LLMClientManager.build_default_provider_registry()
    for model_id in registry.list_model_ids():
        model_spec = registry.get(model_id)
        if not provider_registry.has(model_spec.provider):
            raise SpecValidationError(
                "Model provider is declared in configs/models.yaml but no adapter is registered.",
                details={"model_id": model_id, "provider": model_spec.provider},
            )
        _validate_model_parameters(model_spec)


def _validate_model_parameters(model_spec: ModelSpec) -> None:
    params = {
        "temperature": model_spec.temperature,
        "max_output_tokens": model_spec.max_output_tokens,
        "top_p": model_spec.top_p,
    }
    for key in ALLOWED_MODEL_PARAMETER_KEYS:
        value = params[key]
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            raise SpecValidationError(
                "model parameter values must be numeric.",
                details={"model_id": model_spec.model_id, "key": key, "value": value},
            )


def _load_yaml_mapping(path: str | Path, *, base_dir: Optional[Path] = None) -> tuple[Dict[str, Any], Path]:
    resolved_path = _resolve_path(path, base_dir=base_dir or REPO_ROOT, field_name="path")
    try:
        raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecValidationError(
            "Failed to parse YAML file.",
            details={"path": str(resolved_path), "error": str(exc)},
        ) from exc
    if not isinstance(raw, Mapping):
        raise SpecValidationError(
            "YAML top-level must be an object.",
            details={"path": str(resolved_path)},
        )
    return dict(raw), resolved_path


def _resolve_path(path_value: str | Path, *, base_dir: Path, field_name: str) -> Path:
    if not isinstance(path_value, (str, Path)):
        raise SpecValidationError(
            f"{field_name} must be a path string.",
            details={"value": path_value},
        )
    path = Path(path_value)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    if not path.exists():
        raise SpecValidationError(
            f"{field_name} points to a file that does not exist.",
            details={"path": str(path)},
        )
    return path


def _require_string(data: Mapping[str, Any], field_name: str, source_path: Path, *, namespace: str = "task") -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise SpecValidationError(
            f"{namespace}.{field_name} is required and must be a non-empty string.",
            details={"path": str(source_path)},
        )
    return value.strip()


def _require_non_empty_string_list(data: Mapping[str, Any], field_name: str, source_path: Path) -> List[str]:
    values = data.get(field_name)
    if not isinstance(values, list) or not values:
        raise SpecValidationError(
            f"execution.{field_name} must be a non-empty string array.",
            details={"path": str(source_path)},
        )
    out: List[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise SpecValidationError(
                f"execution.{field_name} items must be non-empty strings.",
                details={"path": str(source_path), "value": value},
            )
        out.append(value.strip())
    return out


def _optional_open_object(
    data: Mapping[str, Any],
    field_name: str,
    source_path: Path,
    *,
    namespace: str,
) -> Dict[str, Any]:
    value = data.get(field_name) or {}
    if not isinstance(value, dict):
        raise SpecValidationError(
            f"{namespace}.{field_name} must be an object when provided.",
            details={"path": str(source_path)},
        )
    return dict(value)


def _require_positive_int(
    data: Mapping[str, Any],
    field_name: str,
    source_path: Path,
    *,
    namespace: str,
) -> int:
    value = data.get(field_name)
    if not isinstance(value, int) or value <= 0:
        raise SpecValidationError(
            f"{namespace}.{field_name} must be a positive integer.",
            details={"path": str(source_path), "value": value},
        )
    return value


def _require_positive_number(
    data: Mapping[str, Any],
    field_name: str,
    source_path: Path,
    *,
    namespace: str,
) -> float:
    value = data.get(field_name)
    if not isinstance(value, (int, float)) or value <= 0:
        raise SpecValidationError(
            f"{namespace}.{field_name} must be a positive number.",
            details={"path": str(source_path), "value": value},
        )
    return float(value)


def _require_non_negative_number(
    data: Mapping[str, Any],
    field_name: str,
    source_path: Path,
    *,
    namespace: str,
) -> float:
    value = data.get(field_name)
    if not isinstance(value, (int, float)) or value < 0:
        raise SpecValidationError(
            f"{namespace}.{field_name} must be a non-negative number.",
            details={"path": str(source_path), "value": value},
        )
    return float(value)


def _optional_positive_number(
    data: Mapping[str, Any],
    field_name: str,
    source_path: Path,
    *,
    namespace: str,
) -> Optional[float]:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or value <= 0:
        raise SpecValidationError(
            f"{namespace}.{field_name} must be a positive number when provided.",
            details={"path": str(source_path), "value": value},
        )
    return float(value)
