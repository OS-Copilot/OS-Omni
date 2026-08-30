"""Deterministic Android oracle adapter.

Android oracle completion is applied by the Android initialization runner after
the normal task initializer succeeds. This provider is the explicit agent-side
counterpart: it emits a deterministic success action once that oracle state has
been prepared, so benchmark runs can use a first-class oracle model instead of
the generic scripted provider.
"""

from __future__ import annotations

import json
from typing import List

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class AndroidOracleAdapter(ProviderAdapter):
    """Report success for Android tasks whose state was completed during init."""

    provider_name = "android_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        step_index = self._step_index(request.messages)
        task_id = str(request.metadata.get("task_id") or "").strip()

        if step_index == 0:
            action = {
                "type": "success",
                "message": "Android oracle completion should now match the evaluator.",
                "assistant_text": "The Android oracle state is already prepared.",
            }
        else:
            action = {
                "type": "success",
                "message": "Android oracle task is complete.",
                "assistant_text": "The Android oracle task is complete.",
            }

        action_type = str(action["type"])
        assistant_text = str(action["assistant_text"])
        tool_payload = {k: v for k, v in action.items() if k not in {"type", "assistant_text"}}

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(tool_payload, ensure_ascii=False),
                        call_id=f"android-oracle-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={
                    "provider": self.provider_name,
                    "task_id": task_id,
                    "step_index": step_index,
                },
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        if request.response_mode == "json_text":
            return ProviderResult(
                text=f"{assistant_text}\n```DONE\n```",
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={
                    "provider": self.provider_name,
                    "task_id": task_id,
                    "step_index": step_index,
                },
            )

        json_action = dict(action)
        json_action.pop("assistant_text", None)
        return ProviderResult(
            text=json.dumps(json_action, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={
                "provider": self.provider_name,
                "task_id": task_id,
                "step_index": step_index,
            },
        )

    @staticmethod
    def _step_index(messages: List[Message]) -> int:
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")
