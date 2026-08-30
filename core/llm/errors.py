"""Unified errors for the shared LLM client."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class LLMErrorCode(str, Enum):
    """Stable error code enum used across all providers."""

    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    PROVIDER_NOT_REGISTERED = "PROVIDER_NOT_REGISTERED"
    ENV_MISSING = "ENV_MISSING"
    TIMEOUT = "TIMEOUT"
    INVALID_PROVIDER_RESPONSE = "INVALID_PROVIDER_RESPONSE"
    MODE_NOT_SUPPORTED = "MODE_NOT_SUPPORTED"
    SESSION_SCOPE_MISMATCH = "SESSION_SCOPE_MISMATCH"
    INVALID_REQUEST = "INVALID_REQUEST"
    PROVIDER_REQUEST_FAILED = "PROVIDER_REQUEST_FAILED"
    MODEL_REGISTRY_INVALID = "MODEL_REGISTRY_INVALID"
    IMAGE_IO_ERROR = "IMAGE_IO_ERROR"


class LLMClientError(Exception):
    """Structured error used by the shared LLM layer."""

    def __init__(
        self,
        code: LLMErrorCode,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.cause = cause

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"

