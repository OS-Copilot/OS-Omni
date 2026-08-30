"""Errors used by shared benchmark spec loaders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class SpecValidationError(Exception):
    """Structured validation error for execution/task/runtime inputs."""

    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if not self.details:
            return self.message
        return f"{self.message} | details={self.details}"
