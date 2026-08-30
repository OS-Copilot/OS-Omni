"""Task-specific oracle provider for Zotero benchmark sanity runs."""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class ZoteroOracleAdapter(ProviderAdapter):
    """Emit deterministic PowerShell actions that drive Zotero tasks to the expected end state.

    Instead of interacting with the GUI, the oracle directly writes to Zotero's
    ``zotero.sqlite`` database. Zotero must be closed before the SQLite writes
    to avoid lock conflicts, so the oracle terminates the process first.
    """

    provider_name = "zotero_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    _TASK_ACTIONS: Dict[str, List[Dict[str, Any]]] = {
        "add_item_by_identifier": [
            {
                "type": "launch_app",
                "assistant_text": "Write the DOI item directly into Zotero's SQLite library.",
            },
            {
                "type": "wait",
                "ms": 5000,
                "assistant_text": "Wait for the SQLite write to flush.",
            },
            {
                "type": "success",
                "message": "DOI item added to Zotero library via SQLite oracle.",
                "assistant_text": "Add-by-identifier task complete.",
            },
        ],
        "create_collection_with_notes": [
            {
                "type": "launch_app",
                "assistant_text": "Create the multi-window Research bridge library state in Zotero SQLite.",
            },
            {
                "type": "wait",
                "ms": 5000,
                "assistant_text": "Wait for the SQLite writes to flush.",
            },
            {
                "type": "success",
                "message": "Research bridge collections, items, tags, and notes added.",
                "assistant_text": "Multi-window create-collection task complete.",
            },
        ],
        "organize_library": [
            {
                "type": "launch_app",
                "assistant_text": "Create the multi-window reference bridge library state in Zotero SQLite.",
            },
            {
                "type": "wait",
                "ms": 5000,
                "assistant_text": "Wait for the SQLite writes to flush.",
            },
            {
                "type": "success",
                "message": "Reference bridge collections, items, tags, and notes added.",
                "assistant_text": "Multi-window organize-library task complete.",
            },
        ],
    }

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        task_key = self._resolve_task_key(request.messages)
        actions = self._actions_for_task(task_key)
        step_index = self._step_index(request.messages)

        if step_index < len(actions):
            action = dict(actions[step_index])
        else:
            action = {"type": "success", "message": "Oracle plan completed."}

        if action.get("type") == "launch_app":
            action["app_name"] = self._powershell_command_for_task(task_key)

        action_type = str(action.get("type") or "").strip()
        assistant_text = str(action.get("assistant_text") or f"Oracle step {step_index + 1}: {action_type}")
        tool_payload = {k: v for k, v in action.items() if k not in {"type", "assistant_text"}}

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(tool_payload, ensure_ascii=False),
                        call_id=f"zotero-oracle-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={
                    "provider": self.provider_name,
                    "task_key": task_key,
                    "step_index": step_index,
                    "action": action,
                },
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        json_action = dict(action)
        json_action.pop("assistant_text", None)
        return ProviderResult(
            text=json.dumps(json_action, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={
                "provider": self.provider_name,
                "task_key": task_key,
                "step_index": step_index,
                "action": action,
            },
        )

    @staticmethod
    def _step_index(messages: List[Message]) -> int:
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    @classmethod
    def _actions_for_task(cls, task_key: str) -> List[Dict[str, Any]]:
        actions = cls._TASK_ACTIONS.get(task_key)
        if not actions:
            raise ValueError(f"Unsupported Zotero oracle task: {task_key!r}")
        return actions

    @staticmethod
    def _resolve_task_key(messages: List[Message]) -> str:
        system_text = "\n".join(
            message.text_content()
            for message in messages
            if getattr(message, "role", "") == "system"
        ).lower()

        if "add item by identifier" in system_text or "10.1038/nature14539" in system_text:
            return "add_item_by_identifier"
        if '"research"' in system_text or "deep learning" in system_text:
            return "create_collection_with_notes"
        if "reference shelf" in system_text and "designing data-intensive applications" in system_text:
            return "organize_library"
        raise ValueError("Zotero oracle could not match the current task instruction.")

    @classmethod
    def _powershell_command_for_task(cls, task_key: str) -> str:
        """Invoke a static .bat wrapper that shells out to the Python oracle script.

        The runtime's ``launch_app`` uses ``cmd /c start "" "<app_name>"``.
        When ``app_name`` contains spaces (e.g. ``py -3 <path>``), ``start``
        treats the quoted string as a single file path and silently fails. A
        ``.bat`` wrapper is a single-token path, so ``start`` can actually
        execute it.
        """

        return fr"\\host.lan\Data\zotero_oracle_{task_key}.bat"
