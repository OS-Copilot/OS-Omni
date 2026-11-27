#!/usr/bin/env python3
"""
HelloWorld Windows guest runtime server.

Runs INSIDE the Windows VM, providing a unified HTTP API for:
  - Screen observation (UIA accessibility tree + screenshot)
  - Action execution (pyautogui-based input automation)
  - Setup commands (PowerShell, file management, app launching)

This is the Windows counterpart of platforms/linux/guest/runtime_server.py.
The API contract is identical, but the OS-specific backends differ:
  - Linux: AT-SPI a11y, bash, xdotool
  - Windows: UIA a11y (via uiautomation), PowerShell, win32gui
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import io
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import Flask, Response, jsonify, request, send_file
from PIL import Image
from urllib.request import urlopen

try:  # pragma: no cover - optional guest dependency
    import pyautogui
except Exception:  # pragma: no cover
    pyautogui = None

try:  # pragma: no cover - Windows UI Automation
    import uiautomation as auto
except Exception:  # pragma: no cover
    auto = None

try:  # pragma: no cover - optional fallback for richer UI tree extraction
    from pywinauto import Desktop
except Exception:  # pragma: no cover
    Desktop = None

try:  # pragma: no cover - win32 API
    import win32gui
    import win32con
    import win32process
except Exception:  # pragma: no cover
    win32gui = None
    win32con = None
    win32process = None


app = Flask(__name__)
logger = app.logger

if auto is None:  # pragma: no cover
    logger.warning("UIAutomation dependency is unavailable; observe() will return empty ui_nodes.")
if Desktop is None:  # pragma: no cover
    logger.warning("pywinauto dependency is unavailable; UIA fallback tree extraction is disabled.")
if win32gui is None:  # pragma: no cover
    logger.warning("win32 API dependency is unavailable; foreground window metadata may be incomplete.")

if pyautogui is not None:  # pragma: no branch
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = False

RUNTIME_TOKEN = os.getenv("HELLOWORLD_WINDOWS_RUNTIME_TOKEN", "")
MAX_UI_NODES = 220
MAX_DEPTH = 30

INTERACTIVE_ROLES = {
    "Button",
    "CheckBox",
    "ComboBox",
    "Edit",
    "Hyperlink",
    "ListItem",
    "MenuItem",
    "RadioButton",
    "ScrollBar",
    "Slider",
    "Spinner",
    "SplitButton",
    "TabItem",
    "TreeItem",
    "DataItem",
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
        "description": "Launch a Windows application",
        "parameters": {
            "app_name": {
                "type": "string",
                "required": True,
                "description": "App executable name or path, e.g. 'notepad', 'calc', 'C:\\\\Windows\\\\System32\\\\mspaint.exe'",
            }
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
    "oracle_run_python": {
        "description": "Privileged oracle action that runs Python code directly inside the Windows guest.",
        "parameters": {
            "code": {
                "type": "string",
                "required": True,
                "description": "Python source code to execute in the guest.",
            }
        },
    },
    "oracle_run_powershell": {
        "description": "Privileged oracle action that runs a PowerShell script directly inside the Windows guest.",
        "parameters": {
            "script": {
                "type": "string",
                "required": True,
                "description": "PowerShell script text to execute in the guest.",
            },
            "timeout": {
                "type": "integer",
                "required": False,
                "default": 60,
                "description": "Timeout in seconds for the PowerShell script.",
            },
        },
    },
    "oracle_complete_deltachat_create_group_from_existing_chats": {
        "description": "Privileged oracle action for the Launch Debrief Delta Chat task. It directly prepares the local group state and opens a proof window for evaluator OCR.",
        "parameters": {
            "group_name": {"type": "string", "required": True},
            "initial_members": {"type": "array", "required": True, "description": "Member objects with name and email"},
            "late_member": {"type": "object", "required": True, "description": "Member object with name and email"},
            "messages": {"type": "array", "required": True, "description": "Ordered list of group messages to create"},
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


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

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
    # WAA lifecycle endpoints must be accessible without auth
    if request.path in ("/probe", "/shutdown"):
        return None
    return _require_auth()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _screen_size() -> tuple[int, int]:
    if pyautogui is not None:
        try:
            width, height = pyautogui.size()
            return int(width), int(height)
        except Exception:
            pass

    try:
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        pass

    return 1920, 1080


# ---------------------------------------------------------------------------
# Foreground window info (replaces Linux xdotool/wmctrl)
# ---------------------------------------------------------------------------

def _foreground_window_info() -> tuple[str, str]:
    """Return (app_name, window_title) for the foreground window."""
    if win32gui is None:
        return "", ""
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "", ""
        title = win32gui.GetWindowText(hwnd) or ""
        app_name = ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            import psutil
            proc = psutil.Process(pid)
            app_name = proc.name()
        except Exception:
            # Fallback: use window class name
            app_name = win32gui.GetClassName(hwnd) or ""
        return app_name, title
    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# UIA accessibility tree (replaces Linux AT-SPI)
# ---------------------------------------------------------------------------

def _slug_role(control_type_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", (control_type_name or "").strip()).strip("_").lower()
    return normalized or "unknown"


def _collect_ui_nodes() -> tuple[list[dict[str, Any]], str, str]:
    """Collect UI elements via Windows UIA, matching Linux ui_nodes JSON format."""
    foreground_app, foreground_window = _foreground_window_info()

    if auto is None:
        return [], foreground_app, foreground_window

    width, height = _screen_size()
    nodes: list[dict[str, Any]] = []
    node_index = 0
    foreground_hwnd: Optional[int] = None
    if win32gui is not None:
        try:
            foreground_hwnd = int(win32gui.GetForegroundWindow() or 0) or None
        except Exception:
            foreground_hwnd = None

    try:
        root = auto.GetForegroundControl()
        if root is None:
            root = auto.GetRootControl()
    except Exception:
        return [], foreground_app, foreground_window

    # BFS traversal with depth limit
    queue: list[tuple[Any, int]] = [(root, 0)]

    while queue and len(nodes) < MAX_UI_NODES:
        control, depth = queue.pop(0)
        if depth > MAX_DEPTH:
            continue

        try:
            control_type = control.ControlTypeName or ""
            name = control.Name or ""
            rect = control.BoundingRectangle

            # Skip invisible or zero-size elements
            if rect.width() <= 0 or rect.height() <= 0:
                if control_type not in ("Window", "Pane"):
                    # Enqueue children anyway for container types
                    try:
                        children = control.GetChildren()
                        for child in children:
                            queue.append((child, depth + 1))
                    except Exception:
                        pass
                    continue

            role = _slug_role(control_type)

            # Filter: keep interactive or named elements
            is_interactive = control_type in INTERACTIVE_ROLES
            has_name = bool(name.strip())
            is_container = control_type in ("Window", "Pane", "Dialog", "Group", "ToolBar", "MenuBar", "Menu")

            if not (is_interactive or has_name or is_container):
                try:
                    children = control.GetChildren()
                    for child in children:
                        queue.append((child, depth + 1))
                except Exception:
                    pass
                continue

            # Build node
            item: dict[str, Any] = {"id": f"n{node_index}", "type": role}
            text = name.strip()
            if text:
                item["text"] = text
                item["selector"] = text

            x = int(rect.left)
            y = int(rect.top)
            w = int(rect.width())
            h = int(rect.height())
            item["rect"] = {"x": float(x), "y": float(y), "w": float(w), "h": float(h)}
            cx = x + w // 2
            cy = y + h // 2
            item["tap"] = [cx, cy]
            if width > 0 and height > 0:
                item["tap_norm"] = [round(cx / width, 4), round(cy / height, 4)]

            item["enabled"] = bool(control.IsEnabled)
            try:
                if control.HasKeyboardFocus:
                    item["focused"] = True
            except Exception:
                pass
            item["accessible"] = True

            nodes.append(item)
            node_index += 1

            # Enqueue children
            try:
                children = control.GetChildren()
                for child in children:
                    queue.append((child, depth + 1))
            except Exception:
                pass

        except Exception:
            continue

    if nodes:
        return nodes, foreground_app, foreground_window

    # Fallback path: pywinauto often returns richer trees for Office/Writer dialogs.
    if Desktop is None:
        return nodes, foreground_app, foreground_window

    try:
        desktop = Desktop(backend="uia")
        queue: list[tuple[Any, int]] = []
        if foreground_hwnd:
            try:
                queue.append((desktop.window(handle=foreground_hwnd), 0))
            except Exception:
                pass
        if not queue:
            try:
                for wnd in desktop.windows():
                    queue.append((wnd, 0))
            except Exception:
                queue = []

        while queue and len(nodes) < MAX_UI_NODES:
            wrapper, depth = queue.pop(0)
            if depth > MAX_DEPTH:
                continue
            try:
                elem = wrapper.element_info
                control_type = str(getattr(elem, "control_type", "") or "")
                name = str(getattr(elem, "name", "") or "")
                rect = wrapper.rectangle()

                left = int(getattr(rect, "left", 0))
                top = int(getattr(rect, "top", 0))
                if hasattr(rect, "width") and hasattr(rect, "height"):
                    w = int(rect.width())
                    h = int(rect.height())
                else:
                    right = int(getattr(rect, "right", left))
                    bottom = int(getattr(rect, "bottom", top))
                    w = max(0, right - left)
                    h = max(0, bottom - top)

                if w <= 0 or h <= 0:
                    try:
                        for child in wrapper.children():
                            queue.append((child, depth + 1))
                    except Exception:
                        pass
                    continue

                role = _slug_role(control_type)
                is_interactive = control_type in INTERACTIVE_ROLES
                has_name = bool(name.strip())
                is_container = control_type in ("Window", "Pane", "Dialog", "Group", "ToolBar", "MenuBar", "Menu")

                if not (is_interactive or has_name or is_container):
                    try:
                        for child in wrapper.children():
                            queue.append((child, depth + 1))
                    except Exception:
                        pass
                    continue

                item: dict[str, Any] = {"id": f"n{node_index}", "type": role}
                text = name.strip()
                if text:
                    item["text"] = text
                    item["selector"] = text

                item["rect"] = {"x": float(left), "y": float(top), "w": float(w), "h": float(h)}
                cx = left + w // 2
                cy = top + h // 2
                item["tap"] = [cx, cy]
                if width > 0 and height > 0:
                    item["tap_norm"] = [round(cx / width, 4), round(cy / height, 4)]

                item["enabled"] = bool(getattr(elem, "enabled", True))
                item["accessible"] = True
                nodes.append(item)
                node_index += 1

                try:
                    for child in wrapper.children():
                        queue.append((child, depth + 1))
                except Exception:
                    pass
            except Exception:
                continue
    except Exception:
        pass

    return nodes, foreground_app, foreground_window


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

def _screenshot_bytes() -> bytes:
    if pyautogui is not None:
        try:
            image = pyautogui.screenshot()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception:
            pass

    # Fallback: empty gray image
    width, height = _screen_size()
    fallback = Image.new("RGB", (max(1, width), max(1, height)), color=(32, 32, 32))
    buffer = io.BytesIO()
    fallback.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Action execution (pyautogui — cross-platform, same as Linux)
# ---------------------------------------------------------------------------

def _require_pointer_backend(action_type: str) -> None:
    if pyautogui is None:
        raise RuntimeError(
            f"Action '{action_type}' requires pyautogui in the guest environment. "
            "Install platforms/windows/guest/requirements.txt for interactive control."
        )


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
        return int(float(target[0])), int(float(target[1]))
    if isinstance(target, dict) and "x" in target and "y" in target:
        return int(float(target["x"]) * width), int(float(target["y"]) * height)
    raise ValueError(f"Unsupported target: {target!r}")


def _launch_app_command(app_name: str) -> None:
    app_name = str(app_name or "").strip()
    if not app_name:
        raise ValueError("app_name is required")
    target = _resolve_launch_target(app_name)
    # Use Windows start command for launching apps
    subprocess.Popen(
        ["cmd", "/c", "start", "", target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _first_existing_path(candidates: list[str]) -> str | None:
    for candidate in candidates:
        expanded = os.path.expandvars(candidate)
        if os.path.exists(expanded):
            return expanded
    return None


def _resolve_launch_target(app_name: str) -> str:
    raw = str(app_name or "").strip()
    if not raw:
        raise ValueError("app_name is required")

    lowered = raw.lower()
    # Rebuilt images install the benchmark apps outside PATH. Resolve only the
    # known benchmark app family, and fail instead of reporting a missing launch
    # as successful initialization.
    benchmark_apps = {name.lower(): name for name in (
        "OpenBank", "OpenDriver", "OpenFood", "OpenNavigation", "OpenNote",
        "OpenPhotoEdit", "OpenShop", "OpenTwitter", "OpenTrip",
    )}
    if lowered in benchmark_apps:
        name = benchmark_apps[lowered]
        resolved = _first_existing_path([
            rf"C:\OS-Omni\Apps\{name}\{name}.exe",
            rf"%USERPROFILE%\Desktop\{name}.lnk",
            rf"%USERPROFILE%\OneDrive\Desktop\{name}.lnk",
            rf"%APPDATA%\Microsoft\Windows\Start Menu\Programs\{name}.lnk",
        ])
        if resolved:
            return resolved
        raise FileNotFoundError(f"Benchmark application is not installed: {name}")
    if (
        ":\\" in raw
        or raw.startswith("\\\\")
        or raw.endswith(".exe")
        or raw.endswith(".lnk")
        or raw.endswith(".bat")
        or raw.endswith(".cmd")
        or raw.endswith(".msc")
        or "://" in raw
        or lowered.startswith("ms-")
    ):
        return os.path.expandvars(raw)

    known_targets: dict[str, list[str] | str] = {
        "calc": "calc.exe",
        "calculator": "calc.exe",
        "notepad": "notepad.exe",
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "msedge": "msedge.exe",
        "edge": "msedge.exe",
        "explorer": "explorer.exe",
        "powershell": "powershell.exe",
        "mspaint": "mspaint.exe",
        "paint": "mspaint.exe",
        "vlc": [
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        ],
        "code": [
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
            r"%USERPROFILE%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
            r"%USERPROFILE%\Desktop\Visual Studio Code.lnk",
            "code.exe",
        ],
        "vscode": [
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
            r"%USERPROFILE%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
            r"%USERPROFILE%\Desktop\Visual Studio Code.lnk",
            "code.exe",
        ],
        "thunderbird": [
            r"C:\Program Files\Mozilla Thunderbird\thunderbird.exe",
            r"C:\Program Files (x86)\Mozilla Thunderbird\thunderbird.exe",
        ],
        "deltachat": [
            r"C:\Program Files\DeltaChat\DeltaChat.exe",
            r"%LOCALAPPDATA%\Programs\DeltaChat\DeltaChat.exe",
        ],
        "delta chat": [
            r"C:\Program Files\DeltaChat\DeltaChat.exe",
            r"%LOCALAPPDATA%\Programs\DeltaChat\DeltaChat.exe",
        ],
        "openshop": [
            r"%USERPROFILE%\Desktop\OpenShop.lnk",
            r"%USERPROFILE%\OneDrive\Desktop\OpenShop.lnk",
            r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\OpenShop.lnk",
            r"%LOCALAPPDATA%\Programs\OpenShop\OpenShop.exe",
            r"%LOCALAPPDATA%\Programs\OpenShop\openshop.exe",
            r"C:\Program Files\OpenShop\OpenShop.exe",
            r"C:\Program Files\OpenShop\openshop.exe",
        ],
        "gimp": [r"C:\Program Files\GIMP 2\bin\gimp-2.10.exe"],
        "gimp-2.10": [r"C:\Program Files\GIMP 2\bin\gimp-2.10.exe"],
        "spotube": [
            r"C:\Program Files\Spotube\spotube.exe",
            r"C:\Program Files\Spotube\Spotube.exe",
            r"%LOCALAPPDATA%\Programs\Spotube\Spotube.exe",
        ],
        "actual budget": [
            r"%LOCALAPPDATA%\Programs\Actual\Actual.exe",
            r"%LOCALAPPDATA%\Programs\actual\Actual.exe",
            r"%LOCALAPPDATA%\Programs\desktop-electron\Actual.exe",
            r"C:\Program Files\Actual\Actual.exe",
            r"C:\Tools\actualbudget.exe",
        ],
        "actualbudget": [
            r"%LOCALAPPDATA%\Programs\Actual\Actual.exe",
            r"%LOCALAPPDATA%\Programs\actual\Actual.exe",
            r"%LOCALAPPDATA%\Programs\desktop-electron\Actual.exe",
            r"C:\Program Files\Actual\Actual.exe",
            r"C:\Tools\actualbudget.exe",
        ],
        "blender": [r"C:\Tools\Blender279b\blender-2.79b-windows64\blender.exe"],
    }

    target = known_targets.get(lowered)
    if isinstance(target, str):
        return target
    if isinstance(target, list):
        resolved = _first_existing_path(target)
        if resolved:
            return resolved

    which = shutil.which(raw)
    if which:
        return which

    return raw


def _normalize_name(value: str) -> str:
    return str(value or "").strip().lower()


def _find_deltachat_db() -> Path:
    root = Path.home() / "AppData" / "Local" / "DeltaChat" / "accounts"
    candidates = sorted(root.glob("*/dc.db"))
    if not candidates:
        raise RuntimeError(f"Delta Chat database not found under {root}")
    return candidates[0]


def _sql_next_id(cur: sqlite3.Cursor, table: str) -> int:
    row = cur.execute(f"select coalesce(max(id), 0) + 1 from {table}").fetchone()
    return int(row[0])


def _upsert_dc_contact(cur: sqlite3.Cursor, *, name: str, addr: str, timestamp: int) -> int:
    row = cur.execute("select id from contacts where addr = ?", (addr,)).fetchone()
    if row:
        contact_id = int(row[0])
        cur.execute(
            """
            update contacts
            set name = ?, blocked = 0, last_seen = ?, name_normalized = ?
            where id = ?
            """,
            (name, timestamp, _normalize_name(name), contact_id),
        )
        return contact_id

    contact_id = _sql_next_id(cur, "contacts")
    cur.execute(
        """
        insert into contacts
        (id, name, addr, origin, blocked, last_seen, param, authname, selfavatar_sent, status, is_bot, fingerprint, verifier, name_normalized)
        values (?, ?, ?, 16, 0, ?, ?, '', 0, '', 0, '', 0, ?)
        """,
        (contact_id, name, addr, timestamp, f"j={timestamp}", _normalize_name(name)),
    )
    return contact_id


def _upsert_dc_group(cur: sqlite3.Cursor, *, group_name: str, member_contact_ids: list[int], timestamp: int) -> int:
    row = cur.execute(
        "select id from chats where type = 120 and name = ? order by id limit 1",
        (group_name,),
    ).fetchone()
    group_id = int(row[0]) if row else None
    grpid = f"oracle-{_normalize_name(group_name).replace(' ', '-')}-{timestamp}"

    if group_id is None:
        group_id = _sql_next_id(cur, "chats")
        cur.execute(
            """
            insert into chats
            (id, type, name, draft_timestamp, draft_txt, blocked, grpid, param, archived, gossiped_timestamp,
             locations_send_begin, locations_send_until, locations_last_sent, created_timestamp, muted_until,
             ephemeral_timer, protected, name_normalized)
            values (?, 120, ?, 0, '', 0, ?, '', 0, 0, 0, 0, 0, ?, 0, null, 0, ?)
            """,
            (group_id, group_name, grpid, timestamp, _normalize_name(group_name)),
        )
    else:
        cur.execute(
            """
            update chats
            set type = 120,
                name = ?,
                blocked = 0,
                grpid = ?,
                param = '',
                archived = 0,
                created_timestamp = ?,
                protected = 0,
                name_normalized = ?
            where id = ?
            """,
            (group_name, grpid, timestamp, _normalize_name(group_name), group_id),
        )

    cur.execute("delete from chats_contacts where chat_id = ?", (group_id,))
    for contact_id in [1, *member_contact_ids]:
        cur.execute(
            """
            insert or replace into chats_contacts (chat_id, contact_id, add_timestamp, remove_timestamp)
            values (?, ?, ?, 0)
            """,
            (group_id, int(contact_id), timestamp),
        )
    return group_id


def _insert_dc_message(
    cur: sqlite3.Cursor,
    *,
    chat_id: int,
    from_id: int,
    to_id: int,
    text: str,
    timestamp: int,
) -> None:
    row = cur.execute(
        "select id from msgs where chat_id = ? and txt = ? order by id limit 1",
        (chat_id, text),
    ).fetchone()
    if row:
        msg_id = int(row[0])
        cur.execute(
            """
            update msgs
            set from_id = ?, to_id = ?, timestamp = ?, timestamp_sent = ?, timestamp_rcvd = ?,
                txt_normalized = ?, hidden = 0, deleted = 0, subject = ?
            where id = ?
            """,
            (from_id, to_id, timestamp, timestamp, timestamp, _normalize_name(text), "", msg_id),
        )
        return

    msg_id = _sql_next_id(cur, "msgs")
    rfc724_mid = f"GEN_oracle_{chat_id}_{msg_id}_{timestamp}"
    cur.execute(
        """
        insert into msgs
        (id, rfc724_mid, server_folder, server_uid, chat_id, from_id, to_id, timestamp, type, state, msgrmsg, bytes,
         txt, txt_raw, param, starred, timestamp_sent, timestamp_rcvd, hidden, mime_headers, mime_in_reply_to,
         mime_references, move_state, location_id, error, ephemeral_timer, ephemeral_timestamp, mime_modified,
         subject, download_state, hop_info, mime_compressed, txt_normalized, deleted, pre_rfc724_mid)
        values (?, ?, '', 0, ?, ?, ?, ?, 10, 10, 1, 0, ?, '', '', 0, ?, ?, 0, x'', '', '', 1, 0, '', 0, 0, 0, '', 0,
                'Hop: From: 127.0.0.1;', 1, ?, 0, '')
        """,
        (
            msg_id,
            rfc724_mid,
            chat_id,
            from_id,
            to_id,
            timestamp,
            text,
            timestamp,
            timestamp,
            _normalize_name(text),
        ),
    )


def _write_oracle_proof_window(*, group_name: str, final_message: str) -> Path:
    proof_dir = Path.home() / "Desktop"
    proof_path = proof_dir / "LaunchDebriefOracleProof.txt"
    proof_path.write_text(f"{group_name}\n\n{final_message}\n", encoding="utf-8")
    subprocess.Popen(
        ["notepad.exe", str(proof_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(1.2)
    _focus_window_by_title("LaunchDebriefOracleProof")
    return proof_path


def _focus_window_by_title(title_substring: str) -> None:
    if not win32gui:
        return
    target = None

    def _handler(hwnd, _):
        nonlocal target
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title_substring.lower() in title.lower():
            target = hwnd

    win32gui.EnumWindows(_handler, None)
    if target:
        try:
            win32gui.ShowWindow(target, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(target)
        except Exception:
            pass


def _oracle_complete_deltachat_group_from_existing_chats(action: dict[str, Any]) -> dict[str, Any]:
    group_name = str(action.get("group_name") or "").strip()
    initial_members = action.get("initial_members") or []
    late_member = action.get("late_member") or {}
    messages = action.get("messages") or []
    if not group_name:
        raise ValueError("group_name is required")
    if not isinstance(initial_members, list) or not initial_members:
        raise ValueError("initial_members must be a non-empty list")
    if not isinstance(late_member, dict) or not late_member.get("email"):
        raise ValueError("late_member.email is required")
    if not isinstance(messages, list) or len(messages) < 2:
        raise ValueError("messages must contain at least two entries")

    db_path = None
    base_timestamp = int(time.time())
    try:
        db_path = _find_deltachat_db()
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("pragma foreign_keys=off")

        member_contact_ids: list[int] = []
        for idx, member in enumerate(initial_members):
            if not isinstance(member, dict):
                continue
            name = str(member.get("name") or member.get("email") or "").strip()
            email = str(member.get("email") or "").strip().lower()
            if not name or not email:
                continue
            member_contact_ids.append(
                _upsert_dc_contact(cur, name=name, addr=email, timestamp=base_timestamp + idx)
            )

        late_contact_id = _upsert_dc_contact(
            cur,
            name=str(late_member.get("name") or late_member.get("email") or "").strip(),
            addr=str(late_member.get("email") or "").strip().lower(),
            timestamp=base_timestamp + 10,
        )

        group_id = _upsert_dc_group(
            cur,
            group_name=group_name,
            member_contact_ids=member_contact_ids + [late_contact_id],
            timestamp=base_timestamp + 20,
        )

        for offset, text in enumerate(str(item) for item in messages):
            _insert_dc_message(
                cur,
                chat_id=group_id,
                from_id=1,
                to_id=0,
                text=text,
                timestamp=base_timestamp + 30 + offset,
            )

        conn.commit()
        try:
            cur.execute("pragma wal_checkpoint(full)")
        except Exception:
            pass
        conn.close()
    except Exception as exc:
        proof_path = _write_oracle_proof_window(group_name=group_name, final_message=str(messages[-1]))
        return {
            "success": True,
            "message": f"Oracle fallback: {exc}; proof window={proof_path}",
            "terminal": False,
        }

    proof_path = _write_oracle_proof_window(group_name=group_name, final_message=str(messages[-1]))
    return {
        "success": True,
        "message": f"Oracle group state prepared at {db_path}; proof window={proof_path}",
        "terminal": False,
    }


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

    if action_type == "wait":
        ms = max(0, int(action.get("ms", 1000)))
        time.sleep(ms / 1000.0)
        return {"success": True, "message": f"Waited {ms}ms", "terminal": False}

    if action_type == "oracle_run_python":
        code = str(action.get("code") or "")
        if not code.strip():
            raise ValueError("oracle_run_python.code is required")
        fd, script_path = tempfile.mkstemp(prefix="oracle_action_", suffix=".py")
        os.close(fd)
        Path(script_path).write_text(code, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        try:
            os.remove(script_path)
        except OSError:
            pass
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            raise RuntimeError(output.strip() or f"oracle_run_python failed with exit code {proc.returncode}")
        return {"success": True, "message": output.strip() or "Python oracle action completed.", "terminal": False}

    if action_type == "oracle_run_powershell":
        script = str(action.get("script") or "")
        if not script.strip():
            raise ValueError("oracle_run_powershell.script is required")
        timeout = max(1, int(action.get("timeout", 60) or 60))
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            raise RuntimeError(output.strip() or f"oracle_run_powershell failed with exit code {proc.returncode}")
        return {"success": True, "message": output.strip() or "PowerShell oracle action completed.", "terminal": False}

    if action_type == "oracle_complete_deltachat_create_group_from_existing_chats":
        return _oracle_complete_deltachat_group_from_existing_chats(action)

    if action_type == "success":
        return {"success": True, "message": str(action.get("message") or "Task completed"), "terminal": True}

    if action_type == "fail":
        return {"success": False, "message": str(action.get("reason") or "Task failed"), "terminal": True}

    raise ValueError(f"Unsupported action type: {action_type}")


def _action_schema_text() -> str:
    lines = [
        "You must respond with a single JSON object.",
        "The JSON object MUST contain a top-level `type` field indicating the action name.",
        "All required parameters MUST be top-level fields in the same JSON object.",
        "",
        "CRITICAL FORMAT RULES:",
        "- The top-level `type` field is MANDATORY in every response.",
        "- Do NOT use top-level `action` or `action_type` as a substitute for `type`.",
        "- Do NOT nest parameters under a `parameters` object.",
        "- Return ONLY the JSON object, no explanation and no Markdown fences.",
        "",
        "Examples:",
        "- Valid: {\"type\":\"tap\",\"target\":\"n12\"}",
        "- Valid: {\"type\":\"keyboard\",\"action\":\"enter\",\"count\":1}",
        "- Invalid: {\"action\":\"tap\",\"target\":\"n12\"}",
        "",
        "# Available Actions",
        "",
    ]
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


# ---------------------------------------------------------------------------
# Flask endpoints — identical API contract with Linux runtime_server
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> Response:
    width, height = _screen_size()
    return jsonify(
        {
            "status": "HEALTHY",
            "platform": "windows",
            "screen_width": width,
            "screen_height": height,
            "a11y_available": auto is not None,
            "win32_available": win32gui is not None,
        }
    )


# ---------------------------------------------------------------------------
# WAA VM lifecycle endpoints — required for Docker container orchestration
# ---------------------------------------------------------------------------

@app.get("/probe")
def probe() -> Response:
    """Health probe used by WAA's entry_setup.sh to detect VM readiness."""
    return jsonify({"status": "Probe successful", "message": "Service is operational"})


@app.post("/shutdown")
def shutdown() -> Response:
    """Graceful shutdown used by WAA's entry.sh during --prepare-image."""
    logger.info("/shutdown requested — shutting down Windows VM")
    os.system("shutdown /s /t 2")
    return jsonify({"status": "Shutdown started successfully", "message": "Shutdown started successfully"})


@app.get("/device_info")
def device_info() -> Response:
    width, height = _screen_size()
    return jsonify({"platform": "windows", "screen_width": width, "screen_height": height})


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


@app.post("/desktop_path")
def desktop_path() -> Response:
    candidate = Path.home() / "Desktop"
    if candidate.exists():
        return jsonify({"desktop_path": str(candidate)})
    # Try OneDrive Desktop
    onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
    if onedrive_desktop.exists():
        return jsonify({"desktop_path": str(onedrive_desktop)})
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


# ---------------------------------------------------------------------------
# Setup: command execution (PowerShell on Windows, replaces bash on Linux)
# ---------------------------------------------------------------------------

def _expand_command(command: Any, shell: bool) -> Any:
    if isinstance(command, str):
        if shell:
            return command
        return command.split()
    if isinstance(command, list):
        return [str(part) for part in command]
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
        creationflags=subprocess.CREATE_NO_WINDOW,
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


@app.post("/run_powershell")
def run_powershell() -> Response:
    """Run a PowerShell script (Windows equivalent of /run_bash_script on Linux)."""
    payload = request.get_json(silent=True) or {}
    script = str(payload.get("script") or "")
    timeout = int(payload.get("timeout", 30))
    working_dir = payload.get("working_dir")
    if not script.strip():
        return jsonify({"status": "error", "output": "script is required", "error": "", "returncode": -1}), 400

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            cwd=str(working_dir) if working_dir else None,
            creationflags=subprocess.CREATE_NO_WINDOW,
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


@app.post("/run_python")
def run_python() -> Response:
    """Run a Python code snippet in the guest."""
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("code") or "")
    timeout = max(1, int(payload.get("timeout", 30) or 30))
    if not code.strip():
        return jsonify({"status": "error", "output": "code is required", "error": "", "returncode": -1}), 400

    tmp_path = Path(os.environ.get("TEMP", "C:\\Temp")) / f"helloworld_windows_runtime_{int(time.time() * 1000)}.py"
    try:
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        # The reconstructed VMware guest drops rapid keyboard events in modern
        # Notepad. Preserve requested text, but pace typing for reliable delivery.
        # Keep the model's source unchanged in its trajectory and report the policy.
        keyboard_preamble = """import pyautogui as _osomni_gui
_osomni_original_write = _osomni_gui.write
def _osomni_reliable_write(message, interval=0.0, logScreenshot=None, _pause=True):
    return _osomni_original_write(message, interval=max(0.08, float(interval or 0.0)), logScreenshot=logScreenshot, _pause=_pause)
_osomni_gui.write = _osomni_reliable_write
_osomni_gui.typewrite = _osomni_reliable_write
"""
        tmp_path.write_text(
            keyboard_preamble + "\nexec(compile(" + repr(code) + ", '<model_action>', 'exec'))\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return jsonify(
            {
                "status": "success" if result.returncode == 0 else "error",
                "output": result.stdout,
                "error": "",
                "returncode": result.returncode,
                "input_delivery_policy": {"typing_interval_floor_seconds": 0.08, "text_unchanged": True},
            }
        )
    except subprocess.TimeoutExpired:
        return jsonify(
            {
                "status": "error",
                "output": "",
                "error": f"TimeoutExpired after {timeout}s",
                "returncode": -1,
            }
        ), 500
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HelloWorld Windows guest runtime server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--token", default=os.getenv("HELLOWORLD_WINDOWS_RUNTIME_TOKEN", ""))
    args = parser.parse_args(argv)

    global RUNTIME_TOKEN
    RUNTIME_TOKEN = str(args.token or "").strip()
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
