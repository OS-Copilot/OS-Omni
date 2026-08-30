"""Base planner classes backed by shared LLMSession."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.llm.llm_client import LLMClientManager
from core.llm.types import (
    LLMResponse,
    Message,
    SessionCreateRequest,
    TextPart,
    ToolDefinition,
    TurnRequest,
)

from .planner_utils import parse_tool_arguments


_DEFAULT_IMAGE_HISTORY_WINDOW = 3
_IMAGE_HISTORY_ENV = "HELLOWORLD_IMAGE_HISTORY_WINDOW"


def _resolve_image_history_window(image_history_window: Optional[int]) -> int:
    if image_history_window is not None:
        return max(0, int(image_history_window))

    raw_override = os.getenv(_IMAGE_HISTORY_ENV, "").strip()
    if raw_override:
        try:
            return max(0, int(raw_override))
        except ValueError:
            pass

    return _DEFAULT_IMAGE_HISTORY_WINDOW


def _append_file_content(prompt: str, files: Optional[List[str]]) -> str:
    if not files:
        return prompt

    merged = prompt
    for file_path in files:
        try:
            content = Path(file_path).read_text(encoding="utf-8")
            merged += f"\n\n--- Content of {Path(file_path).name} ---\n{content}\n"
        except Exception:
            continue
    return merged


def _pick_first_image(images: Optional[List[str]]) -> Optional[str]:
    if not images:
        return None
    for candidate in images:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = path.resolve()
        if path.exists():
            return str(path)
    return None


_BLANK_TOOL_CALL_RETRY_SUFFIX = (
    "\n\nImportant: the previous response for this exact same GUI state returned no tool call. "
    "Return exactly one valid tool call for the next action now."
)
_PROVIDER_RETRY_SUFFIX = "\n\nRetry the same GUI step and return exactly one valid tool call now."
_RETRYABLE_PROVIDER_ERROR_SNIPPETS = (
    "Instructions are required",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "connection reset",
)
_RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


def _format_llm_error(response: LLMResponse) -> Optional[str]:
    raw_error = str(response.error or "").strip()
    if not raw_error:
        return None

    metadata = response.metadata if isinstance(response.metadata, dict) else {}
    detail_parts: List[str] = []

    error_code = str(metadata.get("error_code", "")).strip()
    if error_code:
        detail_parts.append(f"code={error_code}")

    error_details = metadata.get("error_details")
    if isinstance(error_details, dict):
        status_code = error_details.get("status_code")
        if status_code not in (None, ""):
            detail_parts.append(f"status={status_code}")

        provider = str(error_details.get("provider", "")).strip()
        if provider:
            detail_parts.append(f"provider={provider}")

        env_name = str(error_details.get("env", "")).strip()
        if env_name:
            detail_parts.append(f"env={env_name}")

        preview = str(error_details.get("response_preview", "")).strip().replace("\n", " ")
        if preview:
            preview = preview[:180] + ("..." if len(preview) > 180 else "")
            detail_parts.append(f"preview={preview}")

    if detail_parts:
        return f"{raw_error} ({', '.join(detail_parts)})"
    return raw_error


def _extract_reasoning_metadata(response: LLMResponse) -> Optional[Dict[str, Any]]:
    metadata = response.metadata if isinstance(response.metadata, dict) else {}
    reasoning = metadata.get("reasoning")
    if not isinstance(reasoning, dict):
        reasoning_text = str(response.reasoning_content or "").strip()
        if not reasoning_text:
            return None
        return {
            "api_mode": metadata.get("api_mode"),
            "response_id": metadata.get("response_id"),
            "summaries": [reasoning_text],
            "items": [],
            "reasoning_tokens": None,
        }

    summaries = reasoning.get("summaries")
    if not isinstance(summaries, list):
        summaries = []
    items = reasoning.get("items")
    if not isinstance(items, list):
        items = []

    return {
        "api_mode": metadata.get("api_mode"),
        "response_id": metadata.get("response_id"),
        "summaries": [str(item) for item in summaries if isinstance(item, str)],
        "items": [item for item in items if isinstance(item, dict)],
        "reasoning_tokens": reasoning.get("reasoning_tokens"),
    }


def _tool_turn_retry_reason(response: LLMResponse) -> Optional[str]:
    tool_calls = response.tool_calls or []
    provider_error = _format_llm_error(response)
    assistant_text = str(response.text or "").strip()

    if not tool_calls and not provider_error and not assistant_text:
        return "blank_tool_call"

    if not provider_error:
        return None

    metadata = response.metadata if isinstance(response.metadata, dict) else {}
    error_details = metadata.get("error_details")
    status_code = None
    if isinstance(error_details, dict):
        status_code = error_details.get("status_code")

    if isinstance(status_code, int) and status_code in _RETRYABLE_STATUS_CODES:
        return "provider_error"

    lowered = provider_error.lower()
    if any(snippet.lower() in lowered for snippet in _RETRYABLE_PROVIDER_ERROR_SNIPPETS):
        return "provider_error"

    return None


class BaseJsonPlanner:
    """Shared init + turn dispatch for json_text planners."""

    def __init__(
        self,
        llm_client: LLMClientManager,
        model_id: str,
        system_prompt: str,
        history_window: Optional[int] = None,
        image_history_window: Optional[int] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
        *,
        adapter_prefix: str,
    ):
        self._adapter_prefix = adapter_prefix
        self._session = llm_client.create_session(
            SessionCreateRequest(
                model_id=model_id,
                system_prompt=system_prompt,
                history_window=history_window,
                image_history_window=_resolve_image_history_window(image_history_window),
                metadata=dict(session_metadata or {}),
            )
        )

    def _dispatch_chat(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> LLMResponse:
        return self._session.run_turn(
            TurnRequest(
                message={
                    "text": _append_file_content(prompt, files),
                    "image_path": _pick_first_image(images),
                },
                response_mode="json_text",
                timeout_seconds=timeout_seconds,
            )
        )

    def seed_history_steps(self, steps: List[List[Dict[str, Any]]]) -> None:
        self._session.seed_completed_steps(steps)

    @staticmethod
    def _response_error_text(response: LLMResponse) -> Optional[str]:
        return _format_llm_error(response)

    @staticmethod
    def _mode_label() -> str:
        return "json"

    def _adapter_name(self, response: LLMResponse) -> str:
        provider = response.provider or "unknown"
        return f"{provider}_{self._adapter_prefix}"

    @staticmethod
    def _reasoning_metadata(response: LLMResponse) -> Optional[Dict[str, Any]]:
        return _extract_reasoning_metadata(response)


class BaseToolPlanner:
    """Shared init + turn dispatch for tool-calling planners."""

    def __init__(
        self,
        llm_client: LLMClientManager,
        model_id: str,
        system_prompt: str,
        tools: List[ToolDefinition],
        history_window: Optional[int] = None,
        image_history_window: Optional[int] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
        *,
        adapter_prefix: str,
    ):
        self.tools = tools
        self._adapter_prefix = adapter_prefix
        self._blank_tool_call_retry_limit = 2
        self._session = llm_client.create_session(
            SessionCreateRequest(
                model_id=model_id,
                system_prompt=system_prompt,
                history_window=history_window,
                image_history_window=_resolve_image_history_window(image_history_window),
                metadata=dict(session_metadata or {}),
            )
        )

    def _run_tool_turn(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> LLMResponse:
        return self._session.run_turn(
            TurnRequest(
                message={
                    "text": _append_file_content(prompt, files),
                    "image_path": _pick_first_image(images),
                },
                response_mode="tool_calling",
                tools=self.tools,
                tool_choice="required",
                timeout_seconds=timeout_seconds,
            )
        )

    def _dispatch_tool_call(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        response = self._run_tool_turn(
            prompt,
            images=images,
            files=files,
            timeout_seconds=timeout_seconds,
        )

        retry_prompt = prompt
        for _ in range(self._blank_tool_call_retry_limit):
            retry_reason = _tool_turn_retry_reason(response)
            if retry_reason is None:
                break

            if retry_reason == "blank_tool_call":
                retry_prompt = prompt + _BLANK_TOOL_CALL_RETRY_SUFFIX
            else:
                retry_prompt = prompt + _PROVIDER_RETRY_SUFFIX
            response = self._run_tool_turn(
                retry_prompt,
                images=images,
                files=files,
                timeout_seconds=timeout_seconds,
            )

        tool_calls = response.tool_calls or []
        provider_error = _format_llm_error(response)
        assistant_text = response.text or ""
        if provider_error:
            assistant_text = provider_error

        if not tool_calls:
            return {
                "response": response,
                "has_tool_call": False,
                "assistant_text": assistant_text,
                "tool_name": "",
                "parsed_args": {},
                "args_valid": False,
                "provider_error": provider_error,
                "llm_reasoning": _extract_reasoning_metadata(response),
            }

        first = tool_calls[0]
        parsed_args, args_valid = parse_tool_arguments(first.arguments_json)
        return {
            "response": response,
            "has_tool_call": True,
            "assistant_text": assistant_text,
            "tool_name": first.name,
            "parsed_args": parsed_args,
            "args_valid": args_valid,
            "provider_error": provider_error,
            "llm_reasoning": _extract_reasoning_metadata(response),
        }

    def record_tool_execution(
        self,
        action: Dict[str, Any],
        action_result: Dict[str, Any],
    ) -> None:
        payload = {
            "tool_name": action.get("type"),
            "action": action,
            "result": action_result,
        }
        self._session.append_message_to_last_step(
            Message(
                role="user",
                parts=[
                    TextPart(
                        text=(
                            "Tool execution output from the previous step:\n"
                            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
                        )
                    )
                ],
            )
        )

    @staticmethod
    def _mode_label() -> str:
        return "tool_calling"

    def _adapter_name(self, response: LLMResponse) -> str:
        provider = response.provider or "unknown"
        return f"{provider}_{self._adapter_prefix}"

    @staticmethod
    def _reasoning_metadata(response: LLMResponse) -> Optional[Dict[str, Any]]:
        return _extract_reasoning_metadata(response)
