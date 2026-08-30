"""Intern provider adapter (OpenAI-compatible chat completions)."""

from __future__ import annotations

from .base import OpenAICompatibleAdapter


class InternAdapter(OpenAICompatibleAdapter):
    """Adapter for provider=intern in models.yaml."""

    provider_name = "intern"
    max_output_tokens_payload_key = "max_tokens"
