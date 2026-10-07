"""Qwen's XML computer_use protocol, translated to Linux GUI actions.

Protocol reference: https://github.com/xlang-ai/OSWorld/tree/main/mm_agents/qwen
Coordinates are normalized to 0..1000 and converted using the current screenshot.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from PIL import Image

from platforms.linux.core.runtime_types import ActionDecision
from .base_planner import BaseJsonPlanner


def build_qwen_system_prompt(instruction: str) -> str:
    tool = {
        "type": "function",
        "function": {
            "name": "computer_use",
            "description": (
                "Control the desktop through its visible GUI. Start applications from desktop icons. "
                "The coordinate space is 1000x1000: the top-left is [0,0] and bottom-right [1000,1000]. "
                "Locate each target in the screenshot and click its center. Wait for slow applications."
            ),
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": [
                        "left_click", "right_click", "middle_click", "double_click", "triple_click",
                        "mouse_move", "left_click_drag", "type", "key", "scroll", "hscroll",
                        "wait", "terminate",
                    ]},
                    "coordinate": {"type": "array", "description": "[x,y] in the 0..1000 coordinate space."},
                    "text": {"type": "string", "description": "Text to type, or modifier keys for clicks/scroll (e.g. ctrl+shift)."},
                    "keys": {"type": "array", "description": "Keyboard chord for action=key, e.g. [ctrl, c]."},
                    "pixels": {"type": "number", "description": "Scroll distance; positive up/right, negative down/left."},
                    "time": {"type": "number", "description": "Seconds to wait."},
                    "status": {"type": "string", "enum": ["success", "failure"]},
                },
            },
        },
    }
    return (
        "You are a desktop assistant. Complete the user's task using the computer_use tool.\n"
        "# Tools\n<tools>\n" + json.dumps(tool) + "\n</tools>\n"
        "For each step, describe the next action briefly, then output exactly one tool call:\n"
        "<tool_call>\n<function=computer_use>\n<parameter=action>left_click</parameter>\n"
        "<parameter=coordinate>[500,500]</parameter>\n</function>\n</tool_call>\n"
        "Use the same XML parameter format for all actions. Do not output Python code. "
        "Use terminate with status success only when the task is complete, or failure when infeasible.\n\n"
        "User task:\n" + instruction
    )


def parse_qwen_call(response: str) -> dict[str, Any]:
    calls = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", response, re.DOTALL)
    if len(calls) != 1:
        raise ValueError("Expected exactly one computer_use tool call")
    match = re.fullmatch(r"<function=computer_use>\s*(.*?)\s*</function>", calls[0], re.DOTALL)
    if not match:
        raise ValueError("Expected function=computer_use")
    params: dict[str, Any] = {}
    for name, raw in re.findall(r"<parameter=([^>]+)>\s*(.*?)\s*</parameter>", match[1], re.DOTALL):
        if name in params:
            raise ValueError(f"Duplicate parameter: {name}")
        if name == "coordinate":
            params[name] = json.loads(raw)
        elif name == "keys":
            params[name] = _parse_keys(raw)
        else:
            params[name] = raw
    if not params.get("action"):
        raise ValueError("Missing action")
    return params


def _parse_keys(raw: str) -> list[str]:
    """Read a key chord; the tool schema's own example spells it ``[ctrl, c]``."""
    try:
        value = json.loads(raw)
    except ValueError:
        text = raw.strip()
        if text.startswith("[") and text.endswith("]"):
            value = [part.strip().strip("'\"") for part in text[1:-1].split(",")]
        else:
            value = [part.strip() for part in text.split("+")]
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(str(key).strip() for key in value):
        raise ValueError("Keys must be a non-empty list of key names")
    return [str(key).strip() for key in value]


def _key(value: Any) -> str:
    key = str(value).strip().lower()
    aliases = {"control": "ctrl", "control_l": "ctrl", "control_r": "ctrl", "return": "enter",
               "super": "win", "super_l": "win", "meta": "win", "escape": "esc",
               "page_down": "pagedown", "page_up": "pageup", "shift_l": "shift", "alt_l": "alt"}
    return aliases.get(key, key)


def qwen_action(params: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    action = params["action"]
    if action == "terminate":
        status = params.get("status")
        if status == "success":
            return {"type": "success", "message": "Model declared task complete"}
        if status == "failure":
            return {"type": "fail", "reason": "Model declared task infeasible"}
        raise ValueError("Invalid termination status")
    if action == "wait":
        # The model sometimes wraps the number in a list, e.g. "[2.0]".
        seconds = float(str(params.get("time", 1)).strip().strip("[]") or 1)
        if not math.isfinite(seconds) or not 0 <= seconds <= 60:
            raise ValueError("Wait must be between 0 and 60 seconds")
        return {"type": "wait", "ms": round(seconds * 1000)}

    lines = ["import pyautogui"]
    position = None
    if "coordinate" in params:
        coordinate = params["coordinate"]
        if not isinstance(coordinate, list) or len(coordinate) != 2:
            raise ValueError("Coordinate must contain exactly two numbers")
        x, y = map(float, coordinate)
        if not all(math.isfinite(v) and 0 <= v <= 1000 for v in (x, y)):
            raise ValueError("Coordinates must be finite numbers between 0 and 1000")
        position = (min(width - 1, round(x * width / 1000)), min(height - 1, round(y * height / 1000)))

    clicks = {"left_click": "click", "right_click": "rightClick", "middle_click": "middleClick",
              "double_click": "doubleClick", "triple_click": "click"}
    modifiers = []
    if action in {*clicks, "scroll", "hscroll"}:
        modifiers = [_key(k) for k in str(params.get("text", "")).split("+") if k.strip()]
        lines.extend(f"pyautogui.keyDown({key!r})" for key in modifiers)
    if action in clicks or action in {"mouse_move", "left_click_drag"}:
        if position is None:
            raise ValueError(f"{action} requires coordinates")
        method = clicks.get(action) or ("moveTo" if action == "mouse_move" else "dragTo")
        extra = ", clicks=3, interval=0.1" if action == "triple_click" else ", duration=0.5" if action == "left_click_drag" else ""
        lines.append(f"pyautogui.{method}({position[0]}, {position[1]}{extra})")
    elif action == "type":
        if "text" not in params:
            raise ValueError("type requires text")
        # pyautogui types "<" as Shift + the keycode of "less", which is the extra
        # ISO key on the guest's pc105 keymap and yields ">"; use Shift+comma.
        for index, chunk in enumerate(str(params["text"]).split("<")):
            if index:
                lines.append("pyautogui.hotkey('shift', ',')")
            if chunk:
                lines.append(f"pyautogui.write({chunk!r}, interval=0.02)")
    elif action == "key":
        keys = params.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ValueError("key requires a non-empty list of keys")
        keys = [_key(key) for key in keys]
        method = "press" if len(keys) == 1 else "hotkey"
        lines.append(f"pyautogui.{method}({', '.join(repr(key) for key in keys)})")
    elif action in {"scroll", "hscroll"}:
        pixels = float(params.get("pixels", 0))
        if not math.isfinite(pixels) or abs(pixels) > 10000:
            raise ValueError("Invalid scroll distance")
        if position:
            lines.append(f"pyautogui.moveTo({position[0]}, {position[1]})")
        clicks_count = round(pixels / 100) or (1 if pixels > 0 else -1 if pixels < 0 else 0)
        method = "scroll" if action == "scroll" else "hscroll"
        lines.append(f"pyautogui.{method}({clicks_count})")
    else:
        raise ValueError(f"Unsupported computer action: {action}")
    lines.extend(f"pyautogui.keyUp({key!r})" for key in reversed(modifiers))
    return {"type": "python_code", "language": "python", "code": "\n".join(lines), "timeout_seconds": 120}


class QwenComputerUsePlanner(BaseJsonPlanner):
    def __init__(self, llm_client, model_id, system_prompt, history_window=None, session_metadata=None):
        metadata = dict(session_metadata or {})
        instruction = metadata.get("task_instruction")
        if not instruction:
            raise ValueError("Qwen computer_use requires task_instruction in session metadata")
        super().__init__(llm_client, model_id, build_qwen_system_prompt(instruction),
                         history_window=history_window, session_metadata=metadata,
                         adapter_prefix="qwen_computer_use")

    def decide(self, prompt, images=None, files=None, timeout_seconds=None):
        if not images:
            raise ValueError("Qwen computer_use requires a screenshot")
        with Image.open(images[0]) as screenshot:
            width, height = screenshot.size
        response = self._dispatch_chat(
            "Observe the current screenshot and perform the next action toward the user's task. "
            "Use computer_use with coordinates in the 1000x1000 coordinate space.",
            images=images, timeout_seconds=timeout_seconds,
        )
        provider_error = self._response_error_text(response)
        raw = response.text or provider_error or ""
        action, error, params = None, provider_error, None
        if not provider_error:
            try:
                params = parse_qwen_call(raw)
                action = qwen_action(params, width, height)
            except (ValueError, TypeError, KeyError) as exc:
                error = str(exc)
        return ActionDecision(
            action=action, parse_success=action is not None, raw_response=raw,
            mode_requested="code_adapter", mode_used="code_adapter", adapter="qwen_computer_use",
            llm_reasoning={"computer_use": params, "usage": response.usage}, error=error,
        )
