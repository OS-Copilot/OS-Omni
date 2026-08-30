"""Task-specific oracle provider for Wireshark benchmark sanity runs."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class WiresharkOracleAdapter(ProviderAdapter):
    """Emit deterministic PowerShell actions that directly produce the expected output
    artifacts for each Wireshark task, bypassing the GUI.
    """

    provider_name = "wireshark_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    _TASK_ACTIONS: Dict[str, List[Dict[str, Any]]] = {
        "open_and_filter": [
            {
                "type": "launch_app",
                "assistant_text": "Write http_only.pcapng via tshark/oracle shortcut.",
            },
            {
                "type": "wait",
                "ms": 6000,
                "assistant_text": "Wait for tshark to finish writing the filtered pcap.",
            },
            {
                "type": "success",
                "message": "Filtered pcap saved.",
                "assistant_text": "Open-and-filter task complete.",
            },
        ],
        "advanced_filter_export": [
            {
                "type": "launch_app",
                "assistant_text": "Write tcp80.pcapng and http_objects folder.",
            },
            {
                "type": "wait",
                "ms": 8000,
                "assistant_text": "Wait for tshark to finish writing outputs.",
            },
            {
                "type": "success",
                "message": "Advanced filter exports written.",
                "assistant_text": "Advanced filter task complete.",
            },
        ],
        "statistics_report": [
            {
                "type": "launch_app",
                "assistant_text": "Write protocol hierarchy and IPv4 conversations text files.",
            },
            {
                "type": "wait",
                "ms": 8000,
                "assistant_text": "Wait for tshark statistics to be written.",
            },
            {
                "type": "success",
                "message": "Statistics reports saved.",
                "assistant_text": "Statistics task complete.",
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
                        call_id=f"wireshark-oracle-{step_index + 1}",
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
            raise ValueError(f"Unsupported Wireshark oracle task: {task_key!r}")
        return actions

    @staticmethod
    def _resolve_task_key(messages: List[Message]) -> str:
        system_text = "\n".join(
            message.text_content()
            for message in messages
            if getattr(message, "role", "") == "system"
        ).lower()

        if "http_only.pcapng" in system_text:
            return "open_and_filter"
        if "tcp80.pcapng" in system_text or "http_objects" in system_text:
            return "advanced_filter_export"
        if "protocol_hierarchy.txt" in system_text or "ipv4_conversations.txt" in system_text:
            return "statistics_report"
        raise ValueError("Wireshark oracle could not match the current task instruction.")

    @classmethod
    def _powershell_command_for_task(cls, task_key: str) -> str:
        """Return a .bat wrapper path that ``cmd /c start "" <path>`` can execute.

        The .bat wrappers and their .ps1 targets live under
        ``platforms/windows/vm/setup/`` and are exposed inside the VM via
        ``\\\\host.lan\\Data\\``. The runtime's ``launch_app`` prepends
        ``cmd /c start "" <app_name>``; when ``app_name`` contains spaces the
        quoted form is treated by ``start`` as a single file path and fails.
        A ``.bat`` path is a single token, so ``start`` executes it correctly.
        """

        return fr"\\host.lan\Data\wireshark_oracle_{task_key}.bat"
