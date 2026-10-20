from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from core.prompt.builders import build_step_prompt, build_system_prompt

_UI_CONTEXT_KEYS = (
    "id",
    "type",
    "text",
    "selector",
    "enabled",
    "focused",
    "active",
    "rect",
    "tap",
    "tap_norm",
    "accessible",
)


def _windows_reflection_pyautogui_system_prompt(
    *,
    observation_mode: str,
    goal: str,
    client_password: str | None = None,
) -> str:
    observation_mode = str(observation_mode).strip()
    if observation_mode == "screenshot_only":
        observation_text = (
            "For each step, you will get an observation of an image, which is the screenshot of the computer screen "
            "and you will predict the action of the computer based on the image."
        )
    elif observation_mode == "a11y_tree_only":
        observation_text = (
            "For each step, you will get an observation of the desktop by accessibility tree. "
            "And you will predict the action of the computer based on the accessibility tree."
        )
    else:
        observation_text = (
            "For each step, you will get an observation of the desktop by 1) a screenshot; and 2) accessibility "
            "tree. And you will predict the action of the computer based on the screenshot and accessibility tree."
        )

    password_text = ""
    if client_password:
        password_text = f" My computer's password is '{client_password}', feel free to use it when needed."

    is_blender_task = "blender" in goal.lower()
    allowed_code_rule = (
        "For Blender tasks, your pyautogui action code may import `pyautogui`, `time`, and a clipboard helper "
        "such as `tkinter` or `pyperclip` solely to paste Blender Python text into Blender. For multi-command "
        "Blender Python, prefer putting the full command or exec script on the clipboard and pressing Ctrl+V "
        "in Blender's Python Console or Text Editor instead of typing long code with `pyautogui.write`. "
        "Do not use Shift+F4 for Blender because it is unreliable in this VM. Use the editor-type selector "
        "in the lower-left of the Blender area, choose Python Console, click the `>>>` prompt, paste the "
        "exec command, and press Enter.\n"
        if is_blender_task
        else (
            "The code sandbox only allows `import pyautogui`, `import time`, direct pyautogui calls, simple loops, "
            "and `print`. "
        )
    )
    scripting_rule = (
        "For Blender tasks, you may use Blender's graphical UI controls, Blender Python Console, bpy commands, "
        "scripts, macros, or pasted/executed code by driving Blender through normal pyautogui keyboard and mouse "
        "actions. Do not use OS shell commands or external terminal windows.\n"
        if is_blender_task
        else (
            "Do not import tkinter, os, subprocess, pyperclip, bpy, bmesh, or any other module. Do not "
            "use clipboard-based automation or application-internal scripting unless it is reachable through normal "
            "keyboard and mouse actions.\n"
        )
    )

    return (
        "You are an agent which follow my instruction and perform desktop computer tasks as instructed. "
        "You have good knowledge of computer and good internet connection and assume your code will run on a "
        "Windows computer for controlling the mouse and keyboard. "
        f"{observation_text}\n"
        "You are required to use `pyautogui` to perform the action grounded to the observation, but DONOT use "
        "the `pyautogui.locateCenterOnScreen` function to locate the element you want to operate with since we "
        "have no image of the element you want to operate with. DONOT USE `pyautogui.screenshot()` to make "
        "screenshot. Return one line or multiple lines of python code to perform the action each time, be time "
        "efficient.\n"
        f"{allowed_code_rule}"
        f"{scripting_rule}"
        "Do not press Alt+F4 or close windows unless the task explicitly asks you to "
        "close that exact app window.\n"
        "Never open or use cmd.exe, PowerShell, pwsh, Windows Terminal, or any terminal/shell window during a task. "
        "Do not use Win+R to launch shell commands. Complete the requested work inside the target application UI.\n"
        "When predicting multiple lines of code, make some small sleep like `time.sleep(0.5)` interval so that "
        "the machine could take; Each time you need to predict a complete code, no variables or function can be "
        "shared from history. You need to specify the coordinates by yourself based on your observation of the "
        "current observation, but you should be careful to ensure that the coordinates are correct.\n"
        "You should first give the current screenshot and previous things we did a short reflection in plain text, "
        "and then return the code or special code. The reflection should be brief.\n"
        "You ONLY need to return the code inside a code block, like this: ```python\n# your code here\n```. "
        "Specially, it is also allowed to return the following special code: When you think you have to wait for "
        "some time, return ```WAIT```; When you think the task can not be done, return ```FAIL```, don't easily "
        f"say ```FAIL```, try your best to do the task; When you think the task is done, return ```DONE```."
        f"{password_text}\n"
        f"You are asked to complete the following task: {goal}\n"
        "First give the current screenshot and previous things we did a short reflection, then RETURN ME THE CODE "
        "OR SPECIAL CODE I ASKED FOR. NEVER EVER RETURN ME ANYTHING ELSE."
    ).strip()


class WindowsPromptBuilder:
    """Windows runtime adapter for the shared core prompt builders."""

    _EXTRA_SYSTEM_PROMPT = (
        "Windows JSON action format rules:\n"
        "- Return exactly one JSON object and nothing else.\n"
        "- The top-level field `type` is MANDATORY in every response.\n"
        "- All parameters MUST be top-level fields in the same JSON object.\n"
        "- Never use top-level `action`, `action_type`, or `parameters`.\n"
        "- For a single key press, use {\"type\":\"keyboard\",\"action\":\"<key>\",\"count\":1}.\n"
        "- Correct example: {\"type\":\"tap\",\"target\":\"n12\"}\n"
        "- Incorrect example: {\"action\":\"tap\",\"target\":\"n12\"}\n"
    )

    def __init__(
        self,
        *,
        observation_mode: str,
        tool_calling: bool,
        action_mode: str = "code_adapter",
        client_password: str | None = None,
    ) -> None:
        self.observation_mode = str(observation_mode).strip()
        self.tool_calling = bool(tool_calling)
        self.action_mode = str(action_mode).strip() or "code_adapter"
        self.client_password = str(client_password).strip() or None

    def build_system_prompt(
        self,
        *,
        task: Any,
        action_rules: str | None = None,
        extra_system_prompt: str | None = None,
    ) -> str:
        goal = str(getattr(task, "goal", "")).strip()
        if not goal:
            raise ValueError("task.goal cannot be empty")

        if self.action_mode == "code_adapter":
            extra = _windows_reflection_pyautogui_system_prompt(
                observation_mode=self.observation_mode,
                goal=goal,
                client_password=self.client_password,
            )
            if extra_system_prompt:
                extra = f"{extra}\n\n{extra_system_prompt}"
            return extra.strip()

        return build_system_prompt(
            task=goal,
            platform="Windows",
            observation_mode=self.observation_mode,
            tool_calling=self.tool_calling,
            action_rules=action_rules,
            extra_system_prompt=extra_system_prompt or self._EXTRA_SYSTEM_PROMPT,
        )

    def build_step_prompt(
        self,
        *,
        observation: Any,
        extra_step_prompt: str | None = None,
    ) -> str:
        prompt = build_step_prompt(
            observation_mode=self.observation_mode,
            ui_context=self._build_ui_context(getattr(observation, "ui_nodes", None)),
            extra_step_prompt=extra_step_prompt,
        )
        if self.action_mode == "code_adapter":
            width = getattr(observation, "width", None)
            height = getattr(observation, "height", None)
            if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
                prompt += (
                    f"\n\nThe screen is {width}×{height} pixels. Use absolute screen pixel coordinates "
                    f"for pyautogui: x ranges from 0 to {width - 1}, y from 0 to {height - 1}, "
                    "with (0, 0) at the top-left. Do not use normalized coordinates or coordinates "
                    "from a resized preview."
                )
            prompt += (
                "\n\nFirst give a short reflection, then return the next pyautogui code block or special code."
            )
        return prompt

    @staticmethod
    def _build_ui_context(ui_nodes: Any) -> str:
        if not isinstance(ui_nodes, list) or not ui_nodes:
            return "(No interactive elements visible)"

        lines: list[str] = []
        for node in ui_nodes:
            if isinstance(node, Mapping):
                compact_node = {
                    key: node[key]
                    for key in _UI_CONTEXT_KEYS
                    if key in node and node[key] not in (None, "")
                }
                if compact_node:
                    lines.append(json.dumps(compact_node, ensure_ascii=False, separators=(",", ":")))
                    continue
            lines.append(json.dumps(node, ensure_ascii=False, separators=(",", ":"), default=str))
        return "\n".join(lines) if lines else "(No interactive elements visible)"
