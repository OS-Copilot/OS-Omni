"""JSON-mode action planner backed by shared LLMSession."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.llm.llm_client import LLMClientManager

from platforms.macos.host.core.runtime_types import ActionDecision

from .base_planner import BaseJsonPlanner
from .planner_utils import parse_action_from_text


class JsonActionPlanner(BaseJsonPlanner):
    """Action planner for json mode."""

    def __init__(
        self,
        llm_client: LLMClientManager,
        model_id: str,
        system_prompt: str,
        history_window: Optional[int] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            llm_client,
            model_id,
            system_prompt,
            history_window=history_window,
            session_metadata=session_metadata,
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
