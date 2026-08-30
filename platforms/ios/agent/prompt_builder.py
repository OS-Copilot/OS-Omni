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
    "rect",
    "tap",
    "tap_norm",
    "accessible",
)


def _ios_reflection_action_system_prompt(
    *,
    goal: str,
) -> str:
    return (
        "You are an agent which follows my instruction and performs iOS simulator tasks as instructed. "
        "You have good knowledge of iOS and assume your code will run against a WebDriverAgent-backed "
        "Appium/XCUITest session for controlling the simulator. For each step, you will get an observation "
        "of an image, which is the screenshot of the current iOS screen, and you will predict the action "
        "based on the image.\n"
        "You are required to use the existing Appium `driver` to perform the action grounded to the observation. "
        "Return one line or multiple lines of Python code to perform the action each time, be time efficient. "
        "Use direct driver calls such as `driver.execute_script(...)`, `driver.find_element(...)`, "
        "`driver.switch_to.active_element.send_keys(...)`, and `driver.activate_app(...)`.\n"
        "The code sandbox provides the existing `driver`, `AppiumBy`, `WebDriverWait`, `EC`, common "
        "Appium/Selenium exceptions, `time`, simple Python builtins, and `print`. Do not create a new driver, "
        "create a raw WDA client, import modules, run shell commands, read or write host files, access "
        "databases or environment variables, or use capabilities outside Appium GUI automation.\n"
        "When predicting multiple lines of code, make some small sleep like `time.sleep(0.5)` interval so that "
        "the simulator could take; Each time you need to predict a complete code, no variables or function can "
        "be shared from history. When using coordinates, reason from the screenshot by relative position and "
        "convert to Appium logical coordinates with `driver.get_window_size()` before calling the driver, for "
        "example `driver.execute_script(\"mobile: tap\", {\"x\": x, \"y\": y})`.\n"
        "You should first give the current screenshot and previous things we did a short reflection in plain text, "
        "and then return the code or special code. The reflection should be brief.\n"
        "You ONLY need to return the code inside a code block, like this: ```python\n# your code here\n```. "
        "Specially, it is also allowed to return the following special code: When you think you have to wait for "
        "some time, return ```WAIT```; When you think the task can not be done, return ```FAIL```, don't easily "
        "say ```FAIL```, try your best to do the task; When you think the task is done, return ```DONE```.\n"
        f"You are asked to complete the following task: {goal}\n"
        "First give the current screenshot and previous things we did a short reflection, then RETURN ME THE CODE "
        "OR SPECIAL CODE I ASKED FOR. NEVER EVER RETURN ME ANYTHING ELSE."
    ).strip()


class IOSPromptBuilder:
    """iOS runtime adapter for the shared core prompt builders."""

    def __init__(self, *, observation_mode: str, tool_calling: bool, action_mode: str = "code_adapter") -> None:
        self.observation_mode = str(observation_mode).strip()
        self.tool_calling = bool(tool_calling)
        self.action_mode = str(action_mode).strip() or "code_adapter"

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
            prompt = _ios_reflection_action_system_prompt(
                goal=goal,
            )
            if extra_system_prompt:
                prompt = f"{prompt}\n\n{extra_system_prompt}"
            return prompt.strip()

        return build_system_prompt(
            task=goal,
            platform="iOS",
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
        observation_mode = "screenshot_only" if self.action_mode == "code_adapter" else self.observation_mode
        prompt = build_step_prompt(
            observation_mode=observation_mode,
            ui_context=self._build_ui_context(getattr(observation, "ui_nodes", None)),
            extra_step_prompt=extra_step_prompt,
        )
        if self.action_mode == "code_adapter":
            prompt += "\n\nFirst give a short reflection, then return the next Appium `driver` code block or special code."
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
