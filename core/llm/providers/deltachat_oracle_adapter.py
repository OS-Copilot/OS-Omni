"""Oracle provider for Delta Chat benchmark sanity runs."""

from __future__ import annotations

import json
from typing import List

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class DeltaChatOracleAdapter(ProviderAdapter):
    """Emit a minimal deterministic completion plan for oracle-initialized Delta Chat tasks."""

    provider_name = "deltachat_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    @staticmethod
    def _step_index(messages: List[Message]) -> int:
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        step_index = self._step_index(request.messages)
        if step_index == 0:
            action_type = "wait"
            assistant_text = "The oracle initializer already applied the expected Delta Chat messages. Wait briefly for the UI to settle."
            payload = {"ms": 1000}
        else:
            action_type = "success"
            assistant_text = "The Delta Chat oracle task is complete."
            payload = {"message": "Delta Chat oracle task completed."}

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(payload, ensure_ascii=False),
                        call_id=f"deltachat-oracle-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={"provider": self.provider_name, "step_index": step_index, "action": payload},
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        text_payload = {"type": action_type, **payload}
        return ProviderResult(
            text=json.dumps(text_payload, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={"provider": self.provider_name, "step_index": step_index, "action": payload},
        )
