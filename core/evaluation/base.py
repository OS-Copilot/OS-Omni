"""Protocol-aligned evaluator base definitions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class EvalStatus(str, Enum):
    """Canonical evaluator result states."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNDETERMINED = "UNDETERMINED"
    ERROR = "ERROR"


@dataclass
class EvalResult:
    """Protocol-facing evaluator output."""

    status: EvalStatus | str
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        raw_status = self.status.value if isinstance(self.status, EvalStatus) else str(self.status)
        self.status = EvalStatus(raw_status.strip().upper())
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dict")

    def to_dict(self) -> dict[str, Any]:
        """Serialize into the protocol-facing shape."""

        return {
            "status": self.status.value,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


class BaseEvaluator(ABC):
    """Base class all evaluators must inherit.

    The concrete context payload is intentionally platform-defined.
    Shared code only requires a mapping-like object.
    """

    @abstractmethod
    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        raise NotImplementedError
