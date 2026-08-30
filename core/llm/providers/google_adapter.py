"""Google Gemini provider adapter."""

from __future__ import annotations

import json
from typing import Any, Dict
from urllib.parse import quote

import httpx

from ..errors import LLMClientError, LLMErrorCode
from ..types import ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult
from .utils import (
    build_assistant_message,
    gemini_tool_choice_config,
    messages_to_gemini,
    tool_defs_to_gemini,
)


class GoogleAdapter(ProviderAdapter):
    """Adapter for provider=google in models.yaml."""

    provider_name = "google"
    supported_response_modes = {"tool_calling", "json_text"}
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client()

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        if not self.supports_response_mode(request.response_mode):
            raise LLMClientError(
                LLMErrorCode.MODE_NOT_SUPPORTED,
                "Requested response_mode is not supported by google adapter.",
                details={"response_mode": request.response_mode},
            )

        url = _resolve_generate_content_url(
            request.credentials.base_url,
            request.model_spec.model_name,
            request.credentials.api_key,
        )
        system_instruction, contents = messages_to_gemini(request.messages)
        if not contents:
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Gemini request requires at least one non-system message.",
            )

        payload: Dict[str, Any] = {"contents": contents}
        if system_instruction is not None:
            payload["systemInstruction"] = system_instruction

        generation_config = _build_generation_config(request.parameters)
        if generation_config:
            payload["generationConfig"] = generation_config

        if request.response_mode == "tool_calling":
            if request.tools:
                declarations = tool_defs_to_gemini(request.tools)
                if declarations:
                    payload["tools"] = [{"functionDeclarations": declarations}]
            if request.tool_choice is not None:
                payload["toolConfig"] = {
                    "functionCallingConfig": gemini_tool_choice_config(request.tool_choice)
                }

        try:
            response = self._client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=request.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMClientError(
                LLMErrorCode.TIMEOUT,
                "Provider request timed out.",
                details={"provider": self.provider_name},
                cause=exc,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMClientError(
                LLMErrorCode.PROVIDER_REQUEST_FAILED,
                "Provider request failed with HTTP status error.",
                details={
                    "provider": self.provider_name,
                    "status_code": exc.response.status_code,
                    "response_preview": exc.response.text[:500],
                },
                cause=exc,
            ) from exc
        except httpx.RequestError as exc:
            raise LLMClientError(
                LLMErrorCode.PROVIDER_REQUEST_FAILED,
                "Provider request failed.",
                details={"provider": self.provider_name, "error": str(exc)},
                cause=exc,
            ) from exc

        data = _parse_response_json(response)
        try:
            candidate = data["candidates"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(
                LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                "Provider response is missing candidates[0].",
                details={"provider": self.provider_name},
                cause=exc,
            ) from exc

        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        if not isinstance(parts, list):
            raise LLMClientError(
                LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                "Gemini content.parts must be an array.",
                details={"provider": self.provider_name},
            )

        text_chunks = []
        tool_calls = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                text_chunks.append(text)

            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                name = function_call.get("name")
                if isinstance(name, str) and name.strip():
                    args = function_call.get("args")
                    if isinstance(args, str):
                        arguments_json = args
                    elif args is None:
                        arguments_json = "{}"
                    else:
                        arguments_json = json.dumps(args, ensure_ascii=False)
                    tool_calls.append(ToolCall(name=name.strip(), arguments_json=arguments_json))

        text = "\n".join(chunk for chunk in text_chunks if chunk) or None
        assistant_message = build_assistant_message(text, tool_calls)

        return ProviderResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason=candidate.get("finishReason"),
            usage=data.get("usageMetadata"),
            raw_response=data,
            assistant_message=assistant_message,
        )


def _resolve_generate_content_url(
    base_url: str | None,
    model_name: str,
    api_key: str,
) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "base_url is required for google provider.",
            details={"provider": "google"},
        )

    source = base_url.strip().rstrip("/")

    # Full endpoint override.
    if ":generateContent" in source:
        separator = "&" if "?" in source else "?"
        if "key=" in source:
            return source
        return f"{source}{separator}key={quote(api_key)}"

    return f"{source}/models/{quote(model_name, safe='')}:" \
        f"generateContent?key={quote(api_key)}"


def _build_generation_config(parameters: Dict[str, Any]) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    if not parameters:
        return config

    if parameters.get("temperature") is not None:
        config["temperature"] = parameters["temperature"]
    if parameters.get("top_p") is not None:
        config["topP"] = parameters["top_p"]
    if parameters.get("max_output_tokens") is not None:
        config["maxOutputTokens"] = parameters["max_output_tokens"]
    return config


def _parse_response_json(response: httpx.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise LLMClientError(
            LLMErrorCode.INVALID_PROVIDER_RESPONSE,
            "Provider returned non-JSON response.",
            details={"provider": "google"},
            cause=exc,
        ) from exc
    if not isinstance(data, dict):
        raise LLMClientError(
            LLMErrorCode.INVALID_PROVIDER_RESPONSE,
            "Provider JSON response must be an object.",
            details={"provider": "google"},
        )
    return data
