"""Core types used by the shared LLM client protocol."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from .errors import LLMClientError, LLMErrorCode


VALID_ROLES = {"system", "user", "assistant"}
VALID_RESPONSE_MODES = {"tool_calling", "json_text"}


@dataclass(frozen=True)
class TextPart:
    """Text content part."""

    text: str
    type: str = "text"

    def __post_init__(self) -> None:
        if self.type != "text":
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "TextPart.type must be 'text'.",
            )
        if not isinstance(self.text, str):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "TextPart.text must be a string.",
            )

    @classmethod
    def from_obj(cls, obj: Any) -> "TextPart":
        if isinstance(obj, TextPart):
            return obj
        if not isinstance(obj, Mapping):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "TextPart must be an object.",
            )
        return cls(text=str(obj.get("text", "")), type=str(obj.get("type", "text")))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass(frozen=True)
class ImagePart:
    """Image content part that references an absolute local path."""

    path: str
    type: str = "image"

    def __post_init__(self) -> None:
        if self.type != "image":
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "ImagePart.type must be 'image'.",
            )
        if not isinstance(self.path, str) or not self.path.strip():
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "ImagePart.path must be a non-empty string.",
            )
        if not Path(self.path).is_absolute():
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "ImagePart.path must be an absolute path.",
                details={"path": self.path},
            )

    @classmethod
    def from_obj(cls, obj: Any) -> "ImagePart":
        if isinstance(obj, ImagePart):
            return obj
        if not isinstance(obj, Mapping):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "ImagePart must be an object.",
            )
        return cls(path=str(obj.get("path", "")), type=str(obj.get("type", "image")))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "image", "path": self.path}


MessagePart = Union[TextPart, ImagePart]


def normalize_part(obj: Any) -> MessagePart:
    if isinstance(obj, (TextPart, ImagePart)):
        return obj
    if not isinstance(obj, Mapping):
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "Message part must be an object.",
        )
    part_type = obj.get("type")
    if part_type == "text":
        return TextPart.from_obj(obj)
    if part_type == "image":
        return ImagePart.from_obj(obj)
    raise LLMClientError(
        LLMErrorCode.INVALID_REQUEST,
        "Unsupported message part type.",
        details={"type": part_type},
    )


@dataclass
class Message:
    """Internal unified message representation for adapter conversion."""

    role: str
    parts: List[MessagePart]

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Message.role must be one of system/user/assistant.",
                details={"role": self.role},
            )
        if not isinstance(self.parts, list) or not self.parts:
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Message.parts must be a non-empty list.",
            )
        self.parts = [normalize_part(part) for part in self.parts]

    @classmethod
    def from_obj(cls, obj: Any) -> "Message":
        if isinstance(obj, Message):
            return Message(role=obj.role, parts=copy.deepcopy(obj.parts))
        if not isinstance(obj, Mapping):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Message must be an object.",
            )
        role = str(obj.get("role", ""))
        parts_raw = obj.get("parts")
        if not isinstance(parts_raw, list):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Message.parts must be a list.",
            )
        return cls(role=role, parts=[normalize_part(p) for p in parts_raw])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "parts": [part.to_dict() for part in self.parts],
        }

    def text_content(self) -> str:
        chunks: List[str] = []
        for part in self.parts:
            if isinstance(part, TextPart):
                chunks.append(part.text)
        return "\n".join(chunk for chunk in chunks if chunk)


@dataclass(frozen=True)
class UserTurnMessage:
    """Simplified step message used by platform code."""

    text: str
    image_path: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Turn message text is required.",
            )
        if self.image_path is not None:
            if not isinstance(self.image_path, str) or not self.image_path.strip():
                raise LLMClientError(
                    LLMErrorCode.INVALID_REQUEST,
                    "image_path must be a non-empty string when provided.",
                )
            if not Path(self.image_path).is_absolute():
                raise LLMClientError(
                    LLMErrorCode.INVALID_REQUEST,
                    "image_path must be an absolute path.",
                    details={"image_path": self.image_path},
                )

    @classmethod
    def from_obj(cls, obj: Any) -> "UserTurnMessage":
        if isinstance(obj, UserTurnMessage):
            return obj
        if not isinstance(obj, Mapping):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "TurnRequest.message must be an object.",
            )
        return cls(
            text=str(obj.get("text", "")),
            image_path=obj.get("image_path"),
        )

    def to_message(self) -> Message:
        parts: List[MessagePart] = [TextPart(text=self.text)]
        if self.image_path:
            parts.append(ImagePart(path=self.image_path))
        return Message(role="user", parts=parts)

    def to_dict(self) -> Dict[str, Any]:
        data = {"text": self.text}
        if self.image_path:
            data["image_path"] = self.image_path
        return data


@dataclass(frozen=True)
class ToolDefinition:
    """Provider-agnostic tool definition used by platform code."""

    name: str
    description: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Tool name is required.",
            )
        if self.description is not None and not isinstance(self.description, str):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Tool description must be a string when provided.",
            )
        if not isinstance(self.parameters, dict):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Tool parameters must be an object.",
            )

    @classmethod
    def from_obj(cls, obj: Any) -> "ToolDefinition":
        if isinstance(obj, ToolDefinition):
            return obj
        if not isinstance(obj, Mapping):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Tool definition must be an object.",
            )
        return cls(
            name=str(obj.get("name", "")).strip(),
            description=obj.get("description"),
            parameters=copy.deepcopy(obj.get("parameters") or {}),
        )

    def to_openai_tool(self) -> Dict[str, Any]:
        function_obj: Dict[str, Any] = {"name": self.name}
        if self.description:
            function_obj["description"] = self.description
        if self.parameters:
            function_obj["parameters"] = self.parameters
        return {"type": "function", "function": function_obj}

    def to_gemini_function_declaration(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": self.name}
        if self.description:
            out["description"] = self.description
        if self.parameters:
            out["parameters"] = self.parameters
        return out


@dataclass(frozen=True)
class ModelSpec:
    """Resolved model spec loaded from configs/models.yaml."""

    model_id: str
    provider: str
    model_name: str
    api_key_env: str
    base_url: Optional[str] = None
    base_url_env: Optional[str] = None
    temperature: Optional[float] = None
    max_output_tokens: Optional[float] = None
    top_p: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def resolve_base_url(self, env: Mapping[str, str] = os.environ) -> Optional[str]:
        if self.base_url:
            return self.base_url
        if self.base_url_env:
            value = env.get(self.base_url_env)
            return value.strip() if isinstance(value, str) and value.strip() else None
        return None


@dataclass(frozen=True)
class ProviderCredentials:
    """Runtime provider credentials resolved from environment."""

    api_key: str
    base_url: Optional[str] = None


def normalize_messages(messages: Optional[List[Any]]) -> List[Message]:
    if messages is None:
        return []
    if not isinstance(messages, list):
        raise LLMClientError(
            LLMErrorCode.INVALID_REQUEST,
            "messages must be a list.",
        )
    return [Message.from_obj(m) for m in messages]


@dataclass
class SessionCreateRequest:
    """Request payload used to create a new LLMSession."""

    model_id: str
    system_prompt: Optional[str] = None
    history_window: Optional[int] = None
    image_history_window: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "SessionCreateRequest.model_id is required.",
            )
        self.model_id = self.model_id.strip()
        if self.system_prompt is not None and not isinstance(self.system_prompt, str):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "system_prompt must be a string when provided.",
            )
        if self.history_window is not None:
            if (
                isinstance(self.history_window, bool)
                or not isinstance(self.history_window, int)
                or self.history_window <= 0
            ):
                raise LLMClientError(
                    LLMErrorCode.INVALID_REQUEST,
                    "history_window must be a positive integer when provided.",
                    details={"history_window": self.history_window},
                )
        if self.image_history_window is not None:
            if (
                isinstance(self.image_history_window, bool)
                or not isinstance(self.image_history_window, int)
                or self.image_history_window < 0
            ):
                raise LLMClientError(
                    LLMErrorCode.INVALID_REQUEST,
                    "image_history_window must be a non-negative integer when provided.",
                    details={"image_history_window": self.image_history_window},
                )
        if self.metadata is None:
            self.metadata = {}
        if not isinstance(self.metadata, dict):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "SessionCreateRequest.metadata must be an object.",
            )

    def build_system_messages(self) -> List[Message]:
        prompt = (self.system_prompt or "").strip()
        if not prompt:
            return []
        return [Message(role="system", parts=[TextPart(text=prompt)])]

    @classmethod
    def from_obj(cls, obj: Any) -> "SessionCreateRequest":
        if isinstance(obj, SessionCreateRequest):
            return SessionCreateRequest(
                model_id=obj.model_id,
                system_prompt=obj.system_prompt,
                history_window=obj.history_window,
                image_history_window=obj.image_history_window,
                metadata=copy.deepcopy(obj.metadata),
            )
        if not isinstance(obj, Mapping):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "SessionCreateRequest must be an object.",
            )
        return cls(
            model_id=str(obj.get("model_id", "")),
            system_prompt=obj.get("system_prompt"),
            history_window=obj.get("history_window"),
            image_history_window=obj.get("image_history_window"),
            metadata=copy.deepcopy(obj.get("metadata") or {}),
        )


@dataclass
class TurnRequest:
    """Request payload used for one model turn on an existing LLMSession."""

    message: UserTurnMessage
    response_mode: str
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    timeout_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.message = UserTurnMessage.from_obj(self.message)
        if self.response_mode not in VALID_RESPONSE_MODES:
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "TurnRequest.response_mode must be tool_calling/json_text.",
                details={"response_mode": self.response_mode},
            )

        if self.tools is not None:
            if not isinstance(self.tools, list):
                raise LLMClientError(
                    LLMErrorCode.INVALID_REQUEST,
                    "TurnRequest.tools must be a list when provided.",
                )
            self.tools = [ToolDefinition.from_obj(item) for item in self.tools]

        if self.response_mode == "tool_calling" and not self.tools:
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "tool_calling mode requires non-empty tools.",
            )

        if self.tool_choice is not None and not isinstance(self.tool_choice, (str, dict)):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "TurnRequest.tool_choice must be string or object.",
            )

        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "TurnRequest.timeout_seconds must be > 0 when provided.",
            )

        if self.metadata is None:
            self.metadata = {}
        if not isinstance(self.metadata, dict):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "TurnRequest.metadata must be an object.",
            )

    @classmethod
    def from_obj(cls, obj: Any) -> "TurnRequest":
        if isinstance(obj, TurnRequest):
            return TurnRequest(
                message=copy.deepcopy(obj.message),
                response_mode=obj.response_mode,
                tools=copy.deepcopy(obj.tools),
                tool_choice=copy.deepcopy(obj.tool_choice),
                timeout_seconds=obj.timeout_seconds,
                metadata=copy.deepcopy(obj.metadata),
            )
        if not isinstance(obj, Mapping):
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "TurnRequest must be an object.",
            )

        return cls(
            message=UserTurnMessage.from_obj(obj.get("message")),
            response_mode=str(obj.get("response_mode", "")),
            tools=copy.deepcopy(obj.get("tools")),
            tool_choice=copy.deepcopy(obj.get("tool_choice")),
            timeout_seconds=obj.get("timeout_seconds"),
            metadata=copy.deepcopy(obj.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ToolCall:
    """Unified tool call item."""

    name: str
    arguments_json: str
    call_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise LLMClientError(
                LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                "ToolCall.name must be a non-empty string.",
            )
        if not isinstance(self.arguments_json, str):
            raise LLMClientError(
                LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                "ToolCall.arguments_json must be a string.",
            )

    def to_dict(self) -> Dict[str, Any]:
        data = {"name": self.name, "arguments_json": self.arguments_json}
        if self.call_id:
            data["call_id"] = self.call_id
        return data


@dataclass
class LLMResponse:
    """Unified shared LLM response returned to platform code."""

    model_id: str
    provider: str
    response_mode: str
    text: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    raw_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider": self.provider,
            "response_mode": self.response_mode,
            "text": self.text,
            "reasoning_content": self.reasoning_content,
            "tool_calls": [item.to_dict() for item in (self.tool_calls or [])] or None,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "raw_response": self.raw_response,
            "error": self.error,
            "metadata": self.metadata,
        }
