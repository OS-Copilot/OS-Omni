"""Shared core data structures used by multiple platform runners."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class TerminalReason(Enum):
    """Reasons for episode termination."""

    SUCCESS = "success"
    FAIL_LLM = "fail_llm"
    FAIL_TIMEOUT = "fail_timeout"
    FAIL_MAX_STEPS = "fail_max_steps"
    FAIL_ERROR = "fail_error"
    FAIL_PARSE = "fail_parse"


@dataclass
class StepRecord:
    """Single-step trajectory record."""

    step_index: int
    timestamp: str
    observation: Dict[str, Any]
    prompt: str
    llm_response: str
    llm_reasoning: Optional[Dict[str, Any]]
    action_parse: Dict[str, Any]
    action_execution: Optional[Dict[str, Any]]
    latency_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "timestamp": self.timestamp,
            "observation": self.observation,
            "prompt": self.prompt,
            "llm_response": self.llm_response,
            "llm_reasoning": self.llm_reasoning,
            "action_parse": self.action_parse,
            "action_execution": self.action_execution,
            "latency_ms": self.latency_ms,
        }

    def to_jsonl_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class EpisodeResult:
    """Final artifact summary for one episode run."""

    task_id: str
    platform: str
    model_id: str
    status: str
    started_at: str
    ended_at: str
    steps_taken: int
    latency_ms: float
    episode_result: Dict[str, Any]
    initializer: Optional[Dict[str, Any]]
    evaluation: Optional[Dict[str, Any]]
    final_observation: Dict[str, Any]

    @property
    def success(self) -> bool:
        return self.status == "PASS"

    @property
    def failure_message(self) -> Optional[str]:
        if self.success:
            return None
        for section in (self.evaluation, self.initializer, self.episode_result):
            if isinstance(section, dict):
                message = section.get("message")
                if message:
                    return str(message)
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "platform": self.platform,
            "model_id": self.model_id,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "steps_taken": self.steps_taken,
            "latency_ms": self.latency_ms,
            "episode_result": self.episode_result,
            "initializer": self.initializer,
            "evaluation": self.evaluation,
            "final_observation": self.final_observation,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def save(self, output_path: str) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")


@dataclass
class SuccessCriteria:
    """Success criteria for task completion."""

    llm_judge: bool = True
    ui_checks: list[Dict[str, Any]] | None = None
    foreground_app: Optional[str] = None

    def __post_init__(self) -> None:
        if self.ui_checks is None:
            self.ui_checks = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "llm_judge": self.llm_judge,
            "ui_checks": self.ui_checks,
            "foreground_app": self.foreground_app,
        }


@dataclass
class ActionDecision:
    """Result of an action planner's decision."""

    action: Optional[Dict[str, Any]]
    parse_success: bool
    raw_response: str
    mode_requested: str
    mode_used: str
    adapter: str
    llm_reasoning: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
