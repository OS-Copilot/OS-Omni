"""Backward-compatible imports for the old iOS reflection JSON planner name.

iOS reflection_pyautogui now means Appium Python-code mode. The old module path
is kept so older imports do not silently resurrect the previous JSON behavior.
"""

from __future__ import annotations

from .reflection_pyautogui_planner import (
    ReflectionPyAutoGUIPlanner,
    build_python_action,
    extract_code_or_special,
    validate_appium_python_code,
)

ReflectionJsonActionPlanner = ReflectionPyAutoGUIPlanner
build_reflection_action = build_python_action


def extract_reflection_and_payload(raw):
    return "", extract_code_or_special(raw)

__all__ = [
    "ReflectionPyAutoGUIPlanner",
    "ReflectionJsonActionPlanner",
    "build_python_action",
    "build_reflection_action",
    "extract_code_or_special",
    "extract_reflection_and_payload",
    "validate_appium_python_code",
]
