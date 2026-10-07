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


def _osworld_reflection_pyautogui_system_prompt(
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
            "For each step, you will get an observation of the desktop by accessibility tree, which is based on "
            "AT-SPI library. And you will predict the action of the computer based on the accessibility tree."
        )
    else:
        observation_text = (
            "For each step, you will get an observation of the desktop by 1) a screenshot; and 2) accessibility "
            "tree, which is based on AT-SPI library. And you will predict the action of the computer based on the "
            "screenshot and accessibility tree."
        )

    password_text = ""
    if client_password:
        password_text = f" My computer's password is '{client_password}', feel free to use it when you need sudo rights."

    return (
        "You are an agent which follow my instruction and perform desktop computer tasks as instructed. "
        "You have good knowledge of computer and good internet connection and assume your code will run on a "
        "computer for controlling the mouse and keyboard. "
        f"{observation_text}\n"
        "You are required to use `pyautogui` to perform the action grounded to the observation, but DONOT use "
        "the `pyautogui.locateCenterOnScreen` function to locate the element you want to operate with since we "
        "have no image of the element you want to operate with. DONOT USE `pyautogui.screenshot()` to make "
        "screenshot. Return one line or multiple lines of python code to perform the action each time, be time "
        "efficient.\n"
        "The code sandbox only allows `import pyautogui`, `import time`, direct pyautogui calls, simple loops, "
        "and `print`. Do not import tkinter, os, subprocess, pyperclip, bpy, bmesh, or any other module. Do not "
        "use clipboard-based automation or application-internal scripting unless it is reachable through normal "
        "keyboard and mouse actions. Do not press Alt+F4 or close windows unless the task explicitly asks you to "
        "close that exact app window.\n"
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


class LinuxPromptBuilder:
    """Linux runtime adapter for the shared core prompt builders."""

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
            extra = _osworld_reflection_pyautogui_system_prompt(
                observation_mode=self.observation_mode,
                goal=goal,
                client_password=self.client_password,
            )
            if extra_system_prompt:
                extra = f"{extra}\n\n{extra_system_prompt}"
            return extra.strip()

        return build_system_prompt(
            task=goal,
            platform="Linux",
            observation_mode=self.observation_mode,
            tool_calling=self.tool_calling,
            action_rules=action_rules,
            extra_system_prompt=extra_system_prompt,
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
