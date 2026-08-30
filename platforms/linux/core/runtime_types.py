"""Platform-local re-export of shared runtime artifact types."""

from core.platform_shared.runtime_types import (
    ActionDecision,
    EpisodeResult,
    StepRecord,
    SuccessCriteria,
    TerminalReason,
)

__all__ = [
    "ActionDecision",
    "EpisodeResult",
    "StepRecord",
    "SuccessCriteria",
    "TerminalReason",
]
