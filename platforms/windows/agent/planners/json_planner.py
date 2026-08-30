"""JSON-mode action planner backed by shared LLMSession."""

from __future__ import annotations

from typing import List, Optional

from core.llm.llm_client import LLMClientManager

from platforms.windows.core.runtime_types import ActionDecision

from .base_planner import BaseJsonPlanner
from .planner_utils import parse_action_from_text

_WINDOWS_KEYBOARD_ACTIONS = {
    "enter",
    "escape",
    "backspace",
    "delete",
    "tab",
    "space",
    "up",
    "down",
    "left",
    "right",
}

_WINDOWS_ACTION_TYPES = {
    "tap",
    "double_tap",
    "right_click",
    "drag",
    "scroll",
    "type_text",
    "keyboard",
    "hotkey",
    "launch_app",
    "wait",
    "success",
    "fail",
}


def _sanitize_windows_action(action: Optional[dict]) -> Optional[dict]:
    if not isinstance(action, dict):
        return action
    action_type = str(action.get("type") or "").strip().lower()
    if not action_type:
        return action

    if action_type in _WINDOWS_KEYBOARD_ACTIONS:
        corrected = dict(action)
        corrected["type"] = "keyboard"
        corrected["action"] = action_type
        return corrected

    if action_type not in _WINDOWS_ACTION_TYPES:
        action_name = str(action.get("action") or "").strip().lower()
        if action_name in _WINDOWS_KEYBOARD_ACTIONS:
            corrected = dict(action)
            corrected["type"] = "keyboard"
            corrected["action"] = action_name
            return corrected

    return action


class JsonActionPlanner(BaseJsonPlanner):
    """Action planner for json mode."""

    def __init__(
        self,
        llm_client: LLMClientManager,
        model_id: str,
        system_prompt: str,
        history_window: Optional[int] = None,
    ):
        super().__init__(
            llm_client,
            model_id,
            system_prompt,
            history_window=history_window,
            adapter_prefix="json",
        )

    def decide(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> ActionDecision:
        response = self._dispatch_chat(
            prompt,
            images=images,
            files=files,
            timeout_seconds=timeout_seconds,
        )
        provider_error = self._response_error_text(response)
        raw = response.text or provider_error or ""
        action, parse_success = parse_action_from_text(raw)
        if parse_success:
            action = _sanitize_windows_action(action)
        return ActionDecision(
            action=action,
            parse_success=parse_success,
            raw_response=raw,
            mode_requested=self._mode_label(),
            mode_used=self._mode_label(),
            adapter=self._adapter_name(response),
            llm_reasoning=self._reasoning_metadata(response),
            error=None if parse_success else (provider_error or "failed_to_parse_json_action"),
        )
