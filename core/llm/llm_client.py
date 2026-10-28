"""Shared LLM client manager and session implementation."""

from __future__ import annotations

import copy
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False

from .errors import LLMClientError, LLMErrorCode
from .providers.base import ProviderAdapter, ProviderRequest
from .providers.utils import build_assistant_message
from .types import (
    ImagePart,
    LLMResponse,
    Message,
    ModelSpec,
    ProviderCredentials,
    SessionCreateRequest,
    TextPart,
    TurnRequest,
)

if TYPE_CHECKING:
    from .model_registry import ModelRegistry


_SCOPE_KEYS = ("episode_id", "session_scope", "scope_id")
_DEFAULT_MODELS_YAML_PATH = str(Path(__file__).resolve().parents[2] / "configs" / "models.yaml")
_DEFAULT_PROVIDER_RETRY_ATTEMPTS = 5
_DEFAULT_PROVIDER_RETRY_DELAY_SECONDS = 1.0


class ProviderRegistry:
    """Registry for provider adapters keyed by provider_name."""

    def __init__(self, adapters: Optional[Iterable[ProviderAdapter]] = None) -> None:
        self._adapters: Dict[str, ProviderAdapter] = {}
        for adapter in adapters or []:
            self.register(adapter)

    def register(self, adapter: ProviderAdapter) -> None:
        provider_name = getattr(adapter, "provider_name", "").strip()
        if not provider_name:
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Provider adapter must declare non-empty provider_name.",
            )
        self._adapters[provider_name] = adapter

    def get(self, provider_name: str) -> ProviderAdapter:
        adapter = self._adapters.get(provider_name)
        if adapter is None:
            raise LLMClientError(
                LLMErrorCode.PROVIDER_NOT_REGISTERED,
                "Provider is declared in models.yaml but adapter is not registered.",
                details={"provider": provider_name},
            )
        return adapter

    def has(self, provider_name: str) -> bool:
        return provider_name in self._adapters

    def list_providers(self) -> List[str]:
        return sorted(self._adapters.keys())


class LLMClientManager:
    """Stateless manager responsible for session creation."""

    def __init__(
        self,
        model_registry: "ModelRegistry",
        *,
        provider_registry: Optional[ProviderRegistry] = None,
        auto_load_dotenv: bool = True,
    ) -> None:
        if auto_load_dotenv:
            load_dotenv()
        self._model_registry = model_registry
        self._provider_registry = provider_registry or self.build_default_provider_registry()

    @classmethod
    def from_models_yaml(cls, models_yaml_path: Optional[str] = None) -> "LLMClientManager":
        from .model_registry import ModelRegistry

        path = models_yaml_path or _DEFAULT_MODELS_YAML_PATH
        registry = ModelRegistry.load(path)
        return cls(registry)

    @classmethod
    def from_default_models_yaml(cls) -> "LLMClientManager":
        """Create manager from the default configs/models.yaml path."""

        return cls.from_models_yaml(_DEFAULT_MODELS_YAML_PATH)

    @staticmethod
    def load_model_registry(models_yaml_path: Optional[str] = None) -> "ModelRegistry":
        from .model_registry import ModelRegistry

        return ModelRegistry.load(models_yaml_path or _DEFAULT_MODELS_YAML_PATH)

    def register_provider_adapter(self, adapter: ProviderAdapter) -> None:
        self._provider_registry.register(adapter)

    def create_session(self, request: SessionCreateRequest | Mapping[str, Any]) -> "LLMSession":
        create_request = (
            request
            if isinstance(request, SessionCreateRequest)
            else SessionCreateRequest.from_obj(request)
        )
        model_spec = self._model_registry.get(create_request.model_id)
        adapter = self._provider_registry.get(model_spec.provider)
        credentials = _resolve_credentials(model_spec)
        return LLMSession(
            model_spec=model_spec,
            adapter=adapter,
            credentials=credentials,
            system_messages=create_request.build_system_messages(),
            history_window=create_request.history_window,
            image_history_window=create_request.image_history_window,
            session_metadata=create_request.metadata,
        )

    @staticmethod
    def build_default_provider_registry() -> ProviderRegistry:
        from .providers.android_oracle_adapter import AndroidOracleAdapter
        from .providers.anthropic_adapter import AnthropicAdapter
        from .providers.deepseek_adapter import DeepSeekAdapter
        from .providers.deltachat_oracle_adapter import DeltaChatOracleAdapter
        from .providers.gimp_oracle_adapter import GimpOracleAdapter
        from .providers.google_adapter import GoogleAdapter
        from .providers.intern_adapter import InternAdapter
        from .providers.linux_gui_oracle_adapter import LinuxGuiOracleAdapter
        from .providers.linux_wireshark_oracle_adapter import LinuxWiresharkOracleAdapter
        from .providers.macos_blender_oracle_adapter import MacOSBlenderOracleAdapter
        from .providers.macos_openshop_oracle_adapter import MacOSOpenShopOracleAdapter
        from .providers.macos_script_oracle_adapter import MacOSScriptOracleAdapter
        from .providers.macos_spotube_oracle_adapter import MacOSSpotubeOracleAdapter
        from .providers.mock_adapter import MockAdapter
        from .providers.openai_adapter import OpenAIAdapter
        from .providers.openshop_oracle_adapter import OpenShopOracleAdapter
        from .providers.scripted_adapter import ScriptedAdapter
        from .providers.taobao_adapter import TaobaoAdapter
        from .providers.together_adapter import TogetherAdapter
        from .providers.wireshark_oracle_adapter import WiresharkOracleAdapter
        from .providers.zotero_oracle_adapter import ZoteroOracleAdapter

        try:
            from .providers.windows_oracle_adapter import WindowsOracleAdapter
        except ModuleNotFoundError as exc:
            if exc.name != "mine":
                raise
            WindowsOracleAdapter = None

        adapters = [
            OpenAIAdapter(),
            AnthropicAdapter(),
            GoogleAdapter(),
            InternAdapter(),
            TaobaoAdapter(),
            TogetherAdapter(),
            DeepSeekAdapter(),
            MockAdapter(),
            ScriptedAdapter(),
            AndroidOracleAdapter(),
            LinuxGuiOracleAdapter(),
            LinuxWiresharkOracleAdapter(),
            MacOSBlenderOracleAdapter(),
            MacOSOpenShopOracleAdapter(),
            MacOSScriptOracleAdapter(),
            MacOSSpotubeOracleAdapter(),
            OpenShopOracleAdapter(),
            DeltaChatOracleAdapter(),
            GimpOracleAdapter(),
            ZoteroOracleAdapter(),
            WiresharkOracleAdapter(),
        ]
        if WindowsOracleAdapter is not None:
            adapters.append(WindowsOracleAdapter())

        return ProviderRegistry(adapters=adapters)


class LLMSession:
    """Per-episode LLM session with isolated message history."""

    def __init__(
        self,
        *,
        model_spec: ModelSpec,
        adapter: ProviderAdapter,
        credentials: ProviderCredentials,
        system_messages: Optional[List[Message]] = None,
        history_window: Optional[int] = None,
        image_history_window: Optional[int] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._model_spec = model_spec
        self._adapter = adapter
        self._credentials = credentials
        self._system_messages: List[Message] = copy.deepcopy(system_messages or [])
        self._history_window = history_window
        self._image_history_window = max(0, int(image_history_window or 0))
        self._step_history: List[List[Message]] = []
        self._completed_step_count = 0
        self._session_metadata = copy.deepcopy(session_metadata or {})
        self._session_scope_token = _extract_scope_token(self._session_metadata)

    @property
    def model_id(self) -> str:
        return self._model_spec.model_id

    @property
    def provider(self) -> str:
        return self._model_spec.provider

    @property
    def messages(self) -> List[Message]:
        return self._flatten_completed_messages()

    def messages_as_dicts(self) -> List[Dict[str, Any]]:
        return [message.to_dict() for message in self.messages]

    def run_turn(self, request: TurnRequest | Mapping[str, Any]) -> LLMResponse:
        mode_hint = _extract_response_mode_hint(request)
        try:
            turn_request = request if isinstance(request, TurnRequest) else TurnRequest.from_obj(request)
        except LLMClientError as exc:
            return self._error_response(response_mode=mode_hint, error=exc)

        try:
            self._assert_session_scope(turn_request.metadata)
            current_user_message = copy.deepcopy(turn_request.message.to_message())

            if not self._adapter.supports_response_mode(turn_request.response_mode):
                raise LLMClientError(
                    LLMErrorCode.MODE_NOT_SUPPORTED,
                    "Requested response_mode is not supported by provider adapter.",
                    details={
                        "provider": self.provider,
                        "response_mode": turn_request.response_mode,
                    },
                )

            provider_metadata = copy.deepcopy(self._session_metadata)
            provider_metadata.update(copy.deepcopy(turn_request.metadata))
            provider_metadata.setdefault("completed_step_count", self._completed_step_count)

            provider_request = ProviderRequest(
                model_spec=self._model_spec,
                credentials=self._credentials,
                messages=self._build_turn_messages(current_user_message),
                response_mode=turn_request.response_mode,
                tools=copy.deepcopy(turn_request.tools),
                tool_choice=copy.deepcopy(turn_request.tool_choice),
                parameters=_load_model_parameters(self._model_spec),
                timeout_seconds=turn_request.timeout_seconds,
                metadata=provider_metadata,
            )
            provider_result = self._invoke_with_retries(provider_request)

            assistant_message = provider_result.assistant_message or build_assistant_message(
                provider_result.text,
                provider_result.tool_calls,
            )
            self._append_completed_step([current_user_message, assistant_message])

            return LLMResponse(
                model_id=self.model_id,
                provider=self.provider,
                response_mode=turn_request.response_mode,
                text=provider_result.text,
                reasoning_content=provider_result.reasoning_content,
                tool_calls=provider_result.tool_calls or None,
                finish_reason=provider_result.finish_reason,
                usage=provider_result.usage,
                raw_response=provider_result.raw_response,
                error=None,
                metadata=provider_result.metadata or None,
            )
        except LLMClientError as exc:
            return self._error_response(response_mode=turn_request.response_mode, error=exc)
        except Exception as exc:
            wrapped = LLMClientError(
                LLMErrorCode.PROVIDER_REQUEST_FAILED,
                "Provider request failed with unexpected error.",
                details={"provider": self.provider, "error_type": type(exc).__name__},
                cause=exc,
            )
            return self._error_response(response_mode=turn_request.response_mode, error=wrapped)

    def _assert_session_scope(self, turn_metadata: Mapping[str, Any]) -> None:
        turn_scope = _extract_scope_token(turn_metadata)
        if not self._session_scope_token and turn_scope:
            self._session_scope_token = turn_scope
            return
        if self._session_scope_token and turn_scope and self._session_scope_token != turn_scope:
            raise LLMClientError(
                LLMErrorCode.SESSION_SCOPE_MISMATCH,
                "Session scope mismatch detected; this session may be reused across episodes.",
                details={
                    "session_scope": self._session_scope_token,
                    "request_scope": turn_scope,
                },
            )

    def _build_turn_messages(self, current_user_message: Message) -> List[Message]:
        messages = self._flatten_completed_messages()
        messages.append(copy.deepcopy(current_user_message))
        return messages

    def _flatten_completed_messages(self) -> List[Message]:
        messages = copy.deepcopy(self._system_messages)
        for step_messages in self._step_history:
            messages.extend(copy.deepcopy(step_messages))
        return messages

    def append_message_to_last_step(self, message: Message | Mapping[str, Any]) -> None:
        if not self._step_history:
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Cannot append history message without an existing completed step.",
            )
        normalized = Message.from_obj(message)
        if normalized.role == "system":
            raise LLMClientError(
                LLMErrorCode.INVALID_REQUEST,
                "Cannot append system message into completed step history.",
            )
        self._step_history[-1].append(copy.deepcopy(normalized))

    def seed_completed_steps(self, steps: List[List[Message | Mapping[str, Any]]]) -> None:
        """Seed completed step history when resuming an interrupted episode."""
        for step in steps:
            if not step:
                continue
            normalized = [Message.from_obj(message) for message in step]
            self._append_completed_step(normalized)

    def _append_completed_step(self, step_messages: List[Message]) -> None:
        self._step_history.append([Message.from_obj(message) for message in step_messages])
        self._completed_step_count += 1
        if self._history_window is not None and len(self._step_history) > self._history_window:
            self._step_history = self._step_history[-self._history_window :]
        self._apply_image_history_window()

    def _apply_image_history_window(self) -> None:
        if self._image_history_window <= 0:
            keep_from = len(self._step_history)
        else:
            keep_from = max(0, len(self._step_history) - self._image_history_window)

        for index, step_messages in enumerate(self._step_history):
            preserve_images = index >= keep_from
            normalized_messages: List[Message] = []
            for message in step_messages:
                if preserve_images:
                    normalized_messages.append(Message.from_obj(message))
                else:
                    normalized_messages.append(self._strip_images_from_history_message(message))
            self._step_history[index] = normalized_messages

    @staticmethod
    def _strip_images_from_history_message(message: Message) -> Message:
        copied = Message.from_obj(message)
        filtered_parts = [copy.deepcopy(part) for part in copied.parts if not isinstance(part, ImagePart)]
        if not filtered_parts:
            filtered_parts = [TextPart(text="[Historical image omitted to keep request size bounded.]")]
        return Message(role=copied.role, parts=filtered_parts)

    def _error_response(self, *, response_mode: str, error: LLMClientError) -> LLMResponse:
        metadata = {"error_code": error.code.value}
        if error.details:
            metadata["error_details"] = error.details
        return LLMResponse(
            model_id=self.model_id,
            provider=self.provider,
            response_mode=response_mode,
            text=None,
            tool_calls=None,
            finish_reason=None,
            usage=None,
            raw_response=None,
            error=str(error),
            metadata=metadata,
        )

    def _invoke_with_retries(self, provider_request: ProviderRequest) -> Any:
        attempts = _provider_retry_attempts()
        delay_seconds = _provider_retry_delay_seconds()
        last_error: Optional[LLMClientError] = None

        for attempt in range(1, attempts + 1):
            try:
                return self._adapter.invoke(provider_request)
            except LLMClientError as exc:
                if not _is_retryable_provider_error(exc) or attempt >= attempts:
                    raise
                last_error = exc
                time.sleep(delay_seconds)

        if last_error is not None:
            raise last_error
        raise LLMClientError(
            LLMErrorCode.PROVIDER_REQUEST_FAILED,
            "Provider request failed after retries.",
            details={"provider": self.provider, "attempts": attempts},
        )


def _resolve_credentials(model_spec: ModelSpec) -> ProviderCredentials:
    base_url = model_spec.resolve_base_url(os.environ)
    if not base_url:
        raise LLMClientError(
            LLMErrorCode.ENV_MISSING,
            "Missing required base URL configuration.",
            details={
                "model_id": model_spec.model_id,
                "base_url": model_spec.base_url,
                "base_url_env": model_spec.base_url_env,
            },
        )
    api_key = os.getenv(model_spec.api_key_env, "").strip()
    if not api_key:
        if base_url.startswith(("oracle://", "scripted://", "mock://")):
            api_key = "local-oracle"
        else:
            raise LLMClientError(
                LLMErrorCode.ENV_MISSING,
                "Missing required API key environment variable.",
                details={"env": model_spec.api_key_env, "model_id": model_spec.model_id},
            )
    return ProviderCredentials(api_key=api_key, base_url=base_url)


def _load_model_parameters(model_spec: ModelSpec) -> Dict[str, Any]:
    parameters: Dict[str, Any] = {}

    if model_spec.temperature is not None:
        parameters["temperature"] = model_spec.temperature

    if model_spec.max_output_tokens is not None:
        parameters["max_output_tokens"] = model_spec.max_output_tokens

    if model_spec.top_p is not None:
        parameters["top_p"] = model_spec.top_p

    metadata = model_spec.metadata if isinstance(model_spec.metadata, Mapping) else {}
    reasoning_effort = metadata.get("reasoning_effort")
    if isinstance(reasoning_effort, str) and reasoning_effort.strip():
        parameters["reasoning_effort"] = reasoning_effort.strip()

    # stop is intentionally unsupported for now.
    return parameters


def _extract_scope_token(metadata: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not isinstance(metadata, Mapping):
        return None
    for key in _SCOPE_KEYS:
        value = metadata.get(key)
        if value is None:
            continue
        token = str(value).strip()
        if token:
            return token
    return None


def _extract_response_mode_hint(request: TurnRequest | Mapping[str, Any]) -> str:
    if isinstance(request, TurnRequest):
        return request.response_mode
    if isinstance(request, Mapping):
        raw = request.get("response_mode")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return "json_text"


def _provider_retry_attempts() -> int:
    raw = os.getenv("HELLOWORLD_LLM_PROVIDER_RETRY_ATTEMPTS", "").strip()
    if not raw:
        return _DEFAULT_PROVIDER_RETRY_ATTEMPTS
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_PROVIDER_RETRY_ATTEMPTS
    return max(1, parsed)


def _provider_retry_delay_seconds() -> float:
    raw = os.getenv("HELLOWORLD_LLM_PROVIDER_RETRY_DELAY_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_PROVIDER_RETRY_DELAY_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return _DEFAULT_PROVIDER_RETRY_DELAY_SECONDS
    return max(0.0, parsed)


def _is_retryable_provider_error(error: LLMClientError) -> bool:
    return error.code in {
        LLMErrorCode.PROVIDER_REQUEST_FAILED,
        LLMErrorCode.TIMEOUT,
    }
