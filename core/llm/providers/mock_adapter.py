"""Offline mock provider adapter for local smoke runs."""

from __future__ import annotations

import json
from typing import Any, Dict

from ..types import ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class MockAdapter(ProviderAdapter):
    """Deterministic provider that always emits a terminal success action."""

    provider_name = "mock"
    supported_response_modes = {"tool_calling", "json_text"}

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        message = self._message_from_request(request)
        if request.response_mode == "tool_calling":
            return ProviderResult(
                text="Mock provider completed the prepared smoke task.",
                tool_calls=[
                    ToolCall(
                        name="success",
                        arguments_json=json.dumps({"message": message}, ensure_ascii=False),
                        call_id="mock-success-call",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={"provider": "mock", "mode": "tool_calling"},
            )

        return ProviderResult(
            text=json.dumps({"type": "success", "message": message}, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={"provider": "mock", "mode": "json_text"},
        )

    @staticmethod
    def _message_from_request(request: ProviderRequest) -> str:
        metadata: Dict[str, Any] = request.model_spec.metadata if isinstance(request.model_spec.metadata, dict) else {}
        configured = str(metadata.get("mock_success_message") or "").strip()
        if configured:
            return configured
        return "Mock provider completed the task."
