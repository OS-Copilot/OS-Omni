"""Spec-backed oracle provider for Windows benchmark tasks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

try:  # pragma: no cover - optional Windows-only oracle helper
    from mine.oracle_agent.generate_windows_oracle_agents import build_tool_trajectory
except ModuleNotFoundError:  # pragma: no cover - exercised when the optional helper is absent
    build_tool_trajectory = None  # type: ignore[assignment]

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class WindowsOracleAdapter(ProviderAdapter):
    """Emit deterministic tool calls from pre-generated Windows oracle specs."""

    provider_name = "windows_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    def __init__(self, spec_dir: str | None = None) -> None:
        default_dir = Path(__file__).resolve().parents[3] / "mine" / "oracle_agent" / "windows" / "specs"
        self._spec_dir = Path(spec_dir) if spec_dir else default_dir
        self._tasks_dir = Path(__file__).resolve().parents[3] / "tasks" / "windows"
        self._instruction_index: Dict[str, Dict[str, Any]] | None = None

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        if build_tool_trajectory is None:
            raise ValueError(
                "Windows oracle helper is unavailable: expected optional package "
                "mine.oracle_agent.generate_windows_oracle_agents."
            )
        spec = self._resolve_spec(request.messages)
        source_task_id = str(spec.get("metadata", {}).get("oracle_for") or "").strip()
        tool_trajectory = list(build_tool_trajectory(source_task_id) or [])
        step_index = self._step_index(spec, request.messages, request.metadata)

        if not tool_trajectory:
            raise ValueError(f"No executable tool_trajectory is available for {source_task_id or spec.get('task_id')}")

        if step_index < len(tool_trajectory):
            action = dict(tool_trajectory[step_index] or {})
        else:
            action = {"type": "success", "message": "Oracle plan completed."}

        action_type = str(action.get("type") or "").strip()
        if not action_type:
            raise ValueError(f"Oracle action at step {step_index + 1} is missing a type")

        tool_payload = {k: v for k, v in action.items() if k != "type"}
        assistant_text = self._assistant_text_for_action(spec, action, step_index)

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(tool_payload, ensure_ascii=False),
                        call_id=f"windows-oracle-{sanitize_call_id(str(spec.get('task_id') or 'task'))}-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={
                    "provider": self.provider_name,
                    "task_id": spec.get("task_id"),
                    "trajectory_source": "upper_bound",
                    "step_index": step_index,
                    "action": action,
                },
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        return ProviderResult(
            text=json.dumps(action, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={
                "provider": self.provider_name,
                "task_id": spec.get("task_id"),
                "trajectory_source": "upper_bound",
                "step_index": step_index,
                "action": action,
            },
        )

    @staticmethod
    def _step_index(
        spec: Dict[str, Any],
        messages: List[Message],
        metadata: Dict[str, Any] | None = None,
    ) -> int:
        if isinstance(metadata, dict):
            completed_step_count = metadata.get("completed_step_count")
            if isinstance(completed_step_count, int) and completed_step_count >= 0:
                return completed_step_count

        count = 0
        for message in messages:
            if getattr(message, "role", "") != "assistant":
                continue
            text = WindowsOracleAdapter._normalize_text(message.text_content())
            if text.startswith("oracle step "):
                count += 1
        return count

    def _resolve_spec(self, messages: List[Message]) -> Dict[str, Any]:
        instruction = self._extract_instruction(messages)
        normalized_instruction = self._normalize_text(instruction)
        for path in sorted(self._spec_dir.glob("*.yaml")):
            with path.open("r", encoding="utf-8") as f:
                spec = yaml.safe_load(f) or {}
            if not isinstance(spec, dict):
                continue
            oracle_for = str(spec.get("metadata", {}).get("oracle_for") or "").strip()
            if not oracle_for:
                continue
            original = self._task_instruction_index().get(oracle_for)
            candidate = str((original or {}).get("instruction") or "").strip()
            normalized_candidate = self._normalize_text(candidate)
            comparable_candidate = self._comparable_text(candidate)
            comparable_instruction = self._comparable_text(instruction)
            if candidate and (
                candidate == instruction
                or normalized_candidate == normalized_instruction
                or normalized_candidate in normalized_instruction
                or normalized_instruction in normalized_candidate
                or comparable_candidate == comparable_instruction
                or comparable_candidate in comparable_instruction
                or comparable_instruction in comparable_candidate
            ):
                return spec
        raise ValueError("Windows oracle could not match the current task instruction.")

    def _task_instruction_index(self) -> Dict[str, Dict[str, Any]]:
        if self._instruction_index is not None:
            return self._instruction_index
        index: Dict[str, Dict[str, Any]] = {}
        for path in sorted(self._tasks_dir.rglob("*.yaml")):
            with path.open("r", encoding="utf-8") as f:
                task = yaml.safe_load(f) or {}
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("task_id") or "").strip()
            instruction = str(task.get("instruction") or "").strip()
            if task_id and instruction:
                index[task_id] = {"instruction": instruction, "path": str(path)}
        self._instruction_index = index
        return index

    @staticmethod
    def _extract_instruction(messages: List[Message]) -> str:
        system_text = "\n".join(
            message.text_content()
            for message in messages
            if getattr(message, "role", "") == "system"
        )
        marker = "following task:"
        lower_text = system_text.lower()
        if marker in lower_text:
            index = lower_text.rfind(marker)
            return system_text[index + len(marker):].strip()
        return system_text.strip()

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = " ".join(str(text or "").split()).strip().lower()
        replacements = {
            "“": '"',
            "”": '"',
            "‘": "'",
            "’": "'",
            "鈥淲": '"w',
            "鈥淗": '"h',
            "鈥淏": '"b',
            "鈥?": '"',
        }
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        return normalized

    @classmethod
    def _comparable_text(cls, text: str) -> str:
        normalized = cls._normalize_text(text)
        return re.sub(r"[^a-z0-9]+", " ", normalized).strip()

    @staticmethod
    def _assistant_text_for_action(spec: Dict[str, Any], action: Dict[str, Any], step_index: int) -> str:
        action_type = str(action.get("type") or "").strip()
        return f"Oracle step {step_index + 1}: execute {action_type}."


def sanitize_call_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value).strip("-") or "task"
