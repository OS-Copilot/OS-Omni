"""Shared provider utility helpers."""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from ..errors import LLMClientError, LLMErrorCode
from ..types import ImagePart, Message, TextPart, ToolCall, ToolDefinition


def image_path_to_data_url(path: str, *, jpeg_quality: Optional[int] = None) -> str:
    """Convert an image file path to a data URL."""

    image_path = Path(path)
    if not image_path.is_file():
        raise LLMClientError(
            LLMErrorCode.IMAGE_IO_ERROR,
            "Image file does not exist.",
            details={"path": path},
        )

    if jpeg_quality is not None:
        from PIL import Image

        if (
            isinstance(jpeg_quality, bool)
            or not isinstance(jpeg_quality, int)
            or not 1 <= jpeg_quality <= 95
        ):
            raise ValueError("jpeg_quality must be an integer between 1 and 95")
        buffer = io.BytesIO()
        with Image.open(image_path) as image:
            image.convert('RGB').save(buffer, format='JPEG', quality=jpeg_quality)
        return 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')

    mime_type, _ = mimetypes.guess_type(str(image_path))
    mime_type = mime_type or "image/png"
    data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{data}"


def image_path_to_inline_data(path: str) -> Dict[str, str]:
    """Convert an image file path to Gemini inlineData shape."""

    image_path = Path(path)
    if not image_path.is_file():
        raise LLMClientError(
            LLMErrorCode.IMAGE_IO_ERROR,
            "Image file does not exist.",
            details={"path": path},
        )
    mime_type, _ = mimetypes.guess_type(str(image_path))
    mime_type = mime_type or "image/png"
    data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return {"mimeType": mime_type, "data": data}


def messages_to_openai(messages: List[Message], *, jpeg_quality: Optional[int] = None) -> List[Dict[str, Any]]:
    """Convert unified messages to OpenAI Chat Completions format."""

    converted: List[Dict[str, Any]] = []
    for message in messages:
        content_parts: List[Dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                content_parts.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": image_path_to_data_url(part.path, jpeg_quality=jpeg_quality)},
                    }
                )
        converted.append({"role": message.role, "content": content_parts})
    return converted


def fold_system_into_first_user(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Move OpenAI-format system messages to the front of the first user message.

    For gateways that silently drop the system role. The system text is kept
    verbatim and stays ahead of everything else the model sees.
    """

    system_parts = [part for message in messages if message.get("role") == "system" for part in message["content"]]
    if not system_parts:
        return messages
    folded = [message for message in messages if message.get("role") != "system"]
    for index, message in enumerate(folded):
        if message.get("role") == "user":
            folded[index] = {**message, "content": system_parts + list(message["content"])}
            return folded
    return [{"role": "user", "content": system_parts}] + folded


def messages_to_anthropic(messages: List[Message]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Convert unified messages to Anthropic Messages API (system text, messages)."""

    system_texts: List[str] = []
    converted: List[Dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            system_texts.extend(part.text for part in message.parts if isinstance(part, TextPart) and part.text)
            continue
        content_parts: List[Dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                # The Messages API rejects empty text blocks.
                if part.text:
                    content_parts.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                inline = image_path_to_inline_data(part.path)
                content_parts.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": inline["mimeType"], "data": inline["data"]},
                    }
                )
        if content_parts:
            converted.append({"role": message.role, "content": content_parts})
    return ("\n\n".join(system_texts) or None), converted


def messages_to_responses(messages: List[Message]) -> List[Dict[str, Any]]:
    """Convert unified messages to OpenAI Responses API input format."""

    converted: List[Dict[str, Any]] = []
    for message in messages:
        content_parts: List[Dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                content_type = "output_text" if message.role == "assistant" else "input_text"
                content_parts.append({"type": content_type, "text": part.text})
            elif isinstance(part, ImagePart):
                content_parts.append(
                    {
                        "type": "input_image",
                        "image_url": image_path_to_data_url(part.path),
                    }
                )
        converted.append({"role": message.role, "content": content_parts})
    return converted


def messages_to_gemini(messages: List[Message]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Convert unified messages to Gemini generateContent format."""

    system_fragments: List[str] = []
    contents: List[Dict[str, Any]] = []

    for message in messages:
        if message.role == "system":
            text = message.text_content().strip()
            if text:
                system_fragments.append(text)
            continue

        role = "user" if message.role == "user" else "model"
        parts: List[Dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                parts.append({"text": part.text})
            elif isinstance(part, ImagePart):
                parts.append({"inlineData": image_path_to_inline_data(part.path)})

        if not parts:
            parts.append({"text": ""})
        contents.append({"role": role, "parts": parts})

    system_instruction = None
    if system_fragments:
        system_instruction = {"parts": [{"text": "\n\n".join(system_fragments)}]}

    return system_instruction, contents


def tool_defs_to_openai(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
    """Convert canonical ToolDefinition list to OpenAI tools format."""

    return [tool.to_openai_tool() for tool in tools]


def _normalize_responses_strict_schema(node: Any) -> Any:
    """Recursively coerce JSON Schema into the strict subset accepted by Responses tools."""

    if isinstance(node, list):
        return [_normalize_responses_strict_schema(item) for item in node]

    if not isinstance(node, Mapping):
        return node

    normalized: Dict[str, Any] = {
        str(key): _normalize_responses_strict_schema(value)
        for key, value in node.items()
    }

    if normalized.get("type") == "object" or "properties" in normalized:
        properties = normalized.get("properties")
        if not isinstance(properties, dict):
            normalized["properties"] = {}
            properties = normalized["properties"]
        if normalized.get("additionalProperties") is not False:
            normalized["additionalProperties"] = False
        required_keys = []
        original_required = normalized.get("required")
        original_required_set = set(original_required) if isinstance(original_required, list) else set()
        for prop_name, prop_schema in properties.items():
            if prop_name not in original_required_set:
                properties[prop_name] = _wrap_schema_with_null_option(prop_schema)
            required_keys.append(prop_name)
        normalized["required"] = required_keys

    return normalized


def _wrap_schema_with_null_option(schema: Any) -> Any:
    """Allow a formerly-optional field to remain omittable under strict required-all schema rules."""

    if not isinstance(schema, Mapping):
        return {"anyOf": [schema, {"type": "null"}]}

    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and any(
        isinstance(option, Mapping) and option.get("type") == "null"
        for option in any_of
    ):
        return dict(schema)

    if schema.get("type") == "null":
        return dict(schema)

    wrapped: Dict[str, Any] = {"anyOf": [dict(schema), {"type": "null"}]}
    for meta_key in ("description", "default", "title", "examples"):
        if meta_key in schema:
            wrapped[meta_key] = schema[meta_key]
    return wrapped


def tool_defs_to_responses(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
    """Convert canonical ToolDefinition list to OpenAI Responses tools format."""

    converted: List[Dict[str, Any]] = []
    for tool in tools:
        item: Dict[str, Any] = {
            "type": "function",
            "name": tool.name,
            "strict": True,
        }
        if tool.description:
            item["description"] = tool.description
        if tool.parameters:
            item["parameters"] = _normalize_responses_strict_schema(tool.parameters)
        converted.append(item)
    return converted


def tool_defs_to_gemini(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
    """Convert canonical ToolDefinition list to Gemini declarations."""

    return [tool.to_gemini_function_declaration() for tool in tools]


def gemini_tool_choice_config(tool_choice: Optional[Union[str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Convert tool_choice to Gemini functionCallingConfig."""

    if tool_choice is None:
        return None

    if isinstance(tool_choice, str):
        normalized = tool_choice.strip().lower()
        if normalized == "auto":
            return {"mode": "AUTO"}
        if normalized == "none":
            return {"mode": "NONE"}
        if normalized == "required":
            return {"mode": "ANY"}
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "Unsupported string tool_choice.",
            details={"tool_choice": tool_choice},
        )

    if not isinstance(tool_choice, dict):
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "tool_choice must be string or object.",
        )

    # Canonical forced function call.
    if isinstance(tool_choice.get("name"), str) and tool_choice["name"].strip():
        return {"mode": "ANY", "allowedFunctionNames": [tool_choice["name"].strip()]}

    # Allow explicit Gemini-style config passthrough.
    mode = tool_choice.get("mode")
    if isinstance(mode, str) and mode.strip():
        out = {"mode": mode.strip().upper()}
        allowed = tool_choice.get("allowedFunctionNames")
        if isinstance(allowed, list):
            out["allowedFunctionNames"] = [str(item) for item in allowed]
        return out

    raise LLMClientError(
        LLMErrorCode.INVALID_REQUEST,
        "Unsupported object tool_choice format.",
    )


def openai_tool_choice_value(tool_choice: Optional[Union[str, Dict[str, Any]]]) -> Optional[Union[str, Dict[str, Any]]]:
    """Convert canonical tool_choice to OpenAI-compatible shape."""

    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        normalized = tool_choice.strip().lower()
        if normalized in {"auto", "none", "required"}:
            return normalized
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "Unsupported string tool_choice.",
            details={"tool_choice": tool_choice},
        )

    if not isinstance(tool_choice, dict):
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "tool_choice must be string or object.",
        )

    # Canonical format: {"name": "tap"}
    name = tool_choice.get("name")
    if isinstance(name, str) and name.strip():
        return {"type": "function", "function": {"name": name.strip()}}

    raise LLMClientError(
        LLMErrorCode.INVALID_REQUEST,
        "Unsupported object tool_choice format.",
    )


def responses_tool_choice_value(tool_choice: Optional[Union[str, Dict[str, Any]]]) -> Optional[Union[str, Dict[str, Any]]]:
    """Convert canonical tool_choice to OpenAI Responses API shape."""

    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        normalized = tool_choice.strip().lower()
        if normalized in {"auto", "none", "required"}:
            return normalized
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "Unsupported string tool_choice.",
            details={"tool_choice": tool_choice},
        )

    if not isinstance(tool_choice, dict):
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "tool_choice must be string or object.",
        )

    name = tool_choice.get("name")
    if isinstance(name, str) and name.strip():
        return {"type": "function", "name": name.strip()}

    raise LLMClientError(
        LLMErrorCode.INVALID_REQUEST,
        "Unsupported object tool_choice format.",
    )


def parse_openai_like_tool_calls(raw_tool_calls: Any) -> List[ToolCall]:
    """Parse OpenAI-compatible tool calls into unified ToolCall."""

    if raw_tool_calls is None:
        return []
    if not isinstance(raw_tool_calls, list):
        raise LLMClientError(
            LLMErrorCode.INVALID_PROVIDER_RESPONSE,
            "tool_calls should be an array when provided.",
        )

    tool_calls: List[ToolCall] = []
    for raw in raw_tool_calls:
        if not isinstance(raw, Mapping):
            continue

        function_obj = raw.get("function") if isinstance(raw.get("function"), Mapping) else {}
        name = function_obj.get("name") or raw.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        arguments = function_obj.get("arguments")
        if isinstance(arguments, str):
            arguments_json = arguments
        elif arguments is None:
            arguments_json = "{}"
        else:
            arguments_json = json.dumps(arguments, ensure_ascii=False)

        call_id = raw.get("id") or raw.get("call_id")
        tool_calls.append(
            ToolCall(
                name=name.strip(),
                arguments_json=arguments_json,
                call_id=str(call_id) if call_id is not None else None,
            )
        )

    return tool_calls


def parse_responses_tool_calls(output_items: Any) -> List[ToolCall]:
    """Parse OpenAI Responses API function_call output items into unified ToolCall."""

    if output_items is None:
        return []
    if not isinstance(output_items, list):
        raise LLMClientError(
            LLMErrorCode.INVALID_PROVIDER_RESPONSE,
            "Responses output should be an array when provided.",
        )

    tool_calls: List[ToolCall] = []
    for item in output_items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type") or "").strip() != "function_call":
            continue

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        arguments = item.get("arguments")
        if isinstance(arguments, str):
            arguments_json = arguments
        elif arguments is None:
            arguments_json = "{}"
        else:
            arguments_json = json.dumps(arguments, ensure_ascii=False)

        call_id = item.get("call_id") or item.get("id")
        tool_calls.append(
            ToolCall(
                name=name.strip(),
                arguments_json=arguments_json,
                call_id=str(call_id) if call_id is not None else None,
            )
        )
    return tool_calls


def aggregate_chat_completion_sse(body: str) -> Optional[Dict[str, Any]]:
    """Rebuild a chat.completion object from an SSE chat.completion.chunk stream.

    Some OpenAI-compatible gateways answer with a stream even when the request
    did not ask for one. Returns None when the body is not such a stream.
    """

    chunks: List[Dict[str, Any]] = []
    for line in str(body or "").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if not data or data == "[DONE]":
            continue
        try:
            chunk = json.loads(data)
        except ValueError:
            return None
        if isinstance(chunk, dict):
            chunks.append(chunk)
    if not chunks or not any(isinstance(chunk.get("choices"), list) for chunk in chunks):
        return None

    content: List[str] = []
    reasoning: List[str] = []
    tool_calls: Dict[int, Dict[str, Any]] = {}
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    for chunk in chunks:
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if not isinstance(choice, Mapping):
                continue
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            delta = choice.get("delta") if isinstance(choice.get("delta"), Mapping) else {}
            if isinstance(delta.get("content"), str):
                content.append(delta["content"])
            if isinstance(delta.get("reasoning_content"), str):
                reasoning.append(delta["reasoning_content"])
            for raw_call in delta.get("tool_calls") or []:
                if not isinstance(raw_call, Mapping):
                    continue
                call = tool_calls.setdefault(
                    int(raw_call.get("index") or 0),
                    {"type": "function", "function": {"name": "", "arguments": ""}},
                )
                if raw_call.get("id"):
                    call["id"] = raw_call["id"]
                function_obj = raw_call.get("function") if isinstance(raw_call.get("function"), Mapping) else {}
                call["function"]["name"] += function_obj.get("name") or ""
                call["function"]["arguments"] += function_obj.get("arguments") or ""

    message: Dict[str, Any] = {"role": "assistant", "content": "".join(content)}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if tool_calls:
        message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
    first = chunks[0]
    return {
        "id": first.get("id"),
        "object": "chat.completion",
        "created": first.get("created"),
        "model": first.get("model"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }


def extract_openai_text_content(content: Any) -> Optional[str]:
    """Extract assistant text from OpenAI-like message content payload."""

    if content is None:
        return None

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks) if chunks else None

    if isinstance(content, Mapping):
        text = content.get("text")
        if isinstance(text, str):
            return text

    return str(content)


_THINK_OPEN_PATTERN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE_PATTERN = re.compile(r"</think>", re.IGNORECASE)


def extract_think_tag_content(text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Split <think>...</think> blocks from assistant text.

    Returns:
        (clean_text_without_think, think_content)
    """

    if not isinstance(text, str) or not text:
        return text, None

    answer_chunks: List[str] = []
    reasoning_chunks: List[str] = []
    remaining = text
    mode = "answer"

    while remaining:
        if mode == "answer":
            match = _THINK_OPEN_PATTERN.search(remaining)
            if match is None:
                answer_chunks.append(remaining)
                break
            answer_chunks.append(remaining[: match.start()])
            remaining = remaining[match.end() :]
            mode = "reasoning"
            continue

        match = _THINK_CLOSE_PATTERN.search(remaining)
        if match is None:
            reasoning_chunks.append(remaining)
            remaining = ""
            break
        reasoning_chunks.append(remaining[: match.start()])
        remaining = remaining[match.end() :]
        mode = "answer"

    reasoning_parts = [chunk.strip() for chunk in reasoning_chunks if chunk and chunk.strip()]
    if not reasoning_parts:
        return text, None

    cleaned = "".join(answer_chunks).strip()
    return (cleaned or None), "\n\n".join(reasoning_parts)


def extract_responses_text_content(output_items: Any) -> Optional[str]:
    """Extract assistant text from OpenAI Responses API output items."""

    if output_items is None:
        return None
    if not isinstance(output_items, list):
        raise LLMClientError(
            LLMErrorCode.INVALID_PROVIDER_RESPONSE,
            "Responses output should be an array when provided.",
        )

    chunks: List[str] = []
    for item in output_items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type") or "").strip() != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            if str(part.get("type") or "").strip() != "output_text":
                continue
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks) if chunks else None


def extract_responses_reasoning(output_items: Any, usage: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Extract reasoning items and summary text from Responses API output."""

    reasoning_items: List[Dict[str, Any]] = []
    summary_texts: List[str] = []

    if isinstance(output_items, list):
        for item in output_items:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("type") or "").strip() != "reasoning":
                continue
            normalized_item = dict(item)
            reasoning_items.append(normalized_item)
            summary = item.get("summary")
            if not isinstance(summary, list):
                continue
            for entry in summary:
                if not isinstance(entry, Mapping):
                    continue
                text = entry.get("text")
                if isinstance(text, str) and text.strip():
                    summary_texts.append(text)

    reasoning_tokens = None
    if isinstance(usage, Mapping):
        output_details = usage.get("output_tokens_details")
        if isinstance(output_details, Mapping):
            token_value = output_details.get("reasoning_tokens")
            if isinstance(token_value, (int, float)):
                reasoning_tokens = int(token_value)

    return {
        "items": reasoning_items,
        "summaries": summary_texts,
        "reasoning_tokens": reasoning_tokens,
    }


def build_assistant_message(text: Optional[str], tool_calls: List[ToolCall]) -> Message:
    """Build a protocol-compliant assistant message for session history."""

    normalized_text = text or ""
    if tool_calls:
        serialized = [tool.to_dict() for tool in tool_calls]
        if normalized_text.strip():
            normalized_text = (
                f"{normalized_text.rstrip()}\n\n[tool_calls]\n"
                f"{json.dumps(serialized, ensure_ascii=False)}"
            )
        else:
            normalized_text = json.dumps({"tool_calls": serialized}, ensure_ascii=False)

    return Message(role="assistant", parts=[TextPart(text=normalized_text)])


def resolve_chat_completions_url(base_url: Optional[str]) -> str:
    """Resolve OpenAI-compatible chat completion endpoint URL."""

    if not isinstance(base_url, str) or not base_url.strip():
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "base_url is required for OpenAI-compatible providers.",
        )

    source = base_url.strip()
    clean = source.rstrip("/")

    if clean.endswith("/chat/completions") or clean.endswith("/completions"):
        return clean
    return f"{clean}/chat/completions"


def resolve_responses_url(base_url: Optional[str]) -> str:
    """Resolve OpenAI Responses API endpoint URL."""

    if not isinstance(base_url, str) or not base_url.strip():
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "base_url is required for OpenAI-compatible providers.",
        )

    source = base_url.strip()
    clean = source.rstrip("/")

    if clean.endswith("/responses"):
        return clean
    if clean.endswith("/chat/completions"):
        clean = clean[: -len("/chat/completions")]
    return f"{clean}/responses"
