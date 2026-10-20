"""Windows reflection + pyautogui-code planner backed by shared LLMSession."""

from __future__ import annotations

import os
import re
import ast
import textwrap
from typing import Any, Dict, List, Optional, Tuple

from core.llm.llm_client import LLMClientManager

from platforms.windows.core.runtime_types import ActionDecision

from .base_planner import BaseJsonPlanner

_CODE_BLOCK_RE = re.compile(r"```python\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_FENCED_SPECIAL_RE = re.compile(r"```(?:\s*)(WAIT|DONE|FAIL)\s*```", re.IGNORECASE | re.DOTALL)
_GENERIC_CODE_BLOCK_RE = re.compile(r"```(?:[A-Za-z_+-]+)?\s*(.*?)\s*```", re.DOTALL)
_DEFAULT_ACTION_TIMEOUT_SECONDS = 120
_TERMINAL_APP_TEXT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:cmd(?:\.exe)?|powershell(?:\.exe)?|pwsh(?:\.exe)?|wt(?:\.exe)?|windows\s+terminal)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_SHELL_EXECUTION_CALLS = {
    "os.system",
    "os.popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "subprocess.run",
    "startfile",
    "os.startfile",
}
_BLENDER_CONSOLE_HOTKEYS = {
    ("shift", "f4"),
    ("f4", "shift"),
}


def _reflection_action_timeout_seconds() -> int:
    raw = os.environ.get("HELLOWORLD_REFLECTION_PYAUTOGUI_ACTION_TIMEOUT_SECONDS")
    if not raw:
        return _DEFAULT_ACTION_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_ACTION_TIMEOUT_SECONDS
    return max(1, value)


def _split_code_semicolons(line: str) -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    escaped = False

    for index, char in enumerate(line):
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote:
            current.append(char)
            escaped = True
            continue
        if char in {"'", '"'}:
            current.append(char)
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            continue
        if char == "#" and quote is None:
            # A comment runs to the end of the line; semicolons in it do not split statements.
            current.append(line[index:])
            break
        if char == ";" and quote is None:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)

    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _normalize_osworld_code(code: str) -> str:
    normalized: List[str] = []
    dedented = textwrap.dedent(str(code)).strip("\n")
    for raw_line in dedented.splitlines():
        if not raw_line.strip():
            continue
        indent_len = len(raw_line) - len(raw_line.lstrip())
        indent = raw_line[:indent_len]
        body = raw_line.strip()
        if body.startswith("#"):
            normalized.append(f"{indent}{body}")
            continue
        normalized.extend(f"{indent}{part}" for part in _split_code_semicolons(body))
    return "\n".join(normalized).strip()


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


def _string_literals_from_code(code: str) -> List[str]:
    try:
        tree = ast.parse(str(code or ""))
    except SyntaxError:
        return []
    values: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
    return values


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _blender_hotkey_policy_error(code: str) -> Optional[str]:
    try:
        tree = ast.parse(str(code or ""))
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func).lower()
        if call_name not in {"pyautogui.hotkey", "hotkey"}:
            continue
        keys = tuple(
            str(arg.value).strip().lower()
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        )
        if keys in _BLENDER_CONSOLE_HOTKEYS:
            return "blender_hotkey_policy: use Blender editor-type selector instead of Shift+F4"
    return None


def _terminal_policy_error(code: str) -> Optional[str]:
    try:
        tree = ast.parse(str(code or ""))
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported = [alias.name.split(".", 1)[0].lower() for alias in getattr(node, "names", [])]
            module = str(getattr(node, "module", "") or "").split(".", 1)[0].lower()
            if "subprocess" in imported or module == "subprocess":
                return "terminal_policy: subprocess is forbidden in benchmark actions"
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func)
        if call_name in _SHELL_EXECUTION_CALLS:
            return f"terminal_policy: shell execution via {call_name} is forbidden"
        if call_name.lower() in {"pyautogui.write", "pyautogui.typewrite", "write", "typewrite"}:
            for literal in _string_literals_from_code(ast.unparse(node) if hasattr(ast, "unparse") else code):
                if _TERMINAL_APP_TEXT_RE.search(literal):
                    return "terminal_policy: opening cmd/PowerShell/Windows Terminal from a task is forbidden"

    for literal in _string_literals_from_code(code):
        if _TERMINAL_APP_TEXT_RE.search(literal):
            return "terminal_policy: cmd/PowerShell/Windows Terminal text is forbidden in benchmark actions"
    return None


def validate_pyautogui_code(code: str, *, task_id: str | None = None) -> Tuple[bool, Optional[str]]:
    try:
        compile(str(code or ""), "<windows_reflection_pyautogui_action>", "exec")
    except SyntaxError as exc:
        location = f"line {exc.lineno}" if exc.lineno else "unknown line"
        return False, f"syntax_error at {location}: {exc.msg}"
    policy_error = _terminal_policy_error(code)
    if policy_error:
        return False, policy_error
    if str(task_id or "").strip().lower().startswith("windows.blender."):
        policy_error = _blender_hotkey_policy_error(code)
        if policy_error:
            return False, policy_error
    return True, None


def build_python_action(
    raw: str,
    *,
    task_id: str | None = None,
) -> Tuple[Optional[Dict[str, Any]], bool, Optional[Dict[str, Any]], Optional[str]]:
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
        return {"type": "wait", "ms": 1000, **({"reflection": reflection} if reflection else {})}, True, reasoning, None
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
    valid, validation_error = validate_pyautogui_code(normalized_code, task_id=task_id)
    if not valid:
        return None, False, reasoning, validation_error
    action = {
        "type": "python_code",
        "language": "python",
        "code": normalized_code,
        "timeout_seconds": _reflection_action_timeout_seconds(),
    }
    if reflection:
        action["reflection"] = reflection
    return action, True, reasoning, None


class ReflectionPyAutoGUIPlanner(BaseJsonPlanner):
    """Windows action planner for reflection + python-code mode."""

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
            adapter_prefix="windows_reflection_pyautogui",
        )
        self.task_id = str((session_metadata or {}).get("task_id") or "").strip()

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
        action, parse_success, local_reasoning, error = build_python_action(raw, task_id=self.task_id)

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
