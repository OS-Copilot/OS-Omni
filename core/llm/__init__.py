"""LLM client public exports."""

from .errors import LLMClientError, LLMErrorCode
from .types import (
    LLMResponse,
    Message,
    ModelSpec,
    ProviderCredentials,
    SessionCreateRequest,
    TextPart,
    ImagePart,
    ToolDefinition,
    ToolCall,
    TurnRequest,
    UserTurnMessage,
)

try:
    from .llm_client import LLMClientManager, LLMSession, ProviderRegistry
except Exception:  # pragma: no cover - optional until runtime deps are installed
    LLMClientManager = None  # type: ignore[assignment]
    LLMSession = None  # type: ignore[assignment]
    ProviderRegistry = None  # type: ignore[assignment]

try:
    from .model_registry import ModelRegistry
except Exception:  # pragma: no cover - optional until runtime deps are installed
    ModelRegistry = None  # type: ignore[assignment]

__all__ = [
    "ImagePart",
    "LLMClientError",
    "LLMClientManager",
    "LLMErrorCode",
    "LLMResponse",
    "LLMSession",
    "Message",
    "ModelRegistry",
    "ModelSpec",
    "ProviderCredentials",
    "ProviderRegistry",
    "SessionCreateRequest",
    "TextPart",
    "ToolDefinition",
    "ToolCall",
    "TurnRequest",
    "UserTurnMessage",
]
