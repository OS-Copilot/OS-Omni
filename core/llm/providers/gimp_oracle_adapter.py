"""Task-specific oracle provider for GIMP benchmark sanity runs."""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class GimpOracleAdapter(ProviderAdapter):
    """Emit deterministic Pillow-based actions that drive GIMP tasks to their expected end state."""

    provider_name = "gimp_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    _WORKSPACE = "/tmp/helloworld_gimp"
    _INPUT_IMAGE = "/tmp/helloworld_gimp/input.png"

    _TASK_ACTIONS: Dict[str, List[Dict[str, Any]]] = {
        "scale_image": [
            {
                "type": "launch_app",
                "app_name": "",
                "assistant_text": "Scale the input image to 800×600 using Pillow, bypassing the GIMP GUI.",
            },
            {
                "type": "wait",
                "ms": 2000,
                "assistant_text": "Wait for the Pillow operation to complete.",
            },
            {
                "type": "success",
                "message": "Image scaled to 800×600 and saved as scaled.png.",
                "assistant_text": "Scale task complete.",
            },
        ],
        "convert_grayscale": [
            {
                "type": "launch_app",
                "app_name": "",
                "assistant_text": "Convert the input image to grayscale using Pillow, bypassing the GIMP GUI.",
            },
            {
                "type": "wait",
                "ms": 2000,
                "assistant_text": "Wait for the Pillow operation to complete.",
            },
            {
                "type": "success",
                "message": "Image converted to grayscale and saved as gray.png.",
                "assistant_text": "Grayscale conversion task complete.",
            },
        ],
        "rotate_90": [
            {
                "type": "launch_app",
                "app_name": "",
                "assistant_text": "Rotate the input image 90 degrees clockwise using Pillow, bypassing the GIMP GUI.",
            },
            {
                "type": "wait",
                "ms": 2000,
                "assistant_text": "Wait for the Pillow operation to complete.",
            },
            {
                "type": "success",
                "message": "Image rotated 90° clockwise and saved as rotated.png.",
                "assistant_text": "Rotation task complete.",
            },
        ],
        "crop_center": [
            {
                "type": "launch_app",
                "app_name": "",
                "assistant_text": "Crop the center 640×480 region from the input image using Pillow, bypassing the GIMP GUI.",
            },
            {
                "type": "wait",
                "ms": 2000,
                "assistant_text": "Wait for the Pillow operation to complete.",
            },
            {
                "type": "success",
                "message": "Image cropped to 640×480 at center and saved as cropped.png.",
                "assistant_text": "Crop task complete.",
            },
        ],
        "export_jpeg": [
            {
                "type": "launch_app",
                "app_name": "",
                "assistant_text": "Export the input image as JPEG using Pillow, bypassing the GIMP GUI.",
            },
            {
                "type": "wait",
                "ms": 2000,
                "assistant_text": "Wait for the Pillow operation to complete.",
            },
            {
                "type": "success",
                "message": "Image exported as JPEG to export.jpg.",
                "assistant_text": "JPEG export task complete.",
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
            action["app_name"] = self._build_command(task_key)

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
                        call_id=f"gimp-oracle-{step_index + 1}",
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
            raise ValueError(f"Unsupported GIMP oracle task: {task_key!r}")
        return actions

    @staticmethod
    def _resolve_task_key(messages: List[Message]) -> str:
        system_text = "\n".join(
            message.text_content()
            for message in messages
            if getattr(message, "role", "") == "system"
        ).lower()

        if "scaled.png" in system_text or "scale the canvas" in system_text or "scale it to" in system_text:
            return "scale_image"
        if "gray.png" in system_text or "grayscale" in system_text:
            return "convert_grayscale"
        if "rotated.png" in system_text or "rotate" in system_text:
            return "rotate_90"
        if "cropped.png" in system_text or "crop" in system_text:
            return "crop_center"
        if "export.jpg" in system_text or "jpeg" in system_text:
            return "export_jpeg"
        raise ValueError("GIMP oracle could not match the current task instruction.")

    @classmethod
    def _build_command(cls, task_key: str) -> str:
        code = cls._python_code_for_task(task_key)
        return f"python3 -c {shlex.quote(code)}"

    @classmethod
    def _python_code_for_task(cls, task_key: str) -> str:
        inp = cls._INPUT_IMAGE
        ws = cls._WORKSPACE
        if task_key == "scale_image":
            return (
                f"from PIL import Image; "
                f"img = Image.open({json.dumps(inp)}).convert(\"RGB\"); "
                f"out = img.resize((800, 600), Image.LANCZOS); "
                f"out.save({json.dumps(ws + '/scaled.png')}, \"PNG\")"
            )
        if task_key == "convert_grayscale":
            return (
                f"from PIL import Image; "
                f"img = Image.open({json.dumps(inp)}).convert(\"L\"); "
                f"img.save({json.dumps(ws + '/gray.png')}, \"PNG\")"
            )
        if task_key == "rotate_90":
            return (
                f"from PIL import Image; "
                f"img = Image.open({json.dumps(inp)}).convert(\"RGB\"); "
                f"out = img.rotate(-90, expand=True); "
                f"out.save({json.dumps(ws + '/rotated.png')}, \"PNG\")"
            )
        if task_key == "crop_center":
            return (
                f"from PIL import Image; "
                f"img = Image.open({json.dumps(inp)}).convert(\"RGB\"); "
                f"w, h = img.size; "
                f"left = (w - 640) // 2; top = (h - 480) // 2; "
                f"out = img.crop((left, top, left + 640, top + 480)); "
                f"out.save({json.dumps(ws + '/cropped.png')}, \"PNG\")"
            )
        if task_key == "export_jpeg":
            return (
                f"from PIL import Image; "
                f"img = Image.open({json.dumps(inp)}).convert(\"RGB\"); "
                f"img.save({json.dumps(ws + '/export.jpg')}, \"JPEG\", quality=80)"
            )
        raise ValueError(f"Unsupported GIMP oracle task: {task_key!r}")
