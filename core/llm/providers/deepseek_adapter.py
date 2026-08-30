"""DeepSeek provider adapter (OpenAI-compatible, SSL verification disabled).

DeepSeek's API is OpenAI-compatible but some Windows environments fail
to connect via httpx's default SSL verification (ConnectError: [Errno 0]).
This adapter creates an httpx.Client with verify=False to work around the
issue while keeping the base OpenAICompatibleAdapter unchanged for
other providers.
"""

from __future__ import annotations

import httpx

from .base import OpenAICompatibleAdapter


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """Adapter for provider=deepseek in models.yaml."""

    provider_name = "deepseek"
    max_output_tokens_payload_key = "max_tokens"

    def __init__(self, client: httpx.Client | None = None) -> None:
        super().__init__(
            client=client or httpx.Client(
                verify=False,
                transport=httpx.HTTPTransport(verify=False),
            )
        )
