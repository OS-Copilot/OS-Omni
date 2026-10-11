"""Reflection + ADB-command planner for Android actions."""

from __future__ import annotations

from copy import deepcopy
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from core.llm.llm_client import LLMClientManager

from platforms.android.core.runtime_types import ActionDecision

from .base_planner import BaseJsonPlanner

_FENCED_BLOCK_RE = re.compile(r"```(?:(?:bash|sh|shell|text|adb)[ \t]*\r?\n)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_FENCED_SPECIAL_RE = re.compile(r"```(?:\s*)(WAIT|DONE|FAIL)\s*```", re.IGNORECASE | re.DOTALL)
_MAX_ADB_SCRIPT_COMMANDS = 3
_DEFAULT_SCREENSHOT_VISION_LONG_EDGE = 2048.0


def extract_reflection_and_command(raw: str) -> Tuple[str, Optional[str]]:
    text = str(raw or "").strip()
    if not text:
        return "", None

    special_match = _FENCED_SPECIAL_RE.search(text)
    if special_match:
        return text[: special_match.start()].strip(), special_match.group(1).strip().upper()

    block_match = _FENCED_BLOCK_RE.search(text)
    if block_match:
        return text[: block_match.start()].strip(), block_match.group(1).strip() or None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", None
    last = lines[-1]
    if last.upper() in {"WAIT", "DONE", "FAIL"}:
        return "\n".join(lines[:-1]).strip(), last.upper()
    if last.lower().startswith("adb "):
        return "\n".join(lines[:-1]).strip(), last
    return text, None


def build_adb_action(raw: str) -> Tuple[Optional[Dict[str, Any]], bool, Optional[Dict[str, Any]], Optional[str]]:
    reflection, command = extract_reflection_and_command(raw)
    if not command:
        return None, False, None, "missing_adb_command_block"

    reasoning: Optional[Dict[str, Any]] = {"reflection": reflection} if reflection else None
    special = command.strip().upper()
    if special == "WAIT":
        return _with_reflection({"type": "wait", "ms": 1000}, reflection), True, reasoning, None
    if special == "DONE":
        return _with_reflection({"type": "success", "message": "Model declared task complete"}, reflection), True, reasoning, None
    if special == "FAIL":
        return _with_reflection({"type": "fail", "message": "Model declared task infeasible"}, reflection), True, reasoning, None

    commands, error = build_adb_script_commands(command)
    if error:
        return None, False, reasoning, error

    if len(commands) == 1 and commands[0]["type"] == "adb":
        action = {
            "type": "adb",
            "args": commands[0]["args"],
            "command": commands[0]["command"],
        }
    else:
        action = {
            "type": "adb_script",
            "commands": commands,
        }
    return _with_reflection(action, reflection), True, reasoning, None


def build_adb_script_commands(command: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    commands: List[Dict[str, Any]] = []
    lines = list(_command_lines(command))
    if sum(_parse_sleep_seconds(line) is None for line in lines) > _MAX_ADB_SCRIPT_COMMANDS or len(lines) > 6:
        return None, 'too_many_script_commands'
    for line in lines:
        sleep_seconds = _parse_sleep_seconds(line)
        if sleep_seconds is not None:
            commands.append({"type": "sleep", "seconds": sleep_seconds, "command": line})
            continue

        try:
            tokens = shlex.split(line, posix=False)
        except ValueError as exc:
            return None, f"adb_command_parse_error: {exc}"

        adb_args, error = normalize_adb_command(tokens)
        if error:
            return None, error
        commands.append({"type": "adb", "args": adb_args, "command": line})


    if not commands:
        return None, "empty_adb_command"
    return commands, None


def scale_screenshot_only_adb_coordinates(
    action: Dict[str, Any],
    *,
    screen_width: int,
    screen_height: int,
    vision_long_edge: float = _DEFAULT_SCREENSHOT_VISION_LONG_EDGE,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Upscale adb input coordinates emitted against a resized screenshot.

    Some vision adapters appear to reason over screenshots resized to a 2048px
    long edge while still emitting pixel coordinates. Android ADB needs device
    pixels, so this helper scales only tap/swipe adb input coordinates back up.
    """

    width = int(screen_width or 0)
    height = int(screen_height or 0)
    long_edge = float(vision_long_edge or 0.0)
    device_long_edge = max(width, height)
    if width <= 0 or height <= 0 or long_edge <= 0 or device_long_edge <= long_edge:
        return action, None

    scale = device_long_edge / long_edge
    transformed = deepcopy(action)
    changed_commands = 0

    if transformed.get("type") == "adb":
        changed_commands += _scale_adb_command_in_place(
            transformed,
            scale=scale,
            screen_width=width,
            screen_height=height,
        )
    elif transformed.get("type") == "adb_script":
        commands = transformed.get("commands")
        if isinstance(commands, list):
            for command in commands:
                if isinstance(command, dict):
                    changed_commands += _scale_adb_command_in_place(
                        command,
                        scale=scale,
                        screen_width=width,
                        screen_height=height,
                    )

    if changed_commands <= 0:
        return action, None

    metadata = {
        "type": "screenshot_only_adb_coordinate_upscale",
        "scale": scale,
        "screen_width": width,
        "screen_height": height,
        "vision_long_edge": long_edge,
        "commands_changed": changed_commands,
    }
    transformed["_coordinate_transform"] = metadata
    return transformed, metadata


def normalize_adb_command(tokens: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    if not tokens:
        return None, "empty_adb_command"

    tokens = [token.strip("\"'") for token in tokens if str(token).strip()]
    if not tokens:
        return None, "empty_adb_command"

    if tokens[0].lower().endswith("adb") or tokens[0].lower().endswith("adb.exe"):
        tokens = tokens[1:]
    elif tokens[0].lower() == "adb":
        tokens = tokens[1:]
    else:
        return None, "adb_command_must_start_with_adb"

    if len(tokens) >= 2 and tokens[0] == "-s":
        tokens = tokens[2:]

    if not _is_allowed_adb_args(tokens):
        return None, f"unsupported_or_unsafe_adb_command: {' '.join(tokens)}"
    return tokens, None


def _scale_adb_command_in_place(
    command: Dict[str, Any],
    *,
    scale: float,
    screen_width: int,
    screen_height: int,
) -> int:
    args = command.get("args")
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        return 0
    if len(args) >= 5 and args[:3] == ["shell", "input", "tap"]:
        scaled = _scaled_input_args(args, indices=(3, 4), scale=scale, screen_width=screen_width, screen_height=screen_height)
    elif len(args) >= 7 and args[:3] == ["shell", "input", "swipe"]:
        scaled = _scaled_input_args(args, indices=(3, 4, 5, 6), scale=scale, screen_width=screen_width, screen_height=screen_height)
    else:
        return 0

    if scaled == args:
        return 0
    command["original_args"] = list(args)
    if "command" in command:
        command["original_command"] = command.get("command")
    command["args"] = scaled
    command["command"] = "adb " + " ".join(scaled)
    return 1


def _scaled_input_args(
    args: List[str],
    *,
    indices: Tuple[int, ...],
    scale: float,
    screen_width: int,
    screen_height: int,
) -> List[str]:
    scaled = list(args)
    for offset, index in enumerate(indices):
        value = _parse_number_token(args[index])
        if value is None:
            return args
        limit = screen_width if offset % 2 == 0 else screen_height
        scaled[index] = str(_clamp(round(value * scale), 0, max(limit - 1, 0)))
    return scaled


def _parse_number_token(raw: str) -> Optional[float]:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(int(value), upper))


def _command_lines(command: str) -> List[str]:
    lines: List[str] = []
    for raw_line in str(command or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _parse_sleep_seconds(line: str) -> Optional[float]:
    stripped = str(line or "").strip()
    match = re.fullmatch(r"(?:sleep|time\.sleep)\s*\(?\s*([0-9]+(?:\.[0-9]+)?)\s*\)?", stripped)
    if not match:
        return None
    seconds = float(match.group(1))
    return max(0.0, min(seconds, 5.0))


def _is_allowed_adb_args(args: List[str]) -> bool:
    if not args:
        return False
    if args[:2] == ["shell", "input"] and len(args) >= 3:
        return args[2] in {"tap", "swipe", "text", "keyevent"}
    if args[:2] == ["shell", "monkey"]:
        return "-p" in args and "1" in args[-2:]
    return False


def _with_reflection(action: Dict[str, Any], reflection: str) -> Dict[str, Any]:
    if reflection:
        action = dict(action)
        action["reflection"] = reflection
    return action


class ReflectionAdbPlanner(BaseJsonPlanner):
    """Action planner for Android reflection + adb command mode."""

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
            adapter_prefix="reflection_adb",
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
        action, parse_success, local_reasoning, error = build_adb_action(raw)

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
            error=None if parse_success else (provider_error or error or "failed_to_parse_reflection_adb_action"),
        )
