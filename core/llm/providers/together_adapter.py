"""Together provider adapter with mandatory streaming support.

This adapter intentionally does not inherit from OpenAICompatibleAdapter.
Together's Qwen models require stream=True in practice, and reasoning is not
returned as a separate field. Instead, reasoning arrives inline inside
<think>...</think> blocks within streamed content.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List, Mapping, Optional

import httpx

from ..errors import LLMClientError, LLMErrorCode
from ..types import ImagePart, Message, TextPart, ToolCall, ToolDefinition
from .base import ProviderAdapter, ProviderRequest, ProviderResult
from .utils import (
    build_assistant_message,
    extract_think_tag_content,
    image_path_to_data_url,
    openai_tool_choice_value,
    parse_openai_like_tool_calls,
    resolve_chat_completions_url,
    tool_defs_to_openai,
)


class TogetherAdapter(ProviderAdapter):
    """Adapter for provider=together in models.yaml."""

    provider_name = "together"
    supported_response_modes = {"tool_calling", "json_text"}

    max_attempts: int = 6
    retry_base_seconds: float = 1.0
    retry_cap_seconds: float = 30.0
    retryable_status_codes = {408, 409, 425, 429, 500, 502, 503, 504}

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client()

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        if not self.supports_response_mode(request.response_mode):
            raise LLMClientError(
                LLMErrorCode.MODE_NOT_SUPPORTED,
                f"Requested response_mode is not supported by {self.provider_name} adapter.",
                details={"response_mode": request.response_mode},
            )

        metadata = request.model_spec.metadata if isinstance(request.model_spec.metadata, dict) else {}
        if request.response_mode == "tool_calling" and not _model_supports_tool_calling(
            request.model_spec.model_name,
            metadata,
        ):
            raise LLMClientError(
                LLMErrorCode.MODE_NOT_SUPPORTED,
                f"{request.model_spec.model_name} does not support tool_calling.",
                details={
                    "provider": self.provider_name,
                    "model": request.model_spec.model_name,
                    "response_mode": request.response_mode,
                },
            )

        url = resolve_chat_completions_url(request.credentials.base_url)
        payload = self._build_payload(request)
        if payload.get("stream"):
            response_data = self._request_stream_json(
                url,
                request.credentials.api_key,
                payload,
                request.timeout_seconds,
            )
        else:
            try:
                response_data = self._request_json(
                    url,
                    request.credentials.api_key,
                    payload,
                    request.timeout_seconds,
                )
            except LLMClientError as exc:
                if not self._should_fallback_to_stream(exc):
                    raise
                stream_payload = dict(payload)
                stream_payload["stream"] = True
                response_data = self._request_stream_json(
                    url,
                    request.credentials.api_key,
                    stream_payload,
                    request.timeout_seconds,
                )
        return self._build_result(response_data)

    def _build_payload(self, request: ProviderRequest) -> Dict[str, Any]:
        metadata = request.model_spec.metadata if isinstance(request.model_spec.metadata, dict) else {}
        enable_thinking = _bool_with_default(metadata.get("enable_thinking"), default=True)

        temperature = request.parameters.get("temperature")
        if temperature is None:
            temperature = 1.0 if enable_thinking else 0.7

        top_p = request.parameters.get("top_p")
        if top_p is None:
            top_p = 0.95 if enable_thinking else 0.8

        stream = _bool_with_default(metadata.get("stream"), default=False)

        payload: Dict[str, Any] = {
            "model": request.model_spec.model_name,
            "messages": _messages_to_together(request.messages),
            "stream": stream,
            "temperature": float(temperature),
            "top_p": float(top_p),
        }

        max_output_tokens = request.parameters.get("max_output_tokens")
        if max_output_tokens is not None:
            payload["max_tokens"] = int(max_output_tokens)

        presence_penalty = metadata.get("presence_penalty", 1.5)
        if isinstance(presence_penalty, (int, float)):
            payload["presence_penalty"] = float(presence_penalty)

        frequency_penalty = metadata.get("frequency_penalty")
        if isinstance(frequency_penalty, (int, float)):
            payload["frequency_penalty"] = float(frequency_penalty)

        repetition_penalty = metadata.get("repetition_penalty")
        if isinstance(repetition_penalty, (int, float)):
            payload["repetition_penalty"] = float(repetition_penalty)

        safety_model = metadata.get("safety_model")
        if isinstance(safety_model, str) and safety_model.strip():
            payload["safety_model"] = safety_model.strip()

        reasoning_enabled = metadata.get("reasoning_enabled")
        if reasoning_enabled is not None:
            payload["reasoning"] = {"enabled": _bool_with_default(reasoning_enabled, default=True)}

        extra_body: Dict[str, Any] = {
            "top_k": _int_with_default(metadata.get("top_k"), default=20),
            "min_p": _float_with_default(metadata.get("min_p"), default=0.0),
            "chat_template_kwargs": {
                "enable_thinking": enable_thinking,
            },
        }
        metadata_extra_body = metadata.get("extra_body")
        if isinstance(metadata_extra_body, Mapping):
            extra_body = _deep_merge_dicts(extra_body, metadata_extra_body)
        # This adapter posts raw JSON with httpx, so there is no SDK to unpack
        # `extra_body` for us. Together ignores an unknown top-level key, which
        # silently dropped top_k/min_p and chat_template_kwargs (so
        # enable_thinking=false never reached the model). Merge the fields into
        # the request body itself, keeping explicit payload keys authoritative.
        for key, value in extra_body.items():
            payload.setdefault(key, value)

        if request.response_mode == "tool_calling":
            if request.tools:
                payload["tools"] = tool_defs_to_openai(request.tools)
            if request.tool_choice is not None:
                payload["tool_choice"] = openai_tool_choice_value(request.tool_choice)

        return payload

    def _request_json(
        self,
        url: str,
        api_key: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float],
    ) -> Dict[str, Any]:
        last_error: LLMClientError | None = None
        for attempt in range(self.max_attempts):
            try:
                return self._post_json(url, api_key, payload, timeout_seconds)
            except LLMClientError as exc:
                last_error = exc
                if attempt >= self.max_attempts - 1 or not self._should_retry(exc):
                    raise
                time.sleep(self._retry_sleep_seconds(exc, attempt))

        if last_error is not None:
            raise last_error
        raise LLMClientError(
            LLMErrorCode.PROVIDER_REQUEST_FAILED,
            "Together provider request failed without a retryable result.",
            details={"provider": self.provider_name},
        )

    def _post_json(
        self,
        url: str,
        api_key: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float],
    ) -> Dict[str, Any]:
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
            return self._consume_non_stream_response(response)
        except httpx.TimeoutException as exc:
            raise LLMClientError(
                LLMErrorCode.TIMEOUT,
                "Provider request timed out.",
                details={"provider": self.provider_name},
                cause=exc,
            ) from exc
        except httpx.HTTPStatusError as exc:
            retry_after = None
            header_value = exc.response.headers.get("retry-after")
            if header_value:
                try:
                    retry_after = float(header_value)
                except ValueError:
                    retry_after = None
            response_preview = ""
            try:
                exc.response.read()
                response_preview = exc.response.text[:5000]
            except Exception:
                response_preview = ""
            raise LLMClientError(
                LLMErrorCode.PROVIDER_REQUEST_FAILED,
                "Provider request failed with HTTP status error.",
                details={
                    "provider": self.provider_name,
                    "status_code": exc.response.status_code,
                    "response_preview": response_preview,
                    "retry_after": retry_after,
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

    def _request_stream_json(
        self,
        url: str,
        api_key: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float],
    ) -> Dict[str, Any]:
        last_error: LLMClientError | None = None
        for attempt in range(self.max_attempts):
            try:
                return self._post_and_collect_stream(url, api_key, payload, timeout_seconds)
            except LLMClientError as exc:
                last_error = exc
                if attempt >= self.max_attempts - 1 or not self._should_retry(exc):
                    raise
                time.sleep(self._retry_sleep_seconds(exc, attempt))

        if last_error is not None:
            raise last_error
        raise LLMClientError(
            LLMErrorCode.PROVIDER_REQUEST_FAILED,
            "Together provider request failed without a retryable result.",
            details={"provider": self.provider_name},
        )

    def _post_and_collect_stream(
        self,
        url: str,
        api_key: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float],
    ) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with self._client.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            ) as response:
                response.raise_for_status()
                return self._consume_stream_response(response)
        except httpx.TimeoutException as exc:
            raise LLMClientError(
                LLMErrorCode.TIMEOUT,
                "Provider request timed out.",
                details={"provider": self.provider_name},
                cause=exc,
            ) from exc
        except httpx.HTTPStatusError as exc:
            retry_after = None
            header_value = exc.response.headers.get("retry-after")
            if header_value:
                try:
                    retry_after = float(header_value)
                except ValueError:
                    retry_after = None
            response_preview = ""
            try:
                exc.response.read()
                response_preview = exc.response.text[:500]
            except Exception:
                response_preview = ""
            raise LLMClientError(
                LLMErrorCode.PROVIDER_REQUEST_FAILED,
                "Provider request failed with HTTP status error.",
                details={
                    "provider": self.provider_name,
                    "status_code": exc.response.status_code,
                    "response_preview": response_preview,
                    "retry_after": retry_after,
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

    def _consume_stream_response(self, response: httpx.Response) -> Dict[str, Any]:
        content_type = str(response.headers.get("content-type") or "").lower()
        if content_type and "text/event-stream" not in content_type:
            return self._consume_non_stream_response(response)

        stream_id = None
        stream_model = None
        usage: Optional[Dict[str, Any]] = None
        finish_reason: Optional[str] = None
        raw_content_parts: List[str] = []
        direct_reasoning_parts: List[str] = []
        tool_call_state: Dict[int, Dict[str, Any]] = {}
        saw_event = False

        for raw_line in response.iter_lines():
            if raw_line is None:
                continue
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue

            payload_text = line[len("data:") :].strip()
            if not payload_text:
                continue
            if payload_text == "[DONE]":
                saw_event = True
                break

            saw_event = True
            try:
                data = json.loads(payload_text)
            except json.JSONDecodeError as exc:
                raise LLMClientError(
                    LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                    "Together stream emitted invalid JSON.",
                    details={"provider": self.provider_name, "payload_preview": payload_text[:500]},
                    cause=exc,
                ) from exc

            if not isinstance(data, dict):
                raise LLMClientError(
                    LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                    "Together stream chunk must be a JSON object.",
                    details={"provider": self.provider_name},
                )

            stream_id = stream_id or data.get("id")
            if data.get("model") is not None:
                stream_model = data.get("model")
            if isinstance(data.get("usage"), Mapping):
                usage = dict(data["usage"])

            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, Mapping):
                continue

            if isinstance(choice.get("finish_reason"), str) and choice.get("finish_reason"):
                finish_reason = str(choice.get("finish_reason"))

            delta = choice.get("delta")
            if isinstance(delta, Mapping):
                self._append_delta_content(raw_content_parts, delta.get("content"))
                self._append_reasoning_content(direct_reasoning_parts, delta)
                self._merge_stream_tool_calls(tool_call_state, delta.get("tool_calls"))

            message = choice.get("message")
            if isinstance(message, Mapping):
                self._append_delta_content(raw_content_parts, message.get("content"))
                self._merge_stream_tool_calls(tool_call_state, message.get("tool_calls"))

        if not saw_event:
            return self._consume_non_stream_response(response)

        raw_text = "".join(raw_content_parts) or None
        text, reasoning_content = extract_think_tag_content(raw_text)
        if reasoning_content is None:
            direct_reasoning = "".join(direct_reasoning_parts).strip()
            reasoning_content = direct_reasoning or None

        tool_calls = self._finalize_stream_tool_calls(tool_call_state)
        if finish_reason is None and tool_calls:
            finish_reason = "tool_calls"
        if finish_reason is None:
            finish_reason = "stop"

        raw_tool_calls = [
            {
                "id": tool.call_id,
                "type": "function",
                "function": {
                    "name": tool.name,
                    "arguments": tool.arguments_json,
                },
            }
            for tool in tool_calls
        ]

        return {
            "id": stream_id,
            "model": stream_model,
            "usage": usage,
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {
                        "role": "assistant",
                        "content": raw_text,
                        "tool_calls": raw_tool_calls or None,
                    },
                }
            ],
            "reasoning_content": reasoning_content,
            "streamed": True,
        }

    def _consume_non_stream_response(self, response: httpx.Response) -> Dict[str, Any]:
        try:
            response.read()
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

    def _build_result(self, data: Dict[str, Any]) -> ProviderResult:
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

        explicit_reasoning = data.get("reasoning_content")
        if explicit_reasoning is None and isinstance(message, Mapping):
            explicit_reasoning = message.get("reasoning")
        text, reasoning_content = _extract_text_and_reasoning(
            message.get("content"),
            explicit_reasoning,
        )
        tool_calls = parse_openai_like_tool_calls(message.get("tool_calls"))
        assistant_message = build_assistant_message(text, tool_calls)
        reasoning_metadata = _build_reasoning_metadata(reasoning_content, data.get("usage"))
        return ProviderResult(
            text=text,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
            raw_response=data,
            assistant_message=assistant_message,
            metadata={
                "api_mode": "chat_completions",
                "streamed": bool(data.get("streamed")),
                "response_id": data.get("id"),
                "reasoning": reasoning_metadata,
            },
        )

    def _append_delta_content(self, chunks: List[str], content: Any) -> None:
        text = _extract_content_text(content)
        if text:
            chunks.append(text)

    def _append_reasoning_content(self, chunks: List[str], delta: Mapping[str, Any]) -> None:
        for key in ("reasoning_content", "reasoning"):
            value = delta.get(key)
            if isinstance(value, str) and value:
                chunks.append(value)

    def _merge_stream_tool_calls(
        self,
        tool_call_state: Dict[int, Dict[str, Any]],
        raw_tool_calls: Any,
    ) -> None:
        if not isinstance(raw_tool_calls, list):
            return

        for position, raw_tool_call in enumerate(raw_tool_calls):
            if not isinstance(raw_tool_call, Mapping):
                continue

            index = raw_tool_call.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                index = position

            current = tool_call_state.setdefault(
                index,
                {
                    "id": None,
                    "type": "function",
                    "function": {"name": None, "arguments": ""},
                },
            )

            raw_id = raw_tool_call.get("id")
            if raw_id is not None:
                current["id"] = str(raw_id)

            raw_type = raw_tool_call.get("type")
            if isinstance(raw_type, str) and raw_type.strip():
                current["type"] = raw_type.strip()

            function_obj = raw_tool_call.get("function")
            if isinstance(function_obj, Mapping):
                name = function_obj.get("name")
                if isinstance(name, str) and name.strip():
                    current["function"]["name"] = name.strip()

                arguments = function_obj.get("arguments")
                if isinstance(arguments, str):
                    current["function"]["arguments"] += arguments
                elif arguments is not None:
                    current["function"]["arguments"] += json.dumps(arguments, ensure_ascii=False)

    def _finalize_stream_tool_calls(self, tool_call_state: Dict[int, Dict[str, Any]]) -> List[ToolCall]:
        raw_tool_calls: List[Dict[str, Any]] = []
        for index in sorted(tool_call_state):
            item = tool_call_state[index]
            function_obj = item.get("function") if isinstance(item.get("function"), Mapping) else {}
            name = function_obj.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            raw_tool_calls.append(
                {
                    "id": item.get("id"),
                    "type": item.get("type") or "function",
                    "function": {
                        "name": name.strip(),
                        "arguments": function_obj.get("arguments") or "{}",
                    },
                }
            )
        return parse_openai_like_tool_calls(raw_tool_calls)

    def _should_retry(self, error: LLMClientError) -> bool:
        if error.code == LLMErrorCode.TIMEOUT:
            return True
        if error.code == LLMErrorCode.INVALID_PROVIDER_RESPONSE:
            return True
        if error.code != LLMErrorCode.PROVIDER_REQUEST_FAILED:
            return False

        status_code = error.details.get("status_code")
        if isinstance(status_code, int):
            return status_code in self.retryable_status_codes

        error_text = str(error.details.get("error") or "").lower()
        if not error_text:
            return False
        transient_markers = (
            "timed out",
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "server disconnected",
            "remote protocol error",
        )
        return any(marker in error_text for marker in transient_markers)

    def _should_fallback_to_stream(self, error: LLMClientError) -> bool:
        if error.code != LLMErrorCode.PROVIDER_REQUEST_FAILED:
            return False
        if error.details.get("status_code") != 400:
            return False

        preview = str(error.details.get("response_preview") or "").lower()
        if "streaming_required" in preview:
            return True
        return "only supports streaming" in preview

    def _retry_sleep_seconds(self, error: LLMClientError, attempt: int) -> float:
        retry_after = error.details.get("retry_after")
        if isinstance(retry_after, (int, float)):
            base_sleep = float(retry_after)
        else:
            base_sleep = min(self.retry_cap_seconds, self.retry_base_seconds * (2 ** attempt))
        return base_sleep + random.uniform(0.0, 0.5)


def _extract_content_text(content: Any) -> Optional[str]:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts) if parts else None
    if isinstance(content, Mapping):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return str(content)


def _extract_text_and_reasoning(
    content: Any,
    explicit_reasoning: Any,
) -> tuple[Optional[str], Optional[str]]:
    raw_text = _extract_content_text(content)
    text, think_reasoning = extract_think_tag_content(raw_text)
    if isinstance(text, str):
        stripped = text.strip()
        text = stripped or None
    if isinstance(explicit_reasoning, str) and explicit_reasoning.strip():
        return text, explicit_reasoning.strip()
    return text, think_reasoning


def _build_reasoning_metadata(
    reasoning_content: Optional[str],
    usage: Any,
) -> Dict[str, Any]:
    reasoning_tokens = None
    if isinstance(usage, Mapping):
        raw_reasoning_tokens = usage.get("reasoning_tokens")
        if isinstance(raw_reasoning_tokens, (int, float)):
            reasoning_tokens = int(raw_reasoning_tokens)
        else:
            completion_details = usage.get("completion_tokens_details")
            if isinstance(completion_details, Mapping):
                nested_reasoning_tokens = completion_details.get("reasoning_tokens")
                if isinstance(nested_reasoning_tokens, (int, float)):
                    reasoning_tokens = int(nested_reasoning_tokens)

    summaries: List[str] = []
    if isinstance(reasoning_content, str) and reasoning_content.strip():
        summaries = [reasoning_content.strip()]

    return {
        "summaries": summaries,
        "items": [],
        "reasoning_tokens": reasoning_tokens,
    }


def _messages_to_together(messages: List[Message]) -> List[Dict[str, Any]]:
    converted: List[Dict[str, Any]] = []
    for message in messages:
        if all(isinstance(part, TextPart) for part in message.parts):
            converted.append({"role": message.role, "content": message.text_content()})
            continue

        content_parts: List[Dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                content_parts.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": image_path_to_data_url(part.path)},
                    }
                )
        converted.append({"role": message.role, "content": content_parts})
    return converted


def _bool_with_default(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _int_with_default(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return default


def _float_with_default(value: Any, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _deep_merge_dicts(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[str(key)] = _deep_merge_dicts(current, value)
        else:
            merged[str(key)] = value
    return merged


_TOGETHER_TOOL_CALLING_UNSUPPORTED_MODELS = {
    "qwen/qwen3.6-plus",
}


def _model_supports_tool_calling(model_name: str, metadata: Mapping[str, Any]) -> bool:
    explicit = metadata.get("supports_tool_calling")
    if isinstance(explicit, bool):
        return explicit
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return True
    return normalized not in _TOGETHER_TOOL_CALLING_UNSUPPORTED_MODELS
