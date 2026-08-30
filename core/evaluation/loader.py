"""Minimal evaluator loader."""

from __future__ import annotations

import importlib
import inspect

from .base import BaseEvaluator


def normalize_evaluator_spec(spec: str) -> str:
    """Normalize and validate an import-path evaluator spec."""

    if not isinstance(spec, str):
        raise TypeError(f"evaluator spec must be a string, got: {type(spec)!r}")

    normalized = spec.strip()
    if not normalized:
        raise ValueError("evaluator spec cannot be empty")
    if ":" not in normalized:
        raise ValueError(
            f"evaluator spec must be 'module.path:ClassName', got: {spec!r}"
        )

    module_name, class_name = normalized.split(":", 1)
    if not module_name or not class_name:
        raise ValueError(
            f"evaluator spec must be 'module.path:ClassName', got: {spec!r}"
        )
    return normalized


def load_evaluator(spec) -> BaseEvaluator:
    """Load an evaluator from an instance, class, or module path string."""

    if isinstance(spec, BaseEvaluator):
        return spec

    if inspect.isclass(spec):
        if not issubclass(spec, BaseEvaluator):
            raise TypeError(f"evaluator class must inherit BaseEvaluator: {spec}")
        return spec()

    if isinstance(spec, str):
        spec = normalize_evaluator_spec(spec)
        module_name, class_name = spec.split(":", 1)
        module = importlib.import_module(module_name)
        obj = getattr(module, class_name)

        if isinstance(obj, BaseEvaluator):
            return obj

        if inspect.isclass(obj):
            if not issubclass(obj, BaseEvaluator):
                raise TypeError(
                    f"loaded class must inherit BaseEvaluator: {spec!r}"
                )
            return obj()

        raise TypeError(f"loaded object is not a BaseEvaluator: {spec!r}")

    raise TypeError(f"invalid evaluator spec: {spec!r}")
