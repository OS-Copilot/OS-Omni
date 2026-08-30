from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from core.prompt.builders import build_step_prompt, build_system_prompt

_UI_CONTEXT_KEYS = (
    "resource-id",
    "class",
    "text",
    "content-desc",
    "clickable",
    "enabled",
    "focused",
    "bounds",
    "index",
)


def _android_reflection_adb_system_prompt(
    *,
    observation_mode: str,
    goal: str,
) -> str:
    observation_mode = str(observation_mode).strip()
    if observation_mode == "screenshot_only":
        observation_text = "For each step, you will get an Android screenshot."
    elif observation_mode == "a11y_tree_only":
        observation_text = "For each step, you will get an Android accessibility tree."
    else:
        observation_text = "For each step, you will get an Android screenshot and accessibility tree."

    return (
        "You are an Android GUI agent. "
        f"{observation_text} Predict the next Android action grounded in the current observation.\n"
        "You should first give the current screenshot and previous things we did a short reflection in plain text, "
        "and then return exactly one fenced adb command block or one special fenced code block. "
        "The reflection should be brief.\n"
        "You are required to use adb commands to perform the action grounded to the observation. Return one line "
        "or multiple lines of adb commands each time, be time efficient. Each time you need to predict a complete "
        "adb command block; no variables or state can be shared from history.\n"
        "A single adb command block may contain up to 3 adb commands.\n"
        "Allowed adb commands are limited to GUI control commands:\n"
        "- adb shell input tap X Y\n"
        "- adb shell input swipe X1 Y1 X2 Y2 [DURATION_MS]\n"
        "- adb shell input text TEXT\n"
        "- adb shell input keyevent KEYCODE_BACK|KEYCODE_HOME|KEYCODE_ENTER|KEYCODE_DEL|KEYCODE_SPACE\n"
        "- adb shell monkey -p PACKAGE -c android.intent.category.LAUNCHER 1\n"
        "- sleep SECONDS\n"
        "Press Enter/Back/Delete/Space with input keyevent. You do not need to tap individual soft-keyboard keys "
        "to enter text.\n"
        "Coordinates are Android screenshot pixel coordinates. For special cases, return ```WAIT```, "
        "```DONE```, or ```FAIL```. Do not return JSON, pyautogui code, explanatory bullets, "
        "or commands outside the allowed list.\n"
        f"You are asked to complete the following task: {goal}\n"
        "Return exactly two parts: first a brief plain-text reflection, then the fenced adb command block or "
        "fenced special code. Do not include anything else."
    ).strip()


class AndroidPromptBuilder:
    """Android runtime adapter for the shared core prompt builders."""

    def __init__(
        self,
        *,
        observation_mode: str,
        tool_calling: bool,
        action_mode: str = "code_adapter",
    ) -> None:
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
            prompt = _android_reflection_adb_system_prompt(
                observation_mode=self.observation_mode,
                goal=goal,
            )
            if extra_system_prompt:
                prompt = f"{prompt}\n\n{extra_system_prompt}"
            return prompt.strip()

        android_extra_prompt_parts: list[str] = []
        if self.observation_mode == "screenshot_only":
            android_extra_prompt_parts.append(
                "In screenshot-only mode, never use visible text labels, resource-id values, or content-desc strings "
                "as tap/press/swipe targets. Use normalized or pixel coordinates for visible controls instead."
            )
        if extra_system_prompt:
            android_extra_prompt_parts.append(extra_system_prompt)

        return build_system_prompt(
            task=goal,
            platform="Android",
            observation_mode=self.observation_mode,
            tool_calling=self.tool_calling,
            action_rules=action_rules,
            extra_system_prompt="\n".join(android_extra_prompt_parts) if android_extra_prompt_parts else None,
        )

    def build_step_prompt(
        self,
        *,
        observation: Any,
        extra_step_prompt: str | None = None,
    ) -> str:
        ui_context = ""
        if isinstance(observation, dict):
            ui_context = self._build_ui_context_from_xml(
                observation.get("ui_hierarchy_xml", "")
            )
        else:
            ui_context = self._build_ui_context(getattr(observation, "ui_nodes", None))

        prompt = build_step_prompt(
            observation_mode=self.observation_mode,
            ui_context=ui_context,
            extra_step_prompt=extra_step_prompt,
        )
        if self.action_mode == "code_adapter":
            prompt += (
                "\n\nFirst give a short reflection, then return the next adb command block or special code."
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

    @staticmethod
    def _build_ui_context_from_xml(xml_str: str) -> str:
        """Parse Android UI hierarchy XML into structured text."""
        if not xml_str or not xml_str.strip():
            return "(No interactive elements visible)"

        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_str)
        except Exception:
            return xml_str[:2000] if len(xml_str) > 2000 else xml_str

        lines: list[str] = []
        for node in root.iter("node"):
            attrs = node.attrib
            compact = {}
            for key in _UI_CONTEXT_KEYS:
                val = attrs.get(key, "")
                if val and val not in ("false", ""):
                    compact[key] = val
            if compact:
                lines.append(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))

        return "\n".join(lines) if lines else "(No interactive elements visible)"
