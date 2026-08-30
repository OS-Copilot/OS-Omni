"""Deterministic scripted provider for repeatable local agent runs."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class ScriptedAdapter(ProviderAdapter):
    """Provider that emits a predefined action sequence from model metadata."""

    provider_name = "scripted"
    supported_response_modes = {"tool_calling", "json_text"}

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        metadata = request.model_spec.metadata if isinstance(request.model_spec.metadata, dict) else {}
        actions = metadata.get("script_actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError("scripted provider requires model metadata.script_actions")

        step_index = self._step_index(request.messages)
        action = self._resolve_action(actions, step_index)
        if not isinstance(action, dict):
            raise ValueError("scripted action must be an object")

        action_type = str(action.get("type") or "").strip()
        if not action_type:
            raise ValueError("scripted action requires non-empty type")

        tool_payload = {k: v for k, v in action.items() if k != "type"}
        assistant_text = str(action.get("assistant_text") or f"Scripted step {step_index + 1}: {action_type}")

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(tool_payload, ensure_ascii=False),
                        call_id=f"scripted-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={"provider": "scripted", "step_index": step_index, "action": action},
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        json_action = dict(action)
        json_action.pop("assistant_text", None)
        return ProviderResult(
            text=json.dumps(json_action, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={"provider": "scripted", "step_index": step_index, "action": action},
        )

    @staticmethod
    def _step_index(messages: List[Message]) -> int:
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    @staticmethod
    def _resolve_action(actions: List[Any], step_index: int) -> Dict[str, Any]:
        if step_index < len(actions):
            action = actions[step_index]
            if isinstance(action, dict):
                return dict(action)
        return {"type": "success", "message": "Scripted plan completed."}
