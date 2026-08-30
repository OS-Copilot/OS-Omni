"""Appium Python-code planner for iOS code_adapter mode."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from platforms.ios.core.runtime_types import ActionDecision

from .base_planner import BaseJsonPlanner

if TYPE_CHECKING:
    from core.llm.llm_client import LLMClientManager

_PYTHON_CODE_BLOCK_RE = re.compile(r"```python\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_FENCED_SPECIAL_RE = re.compile(r"```(?:\s*)(WAIT|DONE|FAIL)\s*```", re.IGNORECASE | re.DOTALL)


def _normalize_code(code: str) -> str:
    return str(code or "").strip()


def extract_code_or_special(raw: str) -> Optional[str]:
    text = str(raw or "").strip()
    if not text:
        return None

    special_match = _FENCED_SPECIAL_RE.search(text)
    if special_match:
        return special_match.group(1).strip().upper()

    code_match = _PYTHON_CODE_BLOCK_RE.search(text)
    if code_match:
        code = _normalize_code(code_match.group(1))
        return code or None

    if text.upper() in {"WAIT", "DONE", "FAIL"}:
        return text.upper()
    return None


def validate_appium_python_code(code: str) -> Tuple[bool, Optional[str]]:
    try:
        compile(str(code or ""), "<ios_reflection_pyautogui_action>", "exec")
    except SyntaxError as exc:
        location = f"line {exc.lineno}" if exc.lineno else "unknown line"
        return False, f"syntax_error at {location}: {exc.msg}"
    return True, None


def build_python_action(raw: str) -> Tuple[Optional[Dict[str, Any]], bool, Optional[Dict[str, Any]], Optional[str]]:
    payload = extract_code_or_special(raw)
    if not payload:
        return None, False, None, "missing_python_code_block"

    special = payload.strip().upper()
    if special == "WAIT":
        return {"type": "wait", "ms": 1000}, True, None, None
    if special == "DONE":
        return {"type": "success", "message": "Model declared task complete"}, True, None, None
    if special == "FAIL":
        return {"type": "fail", "reason": "Model declared task infeasible"}, True, None, None

    code = _normalize_code(payload)
    valid, validation_error = validate_appium_python_code(code)
    if not valid:
        return None, False, None, validation_error

    return {
        "type": "python_code",
        "language": "python",
        "code": code,
        "timeout_seconds": 120,
    }, True, None, None


class ReflectionPyAutoGUIPlanner(BaseJsonPlanner):
    """Planner for iOS Appium Python-code mode."""

    def __init__(
        self,
        llm_client: "LLMClientManager",
        model_id: str,
        system_prompt: str,
        history_window: Optional[int] = None,
    ):
        super().__init__(
            llm_client,
            model_id,
            system_prompt,
            history_window=history_window,
            adapter_prefix="ios_reflection_pyautogui",
        )

    @staticmethod
    def _mode_label() -> str:
        return "code_adapter"

    def decide(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> ActionDecision:
        response = self._dispatch_chat(
            prompt,
            images=images,
            files=files,
            timeout_seconds=timeout_seconds,
        )
        provider_error = self._response_error_text(response)
        raw = response.text or provider_error or ""
        action, parse_success, local_reasoning, error = build_python_action(raw)

        llm_reasoning = self._reasoning_metadata(response)
        if local_reasoning:
            llm_reasoning = dict(llm_reasoning or {})
            llm_reasoning.update(local_reasoning)

        return ActionDecision(
            action=action,
            parse_success=parse_success,
            raw_response=raw,
            mode_requested=self._mode_label(),
            mode_used=self._mode_label(),
            adapter=self._adapter_name(response),
            llm_reasoning=llm_reasoning,
            error=None if parse_success else (provider_error or error or "failed_to_parse_python_code"),
        )
