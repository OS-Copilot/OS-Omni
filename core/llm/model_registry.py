"""Model registry loader for configs/models.yaml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import yaml

from .errors import LLMClientError, LLMErrorCode
from .types import ModelSpec


_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class ModelRegistry:
    """In-memory model registry keyed by model_id."""

    def __init__(self, models: Dict[str, ModelSpec], *, source_path: Optional[str] = None) -> None:
        self._models = dict(models)
        self.source_path = source_path

    @classmethod
    def load(cls, path: str) -> "ModelRegistry":
        file_path = Path(path)
        if not file_path.exists():
            raise LLMClientError(
                LLMErrorCode.MODEL_REGISTRY_INVALID,
                "models.yaml does not exist.",
                details={"path": str(file_path)},
            )

        try:
            raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise LLMClientError(
                LLMErrorCode.MODEL_REGISTRY_INVALID,
                "Failed to parse models.yaml.",
                details={"path": str(file_path)},
                cause=exc,
            ) from exc

        if not isinstance(raw, Mapping):
            raise LLMClientError(
                LLMErrorCode.MODEL_REGISTRY_INVALID,
                "models.yaml top-level must be an object.",
                details={"path": str(file_path)},
            )

        raw_models = raw.get("models")
        if not isinstance(raw_models, Mapping):
            raise LLMClientError(
                LLMErrorCode.MODEL_REGISTRY_INVALID,
                "models.yaml must contain object field 'models'.",
                details={"path": str(file_path)},
            )

        parsed: Dict[str, ModelSpec] = {}
        for model_id, model_data in raw_models.items():
            if not isinstance(model_id, str) or not model_id.strip():
                raise LLMClientError(
                    LLMErrorCode.MODEL_REGISTRY_INVALID,
                    "model_id must be a non-empty string.",
                    details={"model_id": model_id},
                )
            model_id = model_id.strip()
            if not _MODEL_ID_PATTERN.match(model_id):
                raise LLMClientError(
                    LLMErrorCode.MODEL_REGISTRY_INVALID,
                    "model_id format is invalid.",
                    details={"model_id": model_id},
                )
            parsed[model_id] = _parse_model_spec(model_id, model_data)

        return cls(parsed, source_path=str(file_path))

    def get(self, model_id: str) -> ModelSpec:
        if model_id not in self._models:
            raise LLMClientError(
                LLMErrorCode.MODEL_NOT_FOUND,
                "model_id not found in model registry.",
                details={"model_id": model_id},
            )
        return self._models[model_id]

    def has(self, model_id: str) -> bool:
        return model_id in self._models

    def list_model_ids(self) -> Iterable[str]:
        return self._models.keys()

    def __contains__(self, model_id: str) -> bool:
        return self.has(model_id)

    def __len__(self) -> int:
        return len(self._models)


def _parse_model_spec(model_id: str, model_data: Any) -> ModelSpec:
    if not isinstance(model_data, Mapping):
        raise LLMClientError(
            LLMErrorCode.MODEL_REGISTRY_INVALID,
            "Each model config must be an object.",
            details={"model_id": model_id},
        )

    provider = _required_str(model_data, "provider", model_id=model_id)
    model_name = _required_str(model_data, "model_name", model_id=model_id)
    api_key_env = _required_str(model_data, "api_key_env", model_id=model_id)

    base_url = _optional_str(model_data, "base_url", model_id=model_id)
    base_url_env = _optional_str(model_data, "base_url_env", model_id=model_id)
    if base_url is None and base_url_env is None:
        raise LLMClientError(
            LLMErrorCode.MODEL_REGISTRY_INVALID,
            "At least one of base_url or base_url_env is required.",
            details={"model_id": model_id},
        )

    temperature = _optional_number(model_data, "temperature", model_id=model_id)
    max_output_tokens = _optional_number(model_data, "max_output_tokens", model_id=model_id)
    top_p = _optional_number(model_data, "top_p", model_id=model_id)

    metadata = model_data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise LLMClientError(
            LLMErrorCode.MODEL_REGISTRY_INVALID,
            "metadata must be an object when provided.",
            details={"model_id": model_id},
        )

    return ModelSpec(
        model_id=model_id,
        provider=provider,
        model_name=model_name,
        api_key_env=api_key_env,
        base_url=base_url,
        base_url_env=base_url_env,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        top_p=top_p,
        metadata=metadata,
    )


def _required_str(data: Mapping[str, Any], field_name: str, *, model_id: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise LLMClientError(
            LLMErrorCode.MODEL_REGISTRY_INVALID,
            f"{field_name} is required and must be a non-empty string.",
            details={"model_id": model_id, "field": field_name},
        )
    return value.strip()


def _optional_str(data: Mapping[str, Any], field_name: str, *, model_id: str) -> Optional[str]:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LLMClientError(
            LLMErrorCode.MODEL_REGISTRY_INVALID,
            f"{field_name} must be a non-empty string when provided.",
            details={"model_id": model_id, "field": field_name},
        )
    return value.strip()


def _optional_number(data: Mapping[str, Any], field_name: str, *, model_id: str) -> Optional[float]:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise LLMClientError(
            LLMErrorCode.MODEL_REGISTRY_INVALID,
            f"{field_name} must be numeric when provided.",
            details={"model_id": model_id, "field": field_name, "value": value},
        )
    return float(value)
