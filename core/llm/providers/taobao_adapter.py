"""Taobao provider adapter (OpenAI-compatible chat completions)."""

from __future__ import annotations

from typing import Any, Dict

from .base import OpenAICompatibleAdapter, ProviderResult
from .utils import build_assistant_message, extract_think_tag_content


class TaobaoAdapter(OpenAICompatibleAdapter):
    """Adapter for provider=taobao in models.yaml."""

    provider_name = "taobao"
    max_output_tokens_payload_key = "max_completion_tokens"

    def _build_result(
        self,
        data: Dict[str, Any],
        *,
        api_mode: str = "chat_completions",
    ) -> ProviderResult:
        result = super()._build_result(data, api_mode=api_mode)
        if not result.text:
            return result
        text, reasoning_cot = extract_think_tag_content(result.text)
        if text != result.text:
            result.text = text
            result.assistant_message = build_assistant_message(text, result.tool_calls)
        if reasoning_cot:
            result.reasoning_content = reasoning_cot
        return result
