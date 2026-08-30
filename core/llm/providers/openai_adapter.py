"""OpenAI provider adapter."""

from __future__ import annotations

from .base import OpenAICompatibleAdapter


class OpenAIAdapter(OpenAICompatibleAdapter):
    """Adapter for provider=openai in models.yaml."""

    provider_name = "openai"
    max_output_tokens_payload_key = "max_completion_tokens"
