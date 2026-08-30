"""Minimal initializer loader."""

from __future__ import annotations

import importlib
import inspect

from .base import BaseInitializer


def normalize_initializer_spec(spec: str) -> str:
    """Normalize and validate an import-path initializer spec."""

    if not isinstance(spec, str):
        raise TypeError(f"initializer spec must be a string, got: {type(spec)!r}")

    normalized = spec.strip()
    if not normalized:
        raise ValueError("initializer spec cannot be empty")
    if ":" not in normalized:
        raise ValueError(
            f"initializer spec must be 'module.path:ClassName', got: {spec!r}"
        )

    module_name, class_name = normalized.split(":", 1)
    if not module_name or not class_name:
        raise ValueError(
            f"initializer spec must be 'module.path:ClassName', got: {spec!r}"
        )
    return normalized


def load_initializer(spec) -> BaseInitializer:
    """Load an initializer from an instance, class, or module path string."""

    if isinstance(spec, BaseInitializer):
        return spec

    if inspect.isclass(spec):
        if not issubclass(spec, BaseInitializer):
            raise TypeError(f"initializer class must inherit BaseInitializer: {spec}")
        return spec()

    if isinstance(spec, str):
        spec = normalize_initializer_spec(spec)
        module_name, class_name = spec.split(":", 1)
        module = importlib.import_module(module_name)
        obj = getattr(module, class_name)

        if isinstance(obj, BaseInitializer):
            return obj

        if inspect.isclass(obj):
            if not issubclass(obj, BaseInitializer):
                raise TypeError(
                    f"loaded class must inherit BaseInitializer: {spec!r}"
                )
            return obj()

        raise TypeError(f"loaded object is not a BaseInitializer: {spec!r}")

    raise TypeError(f"invalid initializer spec: {spec!r}")
