"""Tool-calling action planner backed by shared LLMSession."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.llm.llm_client import LLMClientManager
from core.llm.types import ToolDefinition

from platforms.windows.core.runtime_types import ActionDecision

from .base_planner import BaseToolPlanner
from .planner_utils import build_openai_tools_from_action_schema


def _tool_definition_from_openai_tool(tool: Dict[str, Any]) -> ToolDefinition:
    function_obj = tool.get("function") or {}
    return ToolDefinition(
        name=str(function_obj.get("name", "")).strip(),
        description=function_obj.get("description"),
        parameters=function_obj.get("parameters") or {},
    )


def _tool_defs_from_action_schema(action_schema: Dict[str, Any]) -> List[ToolDefinition]:
    openai_tools = build_openai_tools_from_action_schema(action_schema)
    return [_tool_definition_from_openai_tool(tool) for tool in openai_tools]


class ToolActionPlanner(BaseToolPlanner):
    """Action planner for native tool-calling mode."""

    def __init__(
        self,
        llm_client: LLMClientManager,
        model_id: str,
        action_schema: Dict[str, Any],
        system_prompt: str,
        history_window: Optional[int] = None,
    ):
        tools = _tool_defs_from_action_schema(action_schema)
        super().__init__(
            llm_client,
            model_id,
            system_prompt,
            tools,
            history_window=history_window,
            adapter_prefix="tool_calling",
        )

    def decide(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> ActionDecision:
        result = self._dispatch_tool_call(
            prompt,
            images=images,
            files=files,
            timeout_seconds=timeout_seconds,
        )

        assistant_text = result["assistant_text"]
        tool_name = result["tool_name"]
        parsed_args = result["parsed_args"]
        args_valid = result["args_valid"]
        has_tool_call = result["has_tool_call"]
        response = result["response"]
        provider_error = result.get("provider_error")
        llm_reasoning = result.get("llm_reasoning")

        if not has_tool_call:
            return ActionDecision(
                action=None,
                parse_success=False,
                raw_response=assistant_text,
                mode_requested=self._mode_label(),
                mode_used=self._mode_label(),
                adapter=self._adapter_name(response),
                llm_reasoning=llm_reasoning,
                error=provider_error or "model_returned_no_tool_call",
            )

        action: Optional[Dict[str, Any]] = None
        if tool_name:
            action = {"type": tool_name}
            action.update(parsed_args)

        raw_response = json.dumps(
            {
                "assistant_text": assistant_text,
                "llm_reasoning": llm_reasoning,
                "tool_call": {"name": tool_name, "arguments": parsed_args},
            },
            ensure_ascii=False,
            default=str,
        )

        parse_success = bool(tool_name) and args_valid
        error = None
        if not tool_name:
            error = "missing_tool_name"
        elif not args_valid:
            error = "failed_to_parse_tool_arguments"

        return ActionDecision(
            action=action,
            parse_success=parse_success,
            raw_response=raw_response,
            mode_requested=self._mode_label(),
            mode_used=self._mode_label(),
            adapter=self._adapter_name(response),
            llm_reasoning=llm_reasoning,
            error=error,
        )
