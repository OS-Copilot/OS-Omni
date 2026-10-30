"""Anthropic Messages API provider adapter."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import anthropic
import httpx

from ..errors import LLMClientError, LLMErrorCode
from .base import ProviderAdapter, ProviderRequest, ProviderResult
from .utils import build_assistant_message, messages_to_anthropic

DEFAULT_MAX_TOKENS = 16000


class AnthropicAdapter(ProviderAdapter):
    """Adapter for provider=anthropic in models.yaml (POST /v1/messages, text replies).

    metadata.effort is sent as output_config.effort. Claude Opus 5.5 always thinks
    adaptively and effort is its only depth control (default medium), so set it
    explicitly. base_url is the API root without /v1.
    """

    provider_name = "anthropic"
    supported_response_modes = {"json_text"}

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http_client = http_client
        self._clients: Dict[Tuple[str, Optional[str]], anthropic.Anthropic] = {}

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        if not self.supports_response_mode(request.response_mode):
            raise LLMClientError(
                LLMErrorCode.MODE_NOT_SUPPORTED,
                "Requested response_mode is not supported by anthropic adapter.",
                details={"response_mode": request.response_mode},
            )

        system, messages = messages_to_anthropic(request.messages)
        if not messages:
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Anthropic request requires at least one non-system message.",
            )

        params = _build_params(request, system, messages)
        try:
            response = self._client(request).messages.create(**params)
        except anthropic.APITimeoutError as exc:
            raise LLMClientError(
                LLMErrorCode.TIMEOUT,
                "Provider request timed out.",
                details={"provider": self.provider_name},
                cause=exc,
            ) from exc
        except anthropic.APIStatusError as exc:
            raise LLMClientError(
                LLMErrorCode.PROVIDER_REQUEST_FAILED,
                "Provider request failed with HTTP status error.",
                details={
                    "provider": self.provider_name,
                    "status_code": exc.status_code,
                    "response_preview": exc.response.text[:500],
                },
                cause=exc,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMClientError(
                LLMErrorCode.PROVIDER_REQUEST_FAILED,
                "Provider request failed.",
                details={"provider": self.provider_name, "error": str(exc)},
                cause=exc,
            ) from exc

        data = response.to_dict()
        text_chunks = [block.get("text") or "" for block in data.get("content") or [] if block.get("type") == "text"]
        text = "\n".join(chunk for chunk in text_chunks if chunk) or None
        return ProviderResult(
            text=text,
            tool_calls=[],
            finish_reason=data.get("stop_reason"),
            usage=data.get("usage"),
            raw_response=data,
            assistant_message=build_assistant_message(text, []),
        )

    def _client(self, request: ProviderRequest) -> anthropic.Anthropic:
        key = (request.credentials.api_key, request.credentials.base_url)
        if key not in self._clients:
            self._clients[key] = anthropic.Anthropic(
                api_key=request.credentials.api_key,
                base_url=request.credentials.base_url or None,
                http_client=self._http_client,
            )
        return self._clients[key]


def _build_params(request: ProviderRequest, system: Optional[str], messages: list) -> Dict[str, Any]:
    parameters = request.parameters or {}
    max_tokens = parameters.get("max_output_tokens")
    params: Dict[str, Any] = {
        "model": request.model_spec.model_name,
        "max_tokens": int(max_tokens) if max_tokens is not None else DEFAULT_MAX_TOKENS,
        "messages": messages,
    }
    if system:
        params["system"] = system
    # Current Claude models reject sampling parameters; send them only when configured.
    if parameters.get("temperature") is not None:
        params["temperature"] = parameters["temperature"]
    if parameters.get("top_p") is not None:
        params["top_p"] = parameters["top_p"]
    if request.timeout_seconds is not None:
        params["timeout"] = request.timeout_seconds

    metadata = request.model_spec.metadata if isinstance(request.model_spec.metadata, dict) else {}
    effort = str(metadata.get("effort") or "").strip()
    if effort:
        # The installed SDK predates output_config, so it goes in extra_body.
        params["extra_body"] = {"output_config": {"effort": effort}}
    return params
