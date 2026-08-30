"""Protocol-aligned initializer base definitions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class InitStatus(str, Enum):
    """Canonical initializer result states."""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass
class InitResult:
    """Protocol-facing initializer output."""

    status: InitStatus | str
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        raw_status = self.status.value if isinstance(self.status, InitStatus) else str(self.status)
        self.status = InitStatus(raw_status.strip().upper())
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dict")

    def to_dict(self) -> dict[str, Any]:
        """Serialize into the protocol-facing shape."""

        return {
            "status": self.status.value,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


class BaseInitializer(ABC):
    """Base class all initializers must inherit."""

    @abstractmethod
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        raise NotImplementedError
