"""Base provider adapter contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
import os
import json
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

import httpx

from ..errors import LLMClientError, LLMErrorCode
from ..types import Message, ModelSpec, ProviderCredentials, ToolCall, ToolDefinition
from .utils import (
    build_assistant_message,
    extract_openai_text_content,
    extract_responses_reasoning,
    extract_responses_text_content,
    messages_to_openai,
    messages_to_responses,
    openai_tool_choice_value,
    parse_openai_like_tool_calls,
    parse_responses_tool_calls,
    resolve_chat_completions_url,
    resolve_responses_url,
    responses_tool_choice_value,
    tool_defs_to_openai,
    tool_defs_to_responses,
)


@dataclass
class ProviderRequest:
    """Provider-neutral request object for one model generation."""

    model_spec: ModelSpec
    credentials: ProviderCredentials
    messages: List[Message]
    response_mode: str
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResult:
    """Provider-neutral normalized response result."""

    text: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    raw_response: Optional[Dict[str, Any]] = None
    assistant_message: Optional[Message] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(ABC):
    """Single-provider adapter base class."""

    provider_name: str = ""
    supported_response_modes: Set[str] = {"tool_calling", "json_text"}

    def supports_response_mode(self, mode: str) -> bool:
        return mode in self.supported_response_modes

    @abstractmethod
    def invoke(self, request: ProviderRequest) -> ProviderResult:
        """Execute one provider call for a turn request."""


class OpenAICompatibleAdapter(ProviderAdapter):
    """Base adapter for providers that speak the OpenAI chat-completions shape."""

    supported_response_modes = {"tool_calling", "json_text"}
    max_output_tokens_payload_key = "max_completion_tokens"
    default_reasoning_effort: Optional[str] = "high"
    default_reasoning_generate_summary: Optional[str] = "concise"
    transient_retry_attempts: int = 2
    transient_retry_status_codes: Set[int] = {408, 409, 425, 429, 500, 502, 503, 504}
    transient_retry_base_delay_seconds: float = 1.0

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client()

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        if not self.supports_response_mode(request.response_mode):
            raise LLMClientError(
                LLMErrorCode.MODE_NOT_SUPPORTED,
                f"Requested response_mode is not supported by {self.provider_name} adapter.",
                details={"response_mode": request.response_mode},
            )

        api_mode = self._resolve_api_mode(request)
        if api_mode == "responses":
            url = resolve_responses_url(request.credentials.base_url)
        else:
            url = resolve_chat_completions_url(request.credentials.base_url)
        payload = self._build_payload(request, api_mode=api_mode)
        audit_path = os.environ.get("OS_OMNI_DEEPSEEK_REQUEST_AUDIT")
        audit = None
        if audit_path:
            # Author evaluation guard: check the actual transmitted body.
            # Never record headers, credentials, prompts or image data.
            if payload.get("model") != "deepseek-flash" or api_mode != "responses" or payload.get("reasoning", {}).get("effort") != "none":
                raise ValueError("Author evaluation requires deepseek-flash Responses with reasoning.effort=none")
            audit = {"timestamp": time.time(), "model": payload["model"],
                     "api_mode": api_mode, "reasoning": payload["reasoning"],
                     "request_sent": False}
            # Fingerprint the actual wire-level instructions without logging
            # their text. This distinguishes model policy violations from a
            # dropped system prompt in the benchmark/provider adapter.
            system_texts = []
            if isinstance(payload.get("instructions"), str):
                system_texts.append(payload["instructions"])
            for message in payload.get("input", []):
                if isinstance(message, dict) and message.get("role") in {"system", "developer"}:
                    content = message.get("content", [])
                    if isinstance(content, str):
                        system_texts.append(content)
                    elif isinstance(content, list):
                        system_texts.append("\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict)))
            audit["system_instruction_sha256"] = [hashlib.sha256(text.encode()).hexdigest() for text in system_texts]
            audit["ios_import_prohibition_transmitted"] = any(
                "Appium/XCUITest" in text and "import modules" in text and "Do not create a new driver" in text
                for text in system_texts
            )
            Path(audit_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(audit_path).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({**audit, "phase": "request_verified"}) + "\n")
        data = self._request_json(
            url,
            request.credentials.api_key,
            payload,
            request.timeout_seconds,
        )
        if audit is not None:
            reasoning_items = [item for item in data.get("output", []) if item.get("type") == "reasoning"]
            with Path(audit_path).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({**audit, "phase": "response_received", "request_sent": True,
                    "response_id": data.get("id"), "reasoning_items": len(reasoning_items)}) + "\n")
            if reasoning_items:
                raise ValueError("DeepSeek returned reasoning despite reasoning.effort=none")
        return self._build_result(data, api_mode=api_mode)

    def _build_payload(
        self,
        request: ProviderRequest,
        *,
        api_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible payload builder used by tests and subclasses."""
        resolved_mode = api_mode or self._resolve_api_mode(request)
        if resolved_mode == "responses":
            return self._build_responses_payload(request)
        return self._build_chat_completions_payload(request)

    def _build_chat_completions_payload(self, request: ProviderRequest) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": request.model_spec.model_name,
            "messages": messages_to_openai(request.messages),
        }

        self._apply_common_parameters(payload, request.parameters, api_mode="chat_completions")
        if request.response_mode == "tool_calling":
            if request.tools:
                payload["tools"] = tool_defs_to_openai(request.tools)
            if request.tool_choice is not None:
                payload["tool_choice"] = openai_tool_choice_value(request.tool_choice)
        return payload

    def _build_responses_payload(self, request: ProviderRequest) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": request.model_spec.model_name,
            "input": messages_to_responses(request.messages),
        }

        self._apply_common_parameters(payload, request.parameters, api_mode="responses")
        payload.pop("reasoning_effort", None)

        base_reasoning = payload.get("reasoning")
        if isinstance(base_reasoning, dict):
            normalized_reasoning = dict(base_reasoning)
            normalized_reasoning.pop("generate_summary", None)
            if normalized_reasoning:
                payload["reasoning"] = normalized_reasoning
            else:
                payload.pop("reasoning", None)

        metadata = request.model_spec.metadata if isinstance(request.model_spec.metadata, dict) else {}
        reasoning_effort = str(metadata.get("reasoning_effort") or "").strip()
        reasoning_summary = metadata.get("reasoning_summary")
        if reasoning_effort or reasoning_summary is not None:
            reasoning: Dict[str, Any] = {}
            existing_reasoning = payload.get("reasoning")
            if isinstance(existing_reasoning, dict):
                reasoning.update(existing_reasoning)
            if reasoning_effort:
                reasoning["effort"] = reasoning_effort
            if reasoning_summary is not None:
                reasoning["summary"] = reasoning_summary
            payload["reasoning"] = reasoning

        text_verbosity = str(metadata.get("text_verbosity") or "").strip()
        if text_verbosity:
            payload["text"] = {
                "format": {"type": "text"},
                "verbosity": text_verbosity,
            }

        if request.response_mode == "tool_calling":
            if request.tools:
                payload["tools"] = tool_defs_to_responses(request.tools)
            if request.tool_choice is not None:
                payload["tool_choice"] = responses_tool_choice_value(request.tool_choice)
        return payload

    def _resolve_api_mode(self, request: ProviderRequest) -> str:
        metadata = request.model_spec.metadata if isinstance(request.model_spec.metadata, dict) else {}
        raw_mode = str(metadata.get("api_mode") or "").strip().lower()
        if raw_mode in {"responses", "responses_api"}:
            return "responses"
        return "chat_completions"

    def _apply_common_parameters(
        self,
        payload: Dict[str, Any],
        parameters: Dict[str, Any],
        *,
        api_mode: str,
    ) -> None:
        if parameters.get("temperature") is not None:
            payload["temperature"] = parameters["temperature"]
        if parameters.get("top_p") is not None:
            payload["top_p"] = parameters["top_p"]
        if parameters.get("max_output_tokens") is not None:
            max_output_tokens = int(parameters["max_output_tokens"])
            if api_mode == "responses":
                payload["max_output_tokens"] = max_output_tokens
            else:
                payload[self.max_output_tokens_payload_key] = max_output_tokens

        reasoning = parameters.get("reasoning")
        reasoning_effort = parameters.get("reasoning_effort", self.default_reasoning_effort)
        if api_mode == "responses":
            reasoning_payload: Dict[str, Any] | None = None
            if isinstance(reasoning, dict):
                reasoning_payload = dict(reasoning)
                if parameters.get("reasoning_effort") is None:
                    effort_from_reasoning = reasoning_payload.get("effort")
                    if effort_from_reasoning is not None:
                        reasoning_effort = effort_from_reasoning
            elif reasoning is not None:
                reasoning_payload = {"value": reasoning}

            if reasoning_effort is not None:
                reasoning_payload = dict(reasoning_payload or {})
                reasoning_payload.setdefault("effort", reasoning_effort)

            if reasoning_payload:
                payload["reasoning"] = reasoning_payload
            return

        if reasoning is not None:
            payload["reasoning"] = reasoning
            if parameters.get("reasoning_effort") is None and isinstance(reasoning, dict):
                effort_from_reasoning = reasoning.get("effort")
                if effort_from_reasoning is not None:
                    reasoning_effort = effort_from_reasoning

        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
            if "reasoning" not in payload:
                payload["reasoning"] = {
                    "effort": reasoning_effort,
                    "generate_summary": self.default_reasoning_generate_summary,
                }
            elif isinstance(payload["reasoning"], dict):
                payload["reasoning"].setdefault("effort", reasoning_effort)
                payload["reasoning"].setdefault(
                    "generate_summary",
                    self.default_reasoning_generate_summary,
                )

    def _post(
        self,
        url: str,
        api_key: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float],
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._client.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return response
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

    def _request_json(
        self,
        url: str,
        api_key: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float],
    ) -> Dict[str, Any]:
        attempts = max(1, int(self.transient_retry_attempts) + 1)
        last_error: LLMClientError | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self._post(url, api_key, payload, timeout_seconds)
                return self._parse_response_json(response)
            except LLMClientError as exc:
                last_error = exc
                if attempt >= attempts or not self._should_retry_transient_error(exc):
                    raise
                time.sleep(self.transient_retry_base_delay_seconds * attempt)

        if last_error is not None:
            raise last_error
        raise LLMClientError(
            LLMErrorCode.PROVIDER_REQUEST_FAILED,
            "Provider request failed without a retryable result.",
            details={"provider": self.provider_name},
        )

    def _should_retry_transient_error(self, error: LLMClientError) -> bool:
        if error.code == LLMErrorCode.TIMEOUT:
            return True
        if error.code == LLMErrorCode.INVALID_PROVIDER_RESPONSE:
            return True
        if error.code != LLMErrorCode.PROVIDER_REQUEST_FAILED:
            return False

        status_code = error.details.get("status_code")
        if isinstance(status_code, int):
            return status_code in self.transient_retry_status_codes

        error_text = str(error.details.get("error") or "").lower()
        if error_text:
            transient_markers = (
                "timed out",
                "timeout",
                "temporarily unavailable",
                "connection reset",
                "server disconnected",
                "remote protocol error",
            )
            return any(marker in error_text for marker in transient_markers)
        return False

    def _parse_response_json(self, response: httpx.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMClientError(
                LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                "Provider returned non-JSON response.",
                details={"provider": self.provider_name},
                cause=exc,
            ) from exc
        if not isinstance(data, dict):
            raise LLMClientError(
                LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                "Provider JSON response must be an object.",
                details={"provider": self.provider_name},
            )
        return data

    def _build_chat_completions_result(self, data: Dict[str, Any]) -> ProviderResult:
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(
                LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                "Provider response is missing choices[0].message.",
                details={"provider": self.provider_name},
                cause=exc,
            ) from exc

        text = extract_openai_text_content(message.get("content"))
        tool_calls = parse_openai_like_tool_calls(message.get("tool_calls"))
        assistant_message = build_assistant_message(text, tool_calls)
        return ProviderResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
            raw_response=data,
            assistant_message=assistant_message,
            metadata={"api_mode": "chat_completions"},
        )

    def _build_result(
        self,
        data: Dict[str, Any],
        *,
        api_mode: str = "chat_completions",
    ) -> ProviderResult:
        """Backward-compatible result builder used by tests and subclasses."""
        if api_mode == "responses":
            return self._build_responses_result(data)
        return self._build_chat_completions_result(data)

    def _build_responses_result(self, data: Dict[str, Any]) -> ProviderResult:
        output_items = data.get("output")
        text = extract_responses_text_content(output_items)
        tool_calls = parse_responses_tool_calls(output_items)
        reasoning = extract_responses_reasoning(output_items, data.get("usage"))
        assistant_message = build_assistant_message(text, tool_calls)
        return ProviderResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason=str(data.get("status") or ""),
            usage=data.get("usage"),
            raw_response=data,
            assistant_message=assistant_message,
            metadata={
                "api_mode": "responses",
                "reasoning": reasoning,
                "response_id": data.get("id"),
            },
        )
