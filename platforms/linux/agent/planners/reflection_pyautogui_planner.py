"""Reflection + pyautogui-code planner backed by shared LLMSession."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from core.llm.llm_client import LLMClientManager

from platforms.linux.core.runtime_types import ActionDecision

from .base_planner import BaseJsonPlanner

_CODE_BLOCK_RE = re.compile(r"```python\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_FENCED_SPECIAL_RE = re.compile(r"```(?:\s*)(WAIT|DONE|FAIL)\s*```", re.IGNORECASE | re.DOTALL)
_GENERIC_CODE_BLOCK_RE = re.compile(r"```(?:[A-Za-z_+-]+)?\s*(.*?)\s*```", re.DOTALL)


def _normalize_osworld_code(code: str) -> str:
    return str(code).strip()


def extract_reflection_and_code(raw: str) -> Tuple[str, Optional[str]]:
    text = str(raw or "").strip()
    if not text:
        return "", None
    match = _CODE_BLOCK_RE.search(text)
    if match:
        reflection = text[: match.start()].strip()
        code = _normalize_osworld_code(match.group(1))
        return reflection, code or None
    special_match = _FENCED_SPECIAL_RE.search(text)
    if special_match:
        reflection = text[: special_match.start()].strip()
        return reflection, special_match.group(1).strip().upper()
    generic_match = _GENERIC_CODE_BLOCK_RE.search(text)
    if generic_match:
        reflection = text[: generic_match.start()].strip()
        code = _normalize_osworld_code(generic_match.group(1))
        return reflection, code or None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", None
    last = lines[-1].upper()
    if last in {"WAIT", "DONE", "FAIL"}:
        reflection = "\n".join(lines[:-1]).strip()
        return reflection, last
    if text.upper() in {"WAIT", "DONE", "FAIL"}:
        return "", text.upper()
    return text, None


def validate_pyautogui_code(code: str) -> Tuple[bool, Optional[str]]:
    try:
        compile(str(code or ""), "<reflection_pyautogui_action>", "exec")
    except SyntaxError as exc:
        location = f"line {exc.lineno}" if exc.lineno else "unknown line"
        return False, f"syntax_error at {location}: {exc.msg}"
    return True, None


def build_python_action(raw: str) -> Tuple[Optional[Dict[str, Any]], bool, Optional[Dict[str, Any]], Optional[str]]:
    reflection, code = extract_reflection_and_code(raw)
    if not code:
        return None, False, None, "missing_python_code_block"

    reasoning: Optional[Dict[str, Any]] = None
    if reflection:
        reasoning = {"reflection": reflection}

    special = code.strip().upper()
    if special not in {"WAIT", "DONE", "FAIL"}:
        code_lines = [line.strip() for line in code.splitlines() if line.strip()]
        executable_lines = [line for line in code_lines if not line.startswith("#")]
        if executable_lines and executable_lines[-1].upper() in {"WAIT", "DONE", "FAIL"}:
            special = executable_lines[-1].upper()
            comment_reflection = "\n".join(line.lstrip("#").strip() for line in code_lines if line.startswith("#")).strip()
            if comment_reflection:
                reflection = "\n".join(part for part in [reflection, comment_reflection] if part).strip()
                reasoning = {"reflection": reflection}
    if special == "WAIT":
        return {
            "type": "wait",
            "ms": 1000,
            **({"reflection": reflection} if reflection else {}),
        }, True, reasoning, None
    if special == "DONE":
        return {
            "type": "success",
            "message": "Model declared task complete",
            **({"reflection": reflection} if reflection else {}),
        }, True, reasoning, None
    if special == "FAIL":
        return {
            "type": "fail",
            "reason": "Model declared task infeasible",
            **({"reflection": reflection} if reflection else {}),
        }, True, reasoning, None

    normalized_code = _normalize_osworld_code(code)
    valid, validation_error = validate_pyautogui_code(normalized_code)
    if not valid:
        return None, False, reasoning, validation_error
    action = {
        "type": "python_code",
        "language": "python",
        "code": normalized_code,
        "timeout_seconds": 120,
    }
    if reflection:
        action["reflection"] = reflection
    return action, True, reasoning, None


class ReflectionPyAutoGUIPlanner(BaseJsonPlanner):
    """Action planner for reflection + python-code mode."""

    def __init__(
        self,
        llm_client: LLMClientManager,
        model_id: str,
        system_prompt: str,
        history_window: Optional[int] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            llm_client,
            model_id,
            system_prompt,
            history_window=history_window,
            session_metadata=session_metadata,
            adapter_prefix="code_adapter",
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
