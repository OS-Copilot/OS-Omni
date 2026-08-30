#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import Flask, Response, jsonify, request, send_file
from PIL import Image
from urllib.request import urlopen

# Loaded in main() after DISPLAY is ready. Importing at module load can fail in
# Xvfb-driven office runs when the shell environment has not finished wiring
# DISPLAY / Xauthority yet.
pyautogui: Any = None
_PYAUTOGUI_IMPORT_ERROR: Optional[str] = None

try:  # pragma: no cover - optional guest dependency
    import pyatspi
    from pyatspi import Accessible, Component, StateType, Text as ATText
except Exception:  # pragma: no cover - runtime may operate in degraded mode
    pyatspi = None
    Accessible = Any
    Component = Any
    StateType = None
    ATText = Any


app = Flask(__name__)
logger = app.logger

def _try_import_pyautogui() -> None:
    global pyautogui, _PYAUTOGUI_IMPORT_ERROR
    try:
        import pyautogui as _pg

        pyautogui = _pg
        pyautogui.PAUSE = 0
        pyautogui.FAILSAFE = False
        _PYAUTOGUI_IMPORT_ERROR = None
    except Exception as exc:  # pragma: no cover - runtime may operate in degraded mode
        pyautogui = None
        _PYAUTOGUI_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

RUNTIME_TOKEN = "linuxbench-runtime-token"
MAX_UI_NODES = 220
MAX_CHILDREN_PER_NODE = 256

INTERACTIVE_ROLES = {
    "push button",
    "toggle button",
    "check box",
    "check menu item",
    "radio button",
    "radio menu item",
    "menu item",
    "page tab",
    "combo box",
    "list item",
    "entry",
    "password text",
    "text",
    "terminal",
    "document web",
    "document text",
    "table cell",
    "icon",
    "link",
    "slider",
    "scroll bar",
    "spin button",
}

ACTION_SCHEMA = {
    "tap": {
        "description": "Click at the specified element or position",
        "parameters": {
            "target": {
                "type": "string|array|object",
                "required": True,
                "description": "Target: node ID, pixel coords [x, y], or normalized coords {'x':0.5,'y':0.5}",
            }
        },
    },
    "double_tap": {
        "description": "Double-click at the specified element or position",
        "parameters": {
            "target": {
                "type": "string|array|object",
                "required": True,
                "description": "Target: node ID, pixel coords [x, y], or normalized coords",
            }
        },
    },
    "right_click": {
        "description": "Right-click at the specified element or position",
        "parameters": {
            "target": {
                "type": "string|array|object",
                "required": True,
                "description": "Target: node ID, pixel coords [x, y], or normalized coords",
            }
        },
    },
    "drag": {
        "description": "Drag from one position to another",
        "parameters": {
            "from_target": {
                "type": "string|array|object",
                "required": True,
                "description": "Drag start: node ID, pixel coords [x, y], or normalized coords",
            },
            "to_target": {
                "type": "string|array|object",
                "required": True,
                "description": "Drag end: node ID, pixel coords [x, y], or normalized coords",
            },
            "duration_ms": {
                "type": "integer",
                "required": False,
                "default": 400,
                "description": "Approximate drag duration in milliseconds",
            },
        },
    },
    "scroll": {
        "description": "Scroll in one direction",
        "parameters": {
            "direction": {
                "type": "string",
                "required": True,
                "enum": ["up", "down", "left", "right"],
                "description": "Scroll direction",
            },
            "distance": {
                "type": "integer|number",
                "required": False,
                "default": 300,
                "description": "Scroll amount. For vertical/horizontal scroll wheel calls.",
            },
            "target": {
                "type": "string|array|object",
                "required": False,
                "description": "Optional position to move cursor to before scrolling",
            },
        },
    },
    "type_text": {
        "description": "Type text, optionally after clicking a target",
        "parameters": {
            "text": {"type": "string", "required": True, "description": "Text to input"},
            "target": {
                "type": "string|array|object",
                "required": False,
                "description": "Optional target to focus before typing",
            },
            "clear_first": {
                "type": "boolean",
                "required": False,
                "default": False,
                "description": "Whether to clear current field before typing",
            },
        },
    },
    "keyboard": {
        "description": "Press a single keyboard action",
        "parameters": {
            "action": {
                "type": "string",
                "required": True,
                "enum": ["enter", "escape", "backspace", "delete", "tab", "space", "up", "down", "left", "right"],
                "description": "Key to press",
            },
            "count": {
                "type": "integer",
                "required": False,
                "default": 1,
                "description": "Number of repeated presses",
            },
        },
    },
    "hotkey": {
        "description": "Press a keyboard shortcut like ctrl+c",
        "parameters": {
            "keys": {
                "type": "array",
                "required": True,
                "description": "Shortcut keys such as ['ctrl', 'c']",
            }
        },
    },
    "launch_app": {
        "description": "Launch a Linux desktop app or shell command",
        "parameters": {
            "app_name": {
                "type": "string",
                "required": True,
                "description": "App command or desktop id such as 'gnome-terminal' or 'org.gnome.Nautilus.desktop'",
            }
        },
    },
    "run_bash": {
        "description": "Run a bash script synchronously and wait for it to finish",
        "parameters": {
            "script": {
                "type": "string",
                "required": True,
                "description": "Bash script to execute",
            },
            "timeout_ms": {
                "type": "integer",
                "required": False,
                "default": 120000,
                "description": "Maximum runtime in milliseconds",
            },
        },
    },
    "wait": {
        "description": "Wait for a specified time",
        "parameters": {
            "ms": {
                "type": "integer",
                "required": False,
                "default": 1000,
                "description": "Wait duration in milliseconds",
            }
        },
    },
    "success": {
        "description": "Task successfully completed",
        "parameters": {
            "message": {"type": "string", "required": False, "description": "Success message"}
        },
    },
    "fail": {
        "description": "Task could not be completed",
        "parameters": {
            "reason": {"type": "string", "required": True, "description": "Failure reason"}
        },
    },
}


def _require_auth() -> Optional[Response]:
    expected = str(RUNTIME_TOKEN or "").strip()
    if not expected:
        return None
    header = request.headers.get("Authorization", "")
    if header == f"Bearer {expected}":
        return None
    return jsonify({"error": "unauthorized"}), 401


@app.before_request
def _check_auth() -> Optional[Response]:
    if (request.path or "") in ("/health",):
        return None
    return _require_auth()


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _screen_size() -> tuple[int, int]:
    if pyautogui is not None:
        try:
            width, height = pyautogui.size()
            return int(width), int(height)
        except Exception:
            pass

    candidates = [
        ["/bin/bash", "-lc", "xrandr --current 2>/dev/null | awk '/\\*/ {print $1; exit}'"],
        ["/bin/bash", "-lc", "xprop -root _NET_DESKTOP_GEOMETRY 2>/dev/null | awk -F' = ' '{print $2}'"],
    ]
    for command in candidates:
        raw = _run_text(command)
        match = re.search(r"(\d+)\s*x\s*(\d+)", raw)
        if match:
            return int(match.group(1)), int(match.group(2))

    return 1920, 1080


def _run_text(command: List[str]) -> str:
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
        return result.stdout.strip()
    except Exception:
        return ""


def _foreground_window_info() -> tuple[str, str]:
    if _run_text(["/bin/bash", "-lc", "command -v xdotool >/dev/null 2>&1 && echo yes"]) == "yes":
        title = _run_text(["xdotool", "getwindowfocus", "getwindowname"])
        wm_class_raw = _run_text(
            ["/bin/bash", "-lc", "xprop -id $(xdotool getwindowfocus) WM_CLASS 2>/dev/null || true"]
        )
        matches = re.findall(r'"([^"]+)"', wm_class_raw)
        app_name = matches[-1] if matches else ""
        return app_name, title

    active_window_raw = _run_text(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    window_match = re.search(r"(0x[0-9a-fA-F]+)", active_window_raw)
    if not window_match:
        return "", ""

    window_id = window_match.group(1)
    title = _run_text(["xprop", "-id", window_id, "_NET_WM_NAME"])
    if title:
        title = title.split(" = ", 1)[-1].strip().strip('"')
    wm_class_raw = _run_text(["xprop", "-id", window_id, "WM_CLASS"])
    matches = re.findall(r'"([^"]+)"', wm_class_raw)
    app_name = matches[-1] if matches else ""
    return app_name, title


def _normalize_state_names(node: Accessible) -> set[str]:
    names: set[str] = set()
    if pyatspi is None or StateType is None:
        return names
    try:
        for state in node.getState().get_states():
            raw = StateType._enum_lookup.get(state, "")
            if raw.startswith("STATE_"):
                names.add(raw.split("_", 1)[1].lower())
    except Exception:
        pass
    return names


def _get_rect(node: Accessible) -> Optional[dict[str, float]]:
    if pyatspi is None:
        return None
    try:
        component: Component = node.queryComponent()
        x, y, w, h = component.getExtents(pyatspi.XY_SCREEN)
        rect = {"x": float(x), "y": float(y), "w": float(w), "h": float(h)}
        if rect["w"] <= 0 or rect["h"] <= 0:
            return None
        return rect
    except Exception:
        return None


def _get_text(node: Accessible) -> str:
    text_chunks: list[str] = []
    if pyatspi is None:
        name = str(getattr(node, "name", "") or "").strip()
        return name
    try:
        text_obj: ATText = node.queryText()
        raw = text_obj.getText(0, text_obj.characterCount)
        raw = raw.replace("\ufffc", "").replace("\ufffd", "").strip()
        if raw:
            text_chunks.append(raw)
    except Exception:
        pass

    name = str(getattr(node, "name", "") or "").strip()
    if name and name not in text_chunks:
        text_chunks.append(name)

    return "\n".join(text_chunks).strip()


def _slug_role(role: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", (role or "").strip().lower()).strip("_")
    return normalized or "unknown"


def _iter_children(node: Accessible) -> Iterable[Accessible]:
    try:
        for index, child in enumerate(node):
            if index >= MAX_CHILDREN_PER_NODE:
                break
            yield child
    except Exception:
        return


def _should_keep_node(role: str, text: str, states: set[str], rect: Optional[dict[str, float]]) -> bool:
    if "showing" not in states and "visible" not in states and role not in {"application", "frame"}:
        return False
    if rect is None and not text and role not in {"application", "frame"}:
        return False
    if role in INTERACTIVE_ROLES:
        return True
    if text:
        return True
    if role in {"application", "frame", "dialog", "window", "alert"}:
        return True
    return False


def _collect_ui_nodes() -> tuple[list[dict[str, Any]], str, str]:
    foreground_app, foreground_window = _foreground_window_info()
    if pyatspi is None:
        return [], foreground_app, foreground_window

    desktop = pyatspi.Registry.getDesktop(0)
    width, height = _screen_size()
    nodes: list[dict[str, Any]] = []
    node_index = 0
    active_app_candidates: set[str] = set()

    stack: list[Accessible] = [desktop]
    while stack and len(nodes) < MAX_UI_NODES:
        node = stack.pop()
        children = list(_iter_children(node))
        for child in reversed(children):
            stack.append(child)

        role = str(node.getRoleName() or "").strip().lower()
        if role == "desktop frame":
            continue

        states = _normalize_state_names(node)
        rect = _get_rect(node)
        text = _get_text(node)
        name = str(getattr(node, "name", "") or "").strip()

        if role == "application" and "active" in states and name:
            active_app_candidates.add(name)

        if not _should_keep_node(role, text, states, rect):
            continue

        item: dict[str, Any] = {"id": f"n{node_index}", "type": _slug_role(role)}
        if text:
            item["text"] = text
        if name:
            item["selector"] = name
        if rect is not None:
            item["rect"] = rect
            cx = int(rect["x"] + rect["w"] / 2)
            cy = int(rect["y"] + rect["h"] / 2)
            item["tap"] = [cx, cy]
            if width > 0 and height > 0:
                item["tap_norm"] = [round(cx / width, 4), round(cy / height, 4)]
        item["enabled"] = "enabled" in states or "sensitive" in states or not states
        if "focused" in states:
            item["focused"] = True
        if "active" in states:
            item["active"] = True
        item["accessible"] = True
        nodes.append(item)
        node_index += 1

    if not foreground_app and active_app_candidates:
        foreground_app = sorted(active_app_candidates)[0]

    return nodes, foreground_app, foreground_window


def _png_mean_rgb(data: bytes) -> Optional[float]:
    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        image.thumbnail((160, 90))
        pixels = list(image.getdata())
        if not pixels:
            return None
        total = sum(r + g + b for r, g, b in pixels)
        return total / (len(pixels) * 3.0)
    except Exception:
        return None


def _is_mostly_black_png(data: bytes, mean_threshold: float = 4.0) -> bool:
    mean = _png_mean_rgb(data)
    if mean is None:
        return True
    return mean < mean_threshold


def _screenshot_linux_x11_bytes() -> Optional[bytes]:
    display = (os.environ.get("DISPLAY") or "").strip()
    if not display:
        return None

    collected: list[tuple[str, bytes]] = []

    def take(label: str, data: Optional[bytes]) -> None:
        if data and len(data) > 100:
            collected.append((label, data))

    try:
        from PIL import ImageGrab

        image = ImageGrab.grab(xdisplay=display)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        take("pillow_xcb", buffer.getvalue())
    except Exception:
        pass

    xwd_bin = shutil.which("xwd")
    magick_bin = shutil.which("magick") or shutil.which("convert")
    if xwd_bin and magick_bin:
        try:
            xwd_out = subprocess.run(
                [xwd_bin, "-root", "-silent"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=12,
                check=True,
                env=os.environ,
            )
            if xwd_out.stdout:
                png_out = subprocess.run(
                    [magick_bin, "xwd:-", "png:-"],
                    input=xwd_out.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=15,
                    check=True,
                )
                take("xwd_magick", png_out.stdout)
        except Exception:
            pass

    scrot_bin = shutil.which("scrot")
    if scrot_bin:
        try:
            scrot_out = subprocess.run(
                [scrot_bin, "-z", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=12,
                check=True,
                env=os.environ,
            )
            take("scrot", scrot_out.stdout)
        except Exception:
            pass

    import_bin = shutil.which("import")
    if import_bin:
        try:
            import_out = subprocess.run(
                [import_bin, "-window", "root", "png:-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=12,
                check=True,
                env=os.environ,
            )
            take("import", import_out.stdout)
        except Exception:
            pass

    for label, payload in collected:
        if not _is_mostly_black_png(payload):
            return payload

    if collected:
        logger.warning(
            "screenshot: all Linux backends returned near-black image; DISPLAY=%s backends=%s",
            display,
            [item[0] for item in collected],
        )
        return collected[0][1]
    return None


def _screenshot_bytes() -> bytes:
    if sys.platform.startswith("linux"):
        direct = _screenshot_linux_x11_bytes()
        if direct:
            return direct

    if pyautogui is not None:
        try:
            image = pyautogui.screenshot()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            raw = buffer.getvalue()
            if sys.platform.startswith("linux") and _is_mostly_black_png(raw):
                logger.warning(
                    "screenshot: pyautogui result is near-black; DISPLAY=%s",
                    os.environ.get("DISPLAY"),
                )
            return raw
        except Exception:
            pass

    if not sys.platform.startswith("linux"):
        try:
            result = subprocess.run(
                ["import", "-window", "root", "png:-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=True,
                env=os.environ,
            )
            if result.stdout:
                return result.stdout
        except Exception:
            pass

    width, height = _screen_size()
    logger.warning(
        "screenshot: using solid fallback; DISPLAY=%s",
        os.environ.get("DISPLAY"),
    )
    fallback = Image.new("RGB", (max(1, width), max(1, height)), color=(32, 32, 32))
    buffer = io.BytesIO()
    fallback.save(buffer, format="PNG")
    return buffer.getvalue()


def _require_pointer_backend(action_type: str) -> None:
    if pyautogui is None:
        raise RuntimeError(
            f"Action '{action_type}' requires pyautogui in the guest environment. "
            "Install platforms/linux/guest/requirements.txt for interactive control."
        )


def _normalized_to_pixels(x: Any, y: Any, width: int, height: int) -> tuple[int, int]:
    px = float(x) * width
    py = float(y) * height
    max_x = max(0, width - 1)
    max_y = max(0, height - 1)
    return max(0, min(int(px), max_x)), max(0, min(int(py), max_y))


def _parse_target(target: Any, ui_nodes: list[dict[str, Any]]) -> tuple[int, int]:
    width, height = _screen_size()
    if isinstance(target, str):
        for node in ui_nodes:
            if node.get("id") == target:
                tap = node.get("tap")
                if isinstance(tap, list) and len(tap) == 2:
                    return int(tap[0]), int(tap[1])
                rect = node.get("rect") or {}
                return (
                    int(float(rect.get("x", 0)) + float(rect.get("w", 0)) / 2),
                    int(float(rect.get("y", 0)) + float(rect.get("h", 0)) / 2),
                )
        raise ValueError(f"Node not found: {target}")
    if isinstance(target, (list, tuple)) and len(target) == 2:
        x = float(target[0])
        y = float(target[1])
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            return _normalized_to_pixels(x, y, width, height)
        return int(x), int(y)
    if isinstance(target, dict) and "x" in target and "y" in target:
        return _normalized_to_pixels(target["x"], target["y"], width, height)
    raise ValueError(f"Unsupported target: {target!r}")


def _launch_app_command(app_name: str) -> None:
    app_name = str(app_name or "").strip()
    if not app_name:
        raise ValueError("app_name is required")
    if app_name.endswith(".desktop"):
        subprocess.Popen(["gtk-launch", app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    subprocess.Popen(
        ["/bin/bash", "-lc", f"setsid -f {app_name} >/dev/null 2>&1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _execute_action(action: dict[str, Any], ui_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    action_type = str(action.get("type") or "").strip()
    if not action_type:
        raise ValueError("action.type is required")

    if action_type == "tap":
        _require_pointer_backend(action_type)
        x, y = _parse_target(action.get("target"), ui_nodes)
        pyautogui.click(x=x, y=y)
        return {"success": True, "message": f"Clicked at ({x}, {y})", "terminal": False}

    if action_type == "double_tap":
        _require_pointer_backend(action_type)
        x, y = _parse_target(action.get("target"), ui_nodes)
        pyautogui.doubleClick(x=x, y=y)
        return {"success": True, "message": f"Double-clicked at ({x}, {y})", "terminal": False}

    if action_type == "right_click":
        _require_pointer_backend(action_type)
        x, y = _parse_target(action.get("target"), ui_nodes)
        pyautogui.rightClick(x=x, y=y)
        return {"success": True, "message": f"Right-clicked at ({x}, {y})", "terminal": False}

    if action_type == "drag":
        _require_pointer_backend(action_type)
        from_x, from_y = _parse_target(action.get("from_target"), ui_nodes)
        to_x, to_y = _parse_target(action.get("to_target"), ui_nodes)
        duration = max(0.1, float(action.get("duration_ms", 400)) / 1000.0)
        pyautogui.moveTo(from_x, from_y)
        pyautogui.dragTo(to_x, to_y, duration=duration, button="left")
        return {"success": True, "message": f"Dragged to ({to_x}, {to_y})", "terminal": False}

    if action_type == "scroll":
        _require_pointer_backend(action_type)
        target = action.get("target")
        if target is not None:
            x, y = _parse_target(target, ui_nodes)
            pyautogui.moveTo(x, y)
        amount = int(float(action.get("distance", 300)))
        direction = str(action.get("direction", "down")).lower()
        if direction == "up":
            pyautogui.scroll(amount)
        elif direction == "down":
            pyautogui.scroll(-amount)
        elif direction == "left":
            pyautogui.hscroll(-amount)
        elif direction == "right":
            pyautogui.hscroll(amount)
        else:
            raise ValueError(f"Unknown scroll direction: {direction}")
        return {"success": True, "message": f"Scrolled {direction}", "terminal": False}

    if action_type == "type_text":
        _require_pointer_backend(action_type)
        target = action.get("target")
        if target is not None:
            x, y = _parse_target(target, ui_nodes)
            pyautogui.click(x=x, y=y)
            time.sleep(0.1)
        if action.get("clear_first"):
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("backspace")
        text = str(action.get("text") or "")
        if not text:
            raise ValueError("type_text.text is required")
        pyautogui.write(text, interval=0.01)
        return {"success": True, "message": f"Typed {len(text)} chars", "terminal": False}

    if action_type == "keyboard":
        _require_pointer_backend(action_type)
        action_name = str(action.get("action") or "").strip().lower()
        if not action_name:
            raise ValueError("keyboard.action is required")
        key_map = {
            "enter": "enter",
            "escape": "esc",
            "backspace": "backspace",
            "delete": "delete",
            "tab": "tab",
            "space": "space",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
        }
        key = key_map.get(action_name)
        if not key:
            raise ValueError(f"Unknown keyboard action: {action_name}")
        count = max(1, int(action.get("count", 1)))
        for _ in range(count):
            pyautogui.press(key)
        return {"success": True, "message": f"Pressed {action_name} x{count}", "terminal": False}

    if action_type == "hotkey":
        _require_pointer_backend(action_type)
        keys = action.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ValueError("hotkey.keys must be a non-empty list")
        pyautogui.hotkey(*[str(key) for key in keys])
        return {"success": True, "message": f"Pressed hotkey {'+'.join(map(str, keys))}", "terminal": False}

    if action_type == "launch_app":
        app_name = str(action.get("app_name") or "").strip()
        _launch_app_command(app_name)
        return {"success": True, "message": f"Launched {app_name}", "terminal": False}

    if action_type == "run_bash":
        script = str(action.get("script") or "").strip()
        if not script:
            raise ValueError("run_bash.script is required")
        timeout_ms = max(1, int(action.get("timeout_ms", 120000)))
        result = _run_subprocess(["/bin/bash", "-lc", script], shell=False, timeout=max(1, timeout_ms // 1000))
        message = result.stdout.strip() or result.stderr.strip() or "Bash script completed"
        return {"success": result.returncode == 0, "message": message, "terminal": False}

    if action_type == "wait":
        ms = max(0, int(action.get("ms", 1000)))
        time.sleep(ms / 1000.0)
        return {"success": True, "message": f"Waited {ms}ms", "terminal": False}

    if action_type == "success":
        return {"success": True, "message": str(action.get("message") or "Task completed"), "terminal": True}

    if action_type == "fail":
        return {"success": False, "message": str(action.get("reason") or "Task failed"), "terminal": True}

    raise ValueError(f"Unsupported action type: {action_type}")


def _action_schema_text() -> str:
    lines = ["# Available Actions", ""]
    for name, schema in ACTION_SCHEMA.items():
        lines.append(f"## {name}")
        lines.append(schema["description"])
        params = schema.get("parameters", {})
        if params:
            lines.append("**Parameters:**")
            for param_name, info in params.items():
                required = "required" if info.get("required") else "optional"
                default = f", default={info['default']}" if "default" in info else ""
                enum = f", values={info['enum']}" if "enum" in info else ""
                lines.append(
                    f"  - `{param_name}` ({info['type']}, {required}{default}{enum}): {info.get('description', '')}"
                )
        lines.append("")
    return "\n".join(lines).strip()


@app.get("/health")
def health() -> Response:
    width, height = _screen_size()
    return jsonify(
        {
            "status": "HEALTHY",
            "platform": "linux",
            "screen_width": width,
            "screen_height": height,
            "pyautogui": pyautogui is not None,
            "pyautogui_import_error": _PYAUTOGUI_IMPORT_ERROR,
            "display": os.environ.get("DISPLAY", ""),
        }
    )


@app.get("/device_info")
def device_info() -> Response:
    width, height = _screen_size()
    return jsonify({"platform": "linux", "screen_width": width, "screen_height": height})


@app.get("/observe")
def observe() -> Response:
    include_ui_tree = request.args.get("include_ui_tree", "1") == "1"
    include_screenshot_data = request.args.get("include_screenshot_data", "1") == "1"
    width, height = _screen_size()
    ui_nodes: list[dict[str, Any]] = []
    foreground_app = ""
    foreground_window = ""
    if include_ui_tree:
        ui_nodes, foreground_app, foreground_window = _collect_ui_nodes()
    else:
        foreground_app, foreground_window = _foreground_window_info()
    screenshot_data_base64 = ""
    if include_screenshot_data:
        screenshot_data_base64 = base64.b64encode(_screenshot_bytes()).decode("ascii")
    return jsonify(
        {
            "timestamp": _iso_now(),
            "width": width,
            "height": height,
            "ui_nodes": ui_nodes,
            "foreground_app": foreground_app,
            "foreground_bundle_id": foreground_app,
            "foreground_window": foreground_window,
            "screenshot_data_base64": screenshot_data_base64,
        }
    )


@app.get("/screenshot")
def screenshot() -> Response:
    return send_file(io.BytesIO(_screenshot_bytes()), mimetype="image/png", download_name="screenshot.png")


@app.get("/action_schema")
def action_schema() -> Response:
    return jsonify({"schema": ACTION_SCHEMA, "schema_text": _action_schema_text()})


@app.post("/action")
def action() -> Response:
    payload = request.get_json(silent=True) or {}
    action_payload = payload.get("action") or {}
    ui_nodes = payload.get("ui_nodes") if isinstance(payload.get("ui_nodes"), list) else []
    try:
        result = _execute_action(action_payload, ui_nodes)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc), "terminal": False}), 400


@app.get("/terminal")
def terminal_output() -> Response:
    if pyatspi is None:
        return jsonify({"status": "success", "output": ""})
    try:
        desktop = pyatspi.Registry.getDesktop(0)
        for app_node in desktop:
            role = str(app_node.getRoleName() or "").strip().lower()
            if role != "application":
                continue
            if str(getattr(app_node, "name", "") or "") != "gnome-terminal-server":
                continue
            for frame in app_node:
                frame_states = _normalize_state_names(frame)
                if "active" not in frame_states:
                    continue
                stack = [frame]
                while stack:
                    node = stack.pop()
                    children = list(_iter_children(node))
                    for child in reversed(children):
                        stack.append(child)
                    if str(node.getRoleName() or "").strip().lower() != "terminal":
                        continue
                    if "focused" not in _normalize_state_names(node):
                        continue
                    text = _get_text(node).rstrip()
                    return jsonify({"status": "success", "output": text})
        return jsonify({"status": "success", "output": ""})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/desktop_path")
def desktop_path() -> Response:
    candidate = Path.home() / "Desktop"
    if candidate.exists():
        return jsonify({"desktop_path": str(candidate)})
    return jsonify({"error": "desktop path not found"}), 404


def _list_dir(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"error": "not_found", "path": str(path)}
    if path.is_file():
        return {"type": "file", "name": path.name}
    children = []
    try:
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            if child.is_dir():
                children.append(_list_dir(child))
            else:
                children.append({"type": "file", "name": child.name})
    except OSError as exc:
        return {"error": str(exc), "path": str(path)}
    return {"type": "directory", "name": path.name, "children": children}


@app.post("/list_directory")
def list_directory() -> Response:
    payload = request.get_json(silent=True) or {}
    raw_path = str(payload.get("path") or "").strip()
    if not raw_path:
        return jsonify({"error": "path is required"}), 400
    return jsonify({"directory_tree": _list_dir(Path(raw_path).expanduser())})


@app.post("/file")
def get_file() -> Response:
    raw_path = str(request.form.get("file_path") or "").strip()
    if not raw_path:
        return jsonify({"error": "file_path is required"}), 400
    path = Path(raw_path).expanduser()
    if not path.exists() or not path.is_file():
        return jsonify({"error": "file not found"}), 404
    return send_file(path, as_attachment=True)


@app.post("/setup/launch")
@app.post("/launch")
def launch() -> Response:
    payload = request.get_json(silent=True) or {}
    app_name = str(payload.get("app_name") or "").strip()
    try:
        _launch_app_command(app_name)
        return jsonify({"status": "success", "app_name": app_name})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


def _expand_command(command: Any, shell: bool) -> Any:
    if isinstance(command, str):
        if shell:
            return command
        return [os.path.expanduser(part) for part in shlex.split(command)]
    if isinstance(command, list):
        return [os.path.expanduser(str(part)) for part in command]
    raise ValueError("command must be a string or array")


def _run_subprocess(command: Any, *, shell: bool, timeout: int, cwd: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        shell=shell,
        cwd=cwd,
    )


def _run_verification(verification: Dict[str, Any]) -> bool:
    if not verification:
        return True

    command_success = verification.get("command_success")
    if command_success:
        command = _expand_command(command_success, isinstance(command_success, str))
        result = _run_subprocess(command, shell=isinstance(command_success, str), timeout=10)
        if result.returncode != 0:
            return False

    path_exists = verification.get("path_exists")
    if path_exists and not Path(str(path_exists)).expanduser().exists():
        return False

    stdout_contains = verification.get("stdout_contains")
    if stdout_contains:
        verify_command = verification.get("stdout_command") or command_success
        if not verify_command:
            return False
        command = _expand_command(verify_command, isinstance(verify_command, str))
        result = _run_subprocess(command, shell=isinstance(verify_command, str), timeout=10)
        if str(stdout_contains) not in result.stdout:
            return False

    return True


@app.route("/setup/execute", methods=["POST"])
@app.route("/execute", methods=["POST"])
def execute_command() -> Response:
    payload = request.get_json(silent=True) or {}
    shell = bool(payload.get("shell", False))
    timeout = int(payload.get("timeout", 120))
    try:
        command = _expand_command(payload.get("command", "" if shell else []), shell)
        result = _run_subprocess(command, shell=shell, timeout=timeout)
        return jsonify(
            {
                "status": "success" if result.returncode == 0 else "error",
                "output": result.stdout,
                "error": result.stderr,
                "returncode": result.returncode,
            }
        )
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "output": "", "error": f"timed out after {timeout}s", "returncode": -1}), 500
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/setup/execute_with_verification", methods=["POST"])
@app.route("/execute_with_verification", methods=["POST"])
def execute_command_with_verification() -> Response:
    payload = request.get_json(silent=True) or {}
    shell = bool(payload.get("shell", False))
    timeout = int(payload.get("timeout", 120))
    verification = payload.get("verification") if isinstance(payload.get("verification"), dict) else {}
    max_wait_time = max(0, int(payload.get("max_wait_time", 10)))
    check_interval = max(0.1, float(payload.get("check_interval", 1.0)))

    try:
        command = _expand_command(payload.get("command", "" if shell else []), shell)
        result = _run_subprocess(command, shell=shell, timeout=timeout)
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "output": "", "error": f"timed out after {timeout}s", "returncode": -1}), 500
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    if not verification:
        return jsonify(
            {
                "status": "success" if result.returncode == 0 else "error",
                "output": result.stdout,
                "error": result.stderr,
                "returncode": result.returncode,
            }
        )

    start = time.time()
    while time.time() - start <= max_wait_time:
        if _run_verification(verification):
            return jsonify(
                {
                    "status": "success" if result.returncode == 0 else "error",
                    "output": result.stdout,
                    "error": result.stderr,
                    "returncode": result.returncode,
                    "verification": "passed",
                    "wait_time": round(time.time() - start, 3),
                }
            )
        time.sleep(check_interval)

    return jsonify(
        {
            "status": "verification_failed",
            "output": result.stdout,
            "error": result.stderr,
            "returncode": result.returncode,
            "verification": "failed",
            "wait_time": max_wait_time,
        }
    ), 500


@app.post("/setup/upload")
def upload() -> Response:
    raw_path = str(request.form.get("file_path") or "").strip()
    file_storage = request.files.get("file_data")
    if not raw_path:
        return jsonify({"status": "error", "message": "file_path is required"}), 400
    if file_storage is None:
        return jsonify({"status": "error", "message": "file_data is required"}), 400

    target = Path(raw_path).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_storage.save(target)
        return jsonify({"status": "success", "path": str(target)})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/setup/download")
def setup_download() -> Response:
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url") or "").strip()
    raw_path = str(payload.get("path") or "").strip()
    overwrite = bool(payload.get("overwrite", True))
    if not url:
        return jsonify({"status": "error", "message": "url is required"}), 400
    if not raw_path:
        return jsonify({"status": "error", "message": "path is required"}), 400

    target = Path(raw_path).expanduser()
    if target.exists() and not overwrite:
        return jsonify({"status": "error", "message": "target exists and overwrite is false"}), 409

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(url, timeout=120) as response:
            target.write_bytes(response.read())
        return jsonify({"status": "success", "path": str(target), "url": url})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/setup/write_file")
def setup_write_file() -> Response:
    payload = request.get_json(silent=True) or {}
    raw_path = str(payload.get("path") or "").strip()
    content = payload.get("content")
    encoding = str(payload.get("encoding") or "utf-8")
    overwrite = bool(payload.get("overwrite", True))
    if not raw_path:
        return jsonify({"status": "error", "message": "path is required"}), 400
    if not isinstance(content, str):
        return jsonify({"status": "error", "message": "content must be a string"}), 400

    target = Path(raw_path).expanduser()
    if target.exists() and not overwrite:
        return jsonify({"status": "error", "message": "target exists and overwrite is false"}), 409

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        return jsonify({"status": "success", "path": str(target)})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


def _set_wallpaper_with_gsettings(path: Path) -> None:
    uri = path.resolve().as_uri()
    commands = [
        ["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri],
        ["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", uri],
    ]
    for command in commands:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=10)


@app.post("/setup/change_wallpaper")
def change_wallpaper() -> Response:
    payload = request.get_json(silent=True) or {}
    raw_path = str(payload.get("path") or "").strip()
    if not raw_path:
        return jsonify({"status": "error", "message": "path is required"}), 400

    target = Path(raw_path).expanduser()
    if not target.exists():
        return jsonify({"status": "error", "message": f"path not found: {target}"}), 404

    try:
        _set_wallpaper_with_gsettings(target)
        return jsonify({"status": "success", "path": str(target)})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/run_python")
def run_python() -> Response:
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("code") or "")
    timeout = max(1, int(payload.get("timeout", 30) or 30))
    if not code.strip():
        return jsonify({"status": "error", "message": "code is required"}), 400
    tmp_path = Path("/tmp") / f"helloworld_linux_runtime_{int(time.time() * 1000)}.py"
    try:
        tmp_path.write_text(code, encoding="utf-8")
        result = subprocess.run(
            ["/usr/bin/python3", str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return jsonify(
            {
                "status": "success" if result.returncode == 0 else "error",
                "output": result.stdout,
                "error": result.stderr,
                "return_code": result.returncode,
            }
        )
    except subprocess.TimeoutExpired:
        return (
            jsonify(
                {
                    "status": "error",
                    "output": "",
                    "error": f"TimeoutExpired after {timeout}s",
                    "return_code": -1,
                }
            ),
            500,
        )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


@app.post("/run_bash_script")
def run_bash_script() -> Response:
    payload = request.get_json(silent=True) or {}
    script = str(payload.get("script") or "")
    timeout = int(payload.get("timeout", 30))
    working_dir = payload.get("working_dir")
    if not script.strip():
        return jsonify({"status": "error", "output": "script is required", "error": "", "returncode": -1}), 400
    tmp_path = Path("/tmp") / f"helloworld_linux_runtime_{int(time.time() * 1000)}.sh"
    try:
        body = script if script.startswith("#!/bin/bash") else f"#!/bin/bash\nset -e\n{script}\n"
        tmp_path.write_text(body, encoding="utf-8")
        tmp_path.chmod(0o755)
        result = subprocess.run(
            ["/bin/bash", str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            cwd=str(working_dir) if working_dir else None,
        )
        return jsonify(
            {
                "status": "success" if result.returncode == 0 else "error",
                "output": result.stdout,
                "error": "",
                "returncode": result.returncode,
            }
        )
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "output": f"timed out after {timeout}s", "error": "", "returncode": -1}), 500
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="OS-Omni Linux guest runtime server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--token", default=os.getenv("HELLOWORLD_LINUX_RUNTIME_TOKEN", "linuxbench-runtime-token"))
    args = parser.parse_args(argv)

    global RUNTIME_TOKEN
    RUNTIME_TOKEN = str(args.token or "").strip()
    _try_import_pyautogui()
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
