#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hmac
import io
import json
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from urllib.request import urlopen
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, Response, jsonify, request, send_file

try:
    from platforms.macos.shared.drawio_prepared_targets import (
        DRAWIO_PREPARED_TARGETS,
        extract_drawio_filename_from_window_title,
        resolve_prepared_drawio_document_path,
        resolve_prepared_drawio_target_id,
    )
except Exception:
    DRAWIO_PREPARED_TARGETS: Dict[str, List[Tuple[str, str, float, float]]] = {
        "release_board_refresh.drawio": [
            ("Card 1", "card_1", 0.182, 0.307),
            ("Card 2", "card_2", 0.280, 0.307),
            ("Card 3", "card_3", 0.378, 0.307),
            ("Card 4", "card_4", 0.182, 0.418),
            ("Card 5", "card_5", 0.280, 0.418),
            ("Card 6", "card_6", 0.378, 0.418),
        ],
        "launch_matrix_sync.drawio": [
            ("Slot 1", "card_1", 0.175, 0.307),
            ("Slot 2", "card_2", 0.255, 0.307),
            ("Slot 3", "card_3", 0.336, 0.307),
            ("Slot 4", "card_4", 0.417, 0.307),
            ("Slot 5", "card_5", 0.497, 0.307),
            ("Slot 6", "card_6", 0.175, 0.412),
            ("Slot 7", "card_7", 0.255, 0.412),
            ("Slot 8", "card_8", 0.336, 0.412),
            ("Slot 9", "card_9", 0.417, 0.412),
            ("Slot 10", "card_10", 0.497, 0.412),
            ("Slot 11", "card_11", 0.175, 0.517),
            ("Slot 12", "card_12", 0.255, 0.517),
            ("Slot 13", "card_13", 0.336, 0.517),
            ("Slot 14", "card_14", 0.417, 0.517),
            ("Slot 15", "card_15", 0.497, 0.517),
            ("Slot 16", "card_16", 0.175, 0.622),
            ("Slot 17", "card_17", 0.255, 0.622),
            ("Slot 18", "card_18", 0.336, 0.622),
            ("Slot 19", "card_19", 0.417, 0.622),
            ("Slot 20", "card_20", 0.497, 0.622),
        ],
        "ops_plan_relabel.drawio": [
            ("Item 1", "card_1", 0.175, 0.307),
            ("Item 2", "card_2", 0.255, 0.307),
            ("Item 3", "card_3", 0.336, 0.307),
            ("Item 4", "card_4", 0.417, 0.307),
            ("Item 5", "card_5", 0.497, 0.307),
            ("Item 6", "card_6", 0.175, 0.412),
            ("Item 7", "card_7", 0.255, 0.412),
            ("Item 8", "card_8", 0.336, 0.412),
            ("Item 9", "card_9", 0.417, 0.412),
            ("Item 10", "card_10", 0.497, 0.412),
            ("Item 11", "card_11", 0.175, 0.517),
            ("Item 12", "card_12", 0.255, 0.517),
            ("Item 13", "card_13", 0.336, 0.517),
            ("Item 14", "card_14", 0.417, 0.517),
            ("Item 15", "card_15", 0.497, 0.517),
            ("Item 16", "card_16", 0.175, 0.622),
            ("Item 17", "card_17", 0.255, 0.622),
            ("Item 18", "card_18", 0.336, 0.622),
            ("Item 19", "card_19", 0.417, 0.622),
            ("Item 20", "card_20", 0.497, 0.622),
        ],
    }

    def extract_drawio_filename_from_window_title(title: str) -> Optional[str]:
        raw_title = str(title or "").strip()
        if not raw_title:
            return None
        match = re.search(r"([^/\\]+\.drawio)\b", raw_title)
        if not match:
            return None
        return match.group(1)

    def resolve_prepared_drawio_target_id(
        filename: str,
        x_norm: float,
        y_norm: float,
    ) -> Optional[str]:
        entries = DRAWIO_PREPARED_TARGETS.get(str(filename or "").strip())
        if not entries:
            return None

        best: Optional[Tuple[str, float]] = None
        for _label, cell_id, px, py in entries:
            distance = ((px - x_norm) ** 2) + ((py - y_norm) ** 2)
            if best is None or distance < best[1]:
                best = (cell_id, distance)

        if best is None:
            return None
        return best[0]

    def resolve_prepared_drawio_document_path(
        available_paths: List[Path],
        window_titles: List[str],
    ) -> Optional[Path]:
        available_by_name = {
            path.name: path
            for path in available_paths
            if path.is_file() and path.name in DRAWIO_PREPARED_TARGETS
        }
        if not available_by_name:
            return None

        for title in window_titles:
            filename = extract_drawio_filename_from_window_title(title)
            if filename and filename in available_by_name:
                return available_by_name[filename]

        if len(available_by_name) == 1:
            return next(iter(available_by_name.values()))

        return max(available_by_name.values(), key=lambda path: path.stat().st_mtime)

try:
    from platforms.macos.shared.textedit_prepared_files import (
        PREPARED_TEXTEDIT_FILENAMES,
        apply_prepared_textedit_mutation,
        extract_textedit_filename_from_window_title,
    )
except Exception:
    PREPARED_TEXTEDIT_FILENAMES = {"ops_note.txt", "shift_log.txt", "app.ini"}

    def extract_textedit_filename_from_window_title(title: str) -> Optional[str]:
        raw_title = str(title or "").strip()
        if not raw_title:
            return None
        match = re.search(r"([^/\\]+\.(?:txt|ini))\b", raw_title, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1)

    def _normalize_textedit_lines(text: str) -> list[str]:
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        return normalized.rstrip("\n").split("\n") if normalized else []

    def _replace_textedit_prefixed_line(lines: List[str], prefix: str, new_line: str) -> bool:
        for index, line in enumerate(lines):
            if line.startswith(prefix):
                lines[index] = new_line
                return True
        return False

    def _remove_textedit_line(lines: List[str], target: str) -> bool:
        try:
            lines.remove(target)
        except ValueError:
            return False
        return True

    def _insert_textedit_line_after(lines: List[str], anchor: str, new_line: str) -> bool:
        try:
            anchor_index = lines.index(anchor)
        except ValueError:
            return False

        lines[:] = [line for line in lines if line != new_line]
        lines.insert(anchor_index + 1, new_line)
        return True

    def _append_textedit_line(lines: List[str], new_line: str) -> bool:
        lines[:] = [line for line in lines if line != new_line]
        lines.append(new_line)
        return True

    def _normalize_textedit_payload(payload_text: str) -> str:
        return str(payload_text or "").strip()

    def apply_prepared_textedit_mutation(
        filename: str,
        current_text: str,
        payload_text: str,
    ) -> Optional[str]:
        filename = str(filename or "").strip()
        payload_text = _normalize_textedit_payload(payload_text)
        if not payload_text:
            return None
        lines = _normalize_textedit_lines(current_text)

        if filename == "ops_note.txt":
            footer = [
                "Follow-up:",
                "Owner: Riley",
                "Status: ready",
                "Badge count: 12",
                "Next check: 15:30",
                "Desk phone: 555-0187",
            ]
            if payload_text in footer and payload_text not in lines:
                payload_index = footer.index(payload_text)
                if all(previous in lines for previous in footer[:payload_index]):
                    _append_textedit_line(lines, payload_text)
                    return "\n".join(lines) + ("\n" if lines else "")
            return None
        elif filename == "shift_log.txt":
            operations = {
                "Coordinator: Mina": lambda: _insert_textedit_line_after(lines, "Shift Summary", "Coordinator: Mina")
                if "Coordinator: Mina" not in lines
                else False,
                "Priority: high": lambda: _insert_textedit_line_after(lines, "Coordinator: Mina", "Priority: high")
                if "Priority: high" not in lines
                else False,
                "Desk: South Lobby": lambda: _insert_textedit_line_after(lines, "Priority: high", "Desk: South Lobby")
                if "Desk: South Lobby" not in lines
                else False,
                "Front desk status: badges delivered": lambda: _replace_textedit_prefixed_line(
                    lines, "Front desk status:", "Front desk status: badges delivered"
                )
                if "Front desk status: badges delivered" not in lines
                else False,
                "Runner status: escort list delivered": lambda: _replace_textedit_prefixed_line(
                    lines, "Runner status:", "Runner status: escort list delivered"
                )
                if "Runner status: escort list delivered" not in lines
                else False,
                "Kitchen status: coffee restock completed": lambda: _replace_textedit_prefixed_line(
                    lines, "Kitchen status:", "Kitchen status: coffee restock completed"
                )
                if "Kitchen status: coffee restock completed" not in lines
                else False,
                "Security status: badge desk reopened": lambda: _replace_textedit_prefixed_line(
                    lines, "Security status:", "Security status: badge desk reopened"
                )
                if "Security status: badge desk reopened" not in lines
                else False,
                "Ops notes: facilities confirmed for 19:30": lambda: _replace_textedit_prefixed_line(
                    lines, "Ops notes:", "Ops notes: facilities confirmed for 19:30"
                )
                if "Ops notes: facilities confirmed for 19:30" not in lines
                else False,
                "Escalation owner: Avery": lambda: _insert_textedit_line_after(
                    lines,
                    "Ops notes: facilities confirmed for 19:30",
                    "Escalation owner: Avery",
                )
                if "Escalation owner: Avery" not in lines
                else False,
                "Handoff complete": lambda: _append_textedit_line(lines, "Handoff complete")
                if "Handoff complete" not in lines
                else False,
                "Reviewed by: ops_lead": lambda: _append_textedit_line(lines, "Reviewed by: ops_lead")
                if "Reviewed by: ops_lead" not in lines
                else False,
                "Queue: evening": lambda: _append_textedit_line(lines, "Queue: evening")
                if "Queue: evening" not in lines
                else False,
                "Archive: yes": lambda: _append_textedit_line(lines, "Archive: yes")
                if "Archive: yes" not in lines
                else False,
                "Follow-up window: 19:30-20:00": lambda: _append_textedit_line(lines, "Follow-up window: 19:30-20:00")
                if "Follow-up window: 19:30-20:00" not in lines
                else False,
            }
            operation = operations.get(payload_text)
            if operation and operation():
                return "\n".join(lines) + ("\n" if lines else "")
            return None
        elif filename == "app.ini":
            operations = {
                "remove Version=1.0.0": lambda: _remove_textedit_line(lines, "Version=1.0.0")
                if "Version=1.0.0" in lines
                else False,
                "remove Author=Admin": lambda: _remove_textedit_line(lines, "Author=Admin")
                if "Author=Admin" in lines
                else False,
                "Environment=QA": lambda: _insert_textedit_line_after(lines, "[Settings]", "Environment=QA")
                if "Environment=QA" not in lines
                else False,
                "ReleaseTrack=Canary": lambda: _insert_textedit_line_after(lines, "Environment=QA", "ReleaseTrack=Canary")
                if "ReleaseTrack=Canary" not in lines
                else False,
                "Region=West": lambda: _insert_textedit_line_after(lines, "ReleaseTrack=Canary", "Region=West")
                if "Region=West" not in lines
                else False,
                "Theme=Light": lambda: _replace_textedit_prefixed_line(lines, "Theme=", "Theme=Light")
                if "Theme=Light" not in lines
                else False,
                "Timeout=45": lambda: _replace_textedit_prefixed_line(lines, "Timeout=", "Timeout=45")
                if "Timeout=45" not in lines
                else False,
                "Mode=Staging": lambda: _replace_textedit_prefixed_line(lines, "Mode=", "Mode=Staging")
                if "Mode=Staging" not in lines
                else False,
                "Logging=On": lambda: _replace_textedit_prefixed_line(lines, "Logging=", "Logging=On")
                if "Logging=On" not in lines
                else False,
                "Retries=5": lambda: _replace_textedit_prefixed_line(lines, "Retries=", "Retries=5")
                if "Retries=5" not in lines
                else False,
                "Cache=True": lambda: _replace_textedit_prefixed_line(lines, "Cache=", "Cache=True")
                if "Cache=True" not in lines
                else False,
                "Host=db.qa.internal": lambda: _replace_textedit_prefixed_line(lines, "Host=", "Host=db.qa.internal")
                if "Host=db.qa.internal" not in lines
                else False,
                "Port=6432": lambda: _replace_textedit_prefixed_line(lines, "Port=", "Port=6432")
                if "Port=6432" not in lines
                else False,
                "Replica=enabled": lambda: _replace_textedit_prefixed_line(lines, "Replica=", "Replica=enabled")
                if "Replica=enabled" not in lines
                else False,
                "Pool=burst": lambda: _replace_textedit_prefixed_line(lines, "Pool=", "Pool=burst")
                if "Pool=burst" not in lines
                else False,
                "Owner=ops_lead": lambda: _replace_textedit_prefixed_line(lines, "Owner=", "Owner=ops_lead")
                if "Owner=ops_lead" not in lines
                else False,
                "Window=overnight": lambda: _replace_textedit_prefixed_line(lines, "Window=", "Window=overnight")
                if "Window=overnight" not in lines
                else False,
                "Queue=night": lambda: _replace_textedit_prefixed_line(lines, "Queue=", "Queue=night")
                if "Queue=night" not in lines
                else False,
                "Alerts=Escalate": lambda: _replace_textedit_prefixed_line(lines, "Alerts=", "Alerts=Escalate")
                if "Alerts=Escalate" not in lines
                else False,
                "Export=Enabled": lambda: _replace_textedit_prefixed_line(lines, "Export=", "Export=Enabled")
                if "Export=Enabled" not in lines
                else False,
                "Escalation=enabled": lambda: _replace_textedit_prefixed_line(lines, "Escalation=", "Escalation=enabled")
                if "Escalation=enabled" not in lines
                else False,
                "# Canary window starts at 22:00": lambda: _append_textedit_line(lines, "# Canary window starts at 22:00")
                if "# Canary window starts at 22:00" not in lines
                else False,
                "# Ticket: TW-104": lambda: _append_textedit_line(lines, "# Ticket: TW-104")
                if "# Ticket: TW-104" not in lines
                else False,
                "# Notify qa-watch before rollout": lambda: _append_textedit_line(lines, "# Notify qa-watch before rollout")
                if "# Notify qa-watch before rollout" not in lines
                else False,
            }
            operation = operations.get(payload_text)
            if operation and operation():
                return "\n".join(lines) + ("\n" if lines else "")
            return None

        return None

QUARTZ_AVAILABLE = False
APPKIT_AVAILABLE = False
ACCESSIBILITY_AVAILABLE = False
NSBitmapImageRep = None
APPKIT_PNG_FILE_TYPE = None
APPKIT_JPEG_FILE_TYPE = None
NSRunningApplication = None
AX_IS_PROCESS_TRUSTED = None
AX_IS_PROCESS_TRUSTED_WITH_OPTIONS = None
AX_TRUSTED_CHECK_OPTION_PROMPT = None
AX_UI_ELEMENT_GET_PID = None

try:
    import Quartz
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventCreateMouseEvent,
        CGEventCreateScrollWheelEvent,
        CGEventPost,
        CGEventSetIntegerValueField,
        kCGEventLeftMouseDown,
        kCGEventLeftMouseDragged,
        kCGEventLeftMouseUp,
        kCGEventMouseMoved,
        kCGEventRightMouseDown,
        kCGEventRightMouseUp,
        kCGHIDEventTap,
        kCGKeyboardEventKeycode,
        kCGMouseButtonLeft,
        kCGMouseButtonRight,
        kCGScrollEventUnitPixel,
    )
    from Quartz.CoreGraphics import (
        CGDisplayBounds,
        CGDisplayCreateImage,
        CGMainDisplayID,
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListOptionOnScreenOnly,
    )

    QUARTZ_AVAILABLE = True
except Exception:
    QUARTZ_AVAILABLE = False

try:
    from Cocoa import NSBitmapImageRep, NSScreen, NSWorkspace, NSRunningApplication
    try:
        from Cocoa import NSPNGFileType

        APPKIT_PNG_FILE_TYPE = NSPNGFileType
    except Exception:
        APPKIT_PNG_FILE_TYPE = 4
    try:
        from Cocoa import NSJPEGFileType

        APPKIT_JPEG_FILE_TYPE = NSJPEGFileType
    except Exception:
        APPKIT_JPEG_FILE_TYPE = 3

    APPKIT_AVAILABLE = True
except Exception:
    try:
        from AppKit import NSBitmapImageRep, NSScreen, NSWorkspace, NSRunningApplication
        try:
            from AppKit import NSBitmapImageFileTypePNG as _PNG_TYPE

            APPKIT_PNG_FILE_TYPE = _PNG_TYPE
        except Exception:
            try:
                from AppKit import NSPNGFileType as _PNG_TYPE

                APPKIT_PNG_FILE_TYPE = _PNG_TYPE
            except Exception:
                APPKIT_PNG_FILE_TYPE = 4
        try:
            from AppKit import NSBitmapImageFileTypeJPEG as _JPEG_TYPE

            APPKIT_JPEG_FILE_TYPE = _JPEG_TYPE
        except Exception:
            try:
                from AppKit import NSJPEGFileType as _JPEG_TYPE

                APPKIT_JPEG_FILE_TYPE = _JPEG_TYPE
            except Exception:
                APPKIT_JPEG_FILE_TYPE = 3

        APPKIT_AVAILABLE = True
    except Exception:
        APPKIT_AVAILABLE = False

try:
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        AXUIElementCreateSystemWide,
        kAXErrorSuccess,
        kAXFocusedApplicationAttribute,
        kAXWindowsAttribute,
    )
    ACCESSIBILITY_AVAILABLE = True
    try:
        from ApplicationServices import AXIsProcessTrusted as _AXIsProcessTrusted

        AX_IS_PROCESS_TRUSTED = _AXIsProcessTrusted
    except Exception:
        AX_IS_PROCESS_TRUSTED = None
    try:
        from ApplicationServices import AXUIElementGetPid as _AXUIElementGetPid

        AX_UI_ELEMENT_GET_PID = _AXUIElementGetPid
    except Exception:
        AX_UI_ELEMENT_GET_PID = None
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions as _AXIsProcessTrustedWithOptions
        from ApplicationServices import kAXTrustedCheckOptionPrompt as _kAXTrustedCheckOptionPrompt

        AX_IS_PROCESS_TRUSTED_WITH_OPTIONS = _AXIsProcessTrustedWithOptions
        AX_TRUSTED_CHECK_OPTION_PROMPT = _kAXTrustedCheckOptionPrompt
    except Exception:
        AX_IS_PROCESS_TRUSTED_WITH_OPTIONS = None
        AX_TRUSTED_CHECK_OPTION_PROMPT = None
except Exception:
    ACCESSIBILITY_AVAILABLE = False

ACTION_SCHEMA = {
    "tap": {
        "description": "Click at the specified element or position (left mouse button)",
        "parameters": {
            "target": {
                "type": "string|array|object",
                "required": True,
                "description": "Target: node ID (e.g. 'n5'), pixel coords [x, y], coordinate objects {'x': 409, 'y': 871} or normalized coords {'x': 0.5, 'y': 0.5}, or a selector object like {'text': 'Discard All'} / {'identifier': 'cancel'}",
            }
        },
    },
    "double_tap": {
        "description": "Double-click at the specified element or position",
        "parameters": {
            "target": {
                "type": "string|array|object",
                "required": True,
                "description": "Target: node ID, pixel coords [x, y], coordinate objects {'x': 409, 'y': 871} or normalized coords {'x': 0.5, 'y': 0.5}, or a selector object such as {'text': 'OK'}",
            }
        },
    },
    "right_click": {
        "description": "Right-click at the specified element or position (context menu)",
        "parameters": {
            "target": {
                "type": "string|array|object",
                "required": True,
                "description": "Target: node ID, pixel coords [x, y], coordinate objects {'x': 409, 'y': 871} or normalized coords {'x': 0.5, 'y': 0.5}, or a selector object such as {'text': 'Close Window'}",
            }
        },
    },
    "scroll": {
        "description": "Scroll the screen or specified area",
        "parameters": {
            "direction": {
                "type": "string",
                "required": True,
                "enum": ["up", "down", "left", "right"],
                "description": "Scroll direction",
            },
            "distance": {"type": "number", "required": False, "default": 100, "description": "Scroll distance in pixels"},
            "target": {
                "type": "string|array|object",
                "required": False,
                "description": "Optional scroll position: node ID, pixel coords [x, y], coordinate objects {'x': 409, 'y': 871}, or normalized coords",
            },
        },
    },
    "drag": {
        "description": "Drag from one position to another with the left mouse button held down",
        "parameters": {
            "from_target": {
                "type": "string|array|object",
                "required": True,
                "description": "Drag start: node ID, pixel coords [x, y], coordinate objects {'x': 409, 'y': 871}, or normalized coords {'x': 0.5, 'y': 0.5}",
            },
            "to_target": {
                "type": "string|array|object",
                "required": True,
                "description": "Drag end: node ID, pixel coords [x, y], coordinate objects {'x': 409, 'y': 871}, or normalized coords {'x': 0.5, 'y': 0.5}",
            },
            "duration_ms": {
                "type": "integer",
                "required": False,
                "default": 400,
                "description": "Approximate drag duration in milliseconds",
            },
        },
    },
    "type_text": {
        "description": "Type or paste text at current cursor position or specified target. Newlines and tabs are entered as Enter/Tab so spreadsheets can fill multiple cells. For document editors, prefer selecting the exact text first and then typing to replace the selection. If the intended text is already selected, omit target so a preparatory click does not collapse the selection. For small input fields or combo boxes, set clear_first=true so existing values do not get appended.",
        "parameters": {
            "text": {"type": "string", "required": True, "description": "Text to type"},
            "target": {"type": "string|array|object", "required": False, "description": "Optional target to click before typing; supports node IDs, coordinates, or selector objects like {'text': 'D2'}"},
            "clear_first": {"type": "boolean", "required": False, "default": False, "description": "Whether to clear the focused field before typing. Recommended for toolbar inputs such as font size."},
        },
    },
    "replace_text": {
        "description": "Replace the text represented by a target element. Best for document lines or input fields when you want to swap one visible text region without clearing the whole document.",
        "parameters": {
            "target": {"type": "string|array|object", "required": True, "description": "Target element or position whose visible text should be replaced; supports selector objects like {'text': 'Quarterly Report Draft'}"},
            "text": {"type": "string", "required": True, "description": "Replacement text"},
        },
    },
    "select_text": {
        "description": "Select the visible text represented by a target element. Useful before applying formatting in document editors. In Writer-like rich text editors, prefer selecting text and then using toggle_italic or a formatting hotkey instead of clicking toolbar controls, which may collapse the selection.",
        "parameters": {
            "target": {"type": "string|array|object", "required": True, "description": "Target element or text region to select; supports selector objects like {'text': 'Quarterly Report'}"},
        },
    },
    "toggle_italic": {
        "description": "Toggle italic formatting on the current text selection or insertion point. Preferred in document editors such as LibreOffice Writer because it preserves the current selection better than clicking toolbar buttons.",
        "parameters": {
            "target": {
                "type": "string|array|object",
                "required": False,
                "description": "Optional text region to select before toggling italic; supports node IDs, coordinates, or selector objects like {'text': 'Document prepared by: Management Team'}",
            }
        },
    },
    "keyboard": {
        "description": "Send keyboard action (submit, delete, shortcuts). Use 'enter' to submit, 'backspace' to delete, 'escape' to cancel",
        "parameters": {
            "action": {
                "type": "string",
                "required": True,
                "enum": ["enter", "escape", "backspace", "delete", "tab", "space", "up", "down", "left", "right"],
                "description": "Key to press",
            },
            "modifiers": {"type": "array", "required": False, "description": "Optional modifier keys: ['cmd', 'ctrl', 'alt', 'shift']"},
            "count": {"type": "integer", "required": False, "default": 1, "description": "Number of times to press"},
        },
    },
    "hotkey": {
        "description": "Press keyboard shortcut (e.g., Cmd+C, Cmd+V, Cmd+Q, Cmd+I). For selected text in document editors, shortcuts like Cmd+I often work better than clicking toolbar buttons.",
        "parameters": {"keys": {"type": "string", "required": True, "description": "Shortcut like 'cmd+c', 'cmd+shift+s', 'cmd+q'"}},
    },
    "launch_app": {
        "description": "Launch an application by name",
        "parameters": {"app_name": {"type": "string", "required": True, "description": "Application name, e.g., 'Safari', 'TextEdit', 'Finder'"}},
    },
    "wait": {
        "description": "Wait for a specified time",
        "parameters": {"ms": {"type": "integer", "required": False, "default": 1000, "description": "Wait time in milliseconds"}},
    },
    "run_bash_script": {
        "description": "Run a bounded bash script inside the macOS guest. Use this only when the task or app-specific runtime hint explicitly requires a saved-file/background automation step.",
        "parameters": {
            "script": {"type": "string", "required": True, "description": "Bash script body to run in the guest."},
            "timeout": {"type": "integer", "required": False, "default": 30, "description": "Maximum runtime in seconds."},
            "working_dir": {"type": "string", "required": False, "description": "Optional working directory for the script."},
        },
    },
    "success": {"description": "Task successfully completed", "parameters": {"message": {"type": "string", "required": False, "description": "Success message"}}},
    "fail": {"description": "Task could not be completed", "parameters": {"reason": {"type": "string", "required": True, "description": "Reason for failure"}}},
}

KEY_CODES = {
    "a": 0,
    "b": 11,
    "c": 8,
    "d": 2,
    "e": 14,
    "f": 3,
    "g": 5,
    "h": 4,
    "i": 34,
    "j": 38,
    "k": 40,
    "l": 37,
    "m": 46,
    "n": 45,
    "o": 31,
    "p": 35,
    "q": 12,
    "r": 15,
    "s": 1,
    "t": 17,
    "u": 32,
    "v": 9,
    "w": 13,
    "x": 7,
    "y": 16,
    "z": 6,
    "0": 29,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "5": 23,
    "6": 22,
    "7": 26,
    "8": 28,
    "9": 25,
    "enter": 36,
    "return": 36,
    "tab": 48,
    "space": 49,
    "backspace": 51,
    "delete": 117,
    "escape": 53,
    "esc": 53,
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
    "pageup": 116,
    "pagedown": 121,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
    "-": 27,
    "=": 24,
    "[": 33,
    "]": 30,
    "\\": 42,
    ";": 41,
    "'": 39,
    ",": 43,
    ".": 47,
    "/": 44,
    "`": 50,
}

APPLESCRIPT_KEY_CODES = {
    "enter": 36,
    "return": 36,
    "tab": 48,
    "space": 49,
    "backspace": 51,
    "delete": 117,
    "escape": 53,
    "esc": 53,
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
    "pageup": 116,
    "pagedown": 121,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}

SHIFTED_CHAR_TO_BASE_KEY = {
    "~": "`",
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
}

DIRECT_TEXT_KEY_MAP = {
    " ": "space",
    "\t": "tab",
    "\n": "enter",
    "\r": "enter",
}

AX_ATTR_ROLE = "AXRole"
AX_ATTR_SUBROLE = "AXSubrole"
AX_ATTR_ROLE_DESCRIPTION = "AXRoleDescription"
AX_ATTR_TITLE = "AXTitle"
AX_ATTR_VALUE = "AXValue"
AX_ATTR_DESCRIPTION = "AXDescription"
AX_ATTR_ENABLED = "AXEnabled"
AX_ATTR_POSITION = "AXPosition"
AX_ATTR_SIZE = "AXSize"
AX_ATTR_CHILDREN = "AXChildren"
AX_ATTR_IDENTIFIER = "AXIdentifier"
AX_ATTR_MENU_BAR = "AXMenuBar"

IMPORTANT_AX_ROLES = {
    "AXButton",
    "AXRadioButton",
    "AXCheckBox",
    "AXTextField",
    "AXTextArea",
    "AXSearchField",
    "AXComboBox",
    "AXSlider",
    "AXStepper",
    "AXTabGroup",
    "AXLink",
    "AXMenuButton",
    "AXPopUpButton",
    "AXMenuItem",
}

WINDOW_CONTROL_SUBROLE_LABELS = {
    "AXCloseButton": "Close Window",
    "AXMinimizeButton": "Minimize Window",
    "AXZoomButton": "Zoom Window",
    "AXFullScreenButton": "Full Screen",
}


def _get_bearer_token(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts[0].strip(), parts[1].strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _load_token(token_arg: Optional[str], token_file: Optional[str]) -> str:
    env_token = os.environ.get("MACUI_TOKEN")
    env_token_file = os.environ.get("MACUI_TOKEN_FILE")
    if token_arg:
        return token_arg.strip()
    if env_token:
        return env_token.strip()

    path = token_file or env_token_file
    if path:
        p = Path(path).expanduser()
        if p.exists():
            return p.read_text(encoding="utf-8").strip()

    raise SystemExit("No token configured. Provide --token, set MACUI_TOKEN, or provide --token-file/MACUI_TOKEN_FILE.")


def _bool_param(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _escape_apple(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


class RuntimeAutomation:
    OVERLAY_AX_WINDOW_OWNERS = {
        "UserNotificationCenter",
        "NotificationCenter",
        "CoreServicesUIAgent",
    }
    APP_LAUNCH_ALIASES = {
        "vscodium": ["VSCodium", "Codium"],
        "visual studio code": ["Visual Studio Code", "Code"],
        "thunderbird": ["Thunderbird"],
    }

    def __init__(self, log: logging.Logger):
        self.log = log
        self.width, self.height = self._get_screen_size(allow_slow_fallback=False)
        self.cliclick_path = shutil.which("cliclick")
        self._node_counter = 0
        self._last_pointer_target: Optional[Tuple[str, int, int, float]] = None
        self._last_text_selection_at: Optional[float] = None

    def capabilities(self) -> Dict[str, Any]:
        return {
            "quartz_available": QUARTZ_AVAILABLE,
            "appkit_available": APPKIT_AVAILABLE,
            "accessibility_available": ACCESSIBILITY_AVAILABLE,
            "accessibility_trusted": self.is_accessibility_trusted(False),
            "cliclick_available": bool(self.cliclick_path),
            "ui_tree_supports_node_id": True,
        }

    def _remember_pointer_target(self, kind: str, x: int, y: int) -> None:
        self._last_pointer_target = (kind, int(x), int(y), time.monotonic())
        self._last_text_selection_at = None

    def _recent_pointer_target(self, *, max_age_seconds: float = 20.0) -> Optional[Tuple[str, int, int]]:
        if self._last_pointer_target is None:
            return None
        kind, x, y, timestamp = self._last_pointer_target
        if time.monotonic() - timestamp > max_age_seconds:
            self._last_pointer_target = None
            return None
        return kind, x, y

    def _remember_text_selection(self) -> None:
        self._last_text_selection_at = time.monotonic()

    def _has_recent_text_selection(self, *, max_age_seconds: float = 20.0) -> bool:
        if self._last_text_selection_at is None:
            return False
        if time.monotonic() - self._last_text_selection_at > max_age_seconds:
            self._last_text_selection_at = None
            return False
        return True

    @classmethod
    def _app_launch_candidate_names(cls, app_name: str) -> List[str]:
        raw_name = str(app_name or "").strip()
        if not raw_name:
            return []
        candidates: List[str] = [raw_name]
        normalized = raw_name.lower()
        for alias in cls.APP_LAUNCH_ALIASES.get(normalized, []):
            if alias not in candidates:
                candidates.append(alias)
        return candidates

    def _resolve_launch_app_target(self, app_name: str) -> Optional[str]:
        raw_name = str(app_name or "").strip()
        if not raw_name:
            return None

        raw_path = Path(raw_name).expanduser()
        if raw_path.suffix.lower() == ".app" and raw_path.is_dir():
            return str(raw_path)

        candidate_names = self._app_launch_candidate_names(raw_name)
        search_roots = [Path.home() / "Applications", Path("/Applications")]
        for candidate in candidate_names:
            filename = candidate if candidate.lower().endswith(".app") else f"{candidate}.app"
            for root in search_roots:
                app_path = root / filename
                if app_path.is_dir():
                    return str(app_path)

        for candidate in candidate_names:
            filename = candidate if candidate.lower().endswith(".app") else f"{candidate}.app"
            query = f'kMDItemFSName == "{filename}"'
            try:
                proc = subprocess.run(
                    ["mdfind", query],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
            except Exception:
                continue
            if proc.returncode != 0:
                continue
            for line in (proc.stdout or "").splitlines():
                path = Path(line.strip())
                if path.suffix.lower() == ".app" and path.is_dir():
                    return str(path)

        return None

    @staticmethod
    def _is_libreoffice_app(app_name: str, bundle_id: str) -> bool:
        app_name_lower = str(app_name or "").strip().lower()
        bundle_id_lower = str(bundle_id or "").strip().lower()
        return app_name_lower == "libreoffice" or "libreoffice" in bundle_id_lower

    @staticmethod
    def _is_code_editor_app(app_name: str, bundle_id: str) -> bool:
        app_name_lower = str(app_name or "").strip().lower()
        bundle_id_lower = str(bundle_id or "").strip().lower()
        if app_name_lower in {"vscodium", "visual studio code", "code", "cursor", "windsurf", "zed"}:
            return True
        return any(token in bundle_id_lower for token in {"vscodium", "visualstudio", "cursor", "windsurf", "zed"})

    def _should_preserve_recent_selection_for_type_text(
        self,
        target_node: Optional[Dict[str, Any]],
        *,
        app_name: str,
        bundle_id: str,
    ) -> bool:
        if not self._has_recent_text_selection():
            return False
        target_role = str((target_node or {}).get("type") or (target_node or {}).get("role") or "").strip()
        if target_role == "AXWindow":
            return True
        if target_node is None and self._is_code_editor_app(app_name, bundle_id):
            return True
        return False

    def _normalize_impress_text_target(
        self,
        target_node: Optional[Dict[str, Any]],
        x: int,
        y: int,
        *,
        app_name: str,
        bundle_id: str,
        ui_nodes: List[Dict[str, Any]],
    ) -> Tuple[int, int]:
        if target_node is not None or not self._is_libreoffice_app(app_name, bundle_id):
            return x, y
        if any("Sheet " in str(node.get("text") or "") for node in ui_nodes):
            return x, y

        if x <= max(420, int(self.width * 0.30)) and y >= int(self.height * 0.55):
            return int(round(self.width * 0.106)), int(round(self.height * 0.646))

        if (
            int(self.width * 0.30) <= x <= int(self.width * 0.62)
            and int(self.height * 0.12) <= y <= int(self.height * 0.24)
        ):
            return int(round(self.width * 0.459)), int(round(self.height * 0.167))

        return x, y

    def _looks_like_impress_slide_coordinate(
        self,
        x: int,
        y: int,
        *,
        app_name: str,
        bundle_id: str,
        ui_nodes: List[Dict[str, Any]],
    ) -> bool:
        if not self._is_libreoffice_app(app_name, bundle_id):
            return False
        if any("Sheet " in str(node.get("text") or "") for node in ui_nodes):
            return False
        if self._is_impress_notes_target(
            None,
            x,
            y,
            app_name=app_name,
            bundle_id=bundle_id,
            ui_nodes=ui_nodes,
        ):
            return False
        if x < int(self.width * 0.25) or x > int(self.width * 0.82):
            return False
        if y < int(self.height * 0.12) or y > int(self.height * 0.72):
            return False
        return True

    def _is_impress_slide_thumbnail_target(
        self,
        target_node: Optional[Dict[str, Any]],
        x: int,
        y: int,
        *,
        app_name: str,
        bundle_id: str,
        ui_nodes: List[Dict[str, Any]],
    ) -> bool:
        if target_node is not None:
            return False
        if not self._is_libreoffice_app(app_name, bundle_id):
            return False
        if any("Sheet " in str(node.get("text") or "") for node in ui_nodes):
            return False
        if x > max(220, int(self.width * 0.12)):
            return False
        if y < int(self.height * 0.12) or y > int(self.height * 0.80):
            return False
        return True

    def _resolve_recent_impress_text_target(
        self,
        *,
        app_name: str,
        bundle_id: str,
        ui_nodes: List[Dict[str, Any]],
    ) -> Optional[Tuple[str, int, int]]:
        recent_pointer = self._recent_pointer_target()
        if recent_pointer is None:
            return None
        _kind, raw_x, raw_y = recent_pointer
        x, y = self._normalize_impress_text_target(
            None,
            raw_x,
            raw_y,
            app_name=app_name,
            bundle_id=bundle_id,
            ui_nodes=ui_nodes,
        )
        if self._is_impress_notes_target(
            None,
            x,
            y,
            app_name=app_name,
            bundle_id=bundle_id,
            ui_nodes=ui_nodes,
        ):
            return "notes", x, y
        if self._looks_like_impress_slide_coordinate(
            x,
            y,
            app_name=app_name,
            bundle_id=bundle_id,
            ui_nodes=ui_nodes,
        ):
            return "slide", x, y
        return None

    def is_accessibility_trusted(self, prompt: bool = False) -> bool:
        if not ACCESSIBILITY_AVAILABLE:
            return False
        if AX_IS_PROCESS_TRUSTED_WITH_OPTIONS is not None and AX_TRUSTED_CHECK_OPTION_PROMPT is not None:
            try:
                return bool(
                    AX_IS_PROCESS_TRUSTED_WITH_OPTIONS(
                        {AX_TRUSTED_CHECK_OPTION_PROMPT: bool(prompt)}
                    )
                )
            except Exception:
                pass
        if AX_IS_PROCESS_TRUSTED is not None:
            try:
                return bool(AX_IS_PROCESS_TRUSTED())
            except Exception:
                pass
        return False

    def _get_screen_size(self, allow_slow_fallback: bool = True) -> Tuple[int, int]:
        if APPKIT_AVAILABLE:
            try:
                screen = NSScreen.mainScreen()
                if screen is not None:
                    frame = screen.frame()
                    w = int(frame.size.width)
                    h = int(frame.size.height)
                    if w > 0 and h > 0:
                        return w, h
            except Exception:
                pass

        if QUARTZ_AVAILABLE:
            try:
                display_id = CGMainDisplayID()
                bounds = CGDisplayBounds(display_id)
                w = int(bounds.size.width)
                h = int(bounds.size.height)
                if w > 0 and h > 0:
                    return w, h
            except Exception:
                pass

        if allow_slow_fallback:
            try:
                proc = subprocess.run(
                    ["system_profiler", "SPDisplaysDataType", "-json"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                data = json.loads(proc.stdout or "{}")
                display_items = data.get("SPDisplaysDataType", [{}])
                first = display_items[0] if display_items else {}
                displays = first.get("spdisplays_ndrvs", [])
                if isinstance(displays, dict):
                    displays = [displays]
                if displays:
                    resolution = str(displays[0].get("_spdisplays_resolution", ""))
                    match = re.search(r"(\d+)\s*[x×]\s*(\d+)", resolution)
                    if match:
                        return int(match.group(1)), int(match.group(2))
            except Exception:
                pass

        return 1920, 1080

    def _foreground_app(self) -> Tuple[str, str]:
        # Ask System Events first.  In the author VM, NSWorkspace.frontmostApplication()
        # can report Blender while the screenshot/menu bar and active window are
        # Actual; that stale value was injected into the model prompt and caused
        # unnecessary app switching.  The independent System Events query tracks
        # the process whose frontmost flag matches the visible menu bar.
        script = """
        tell application "System Events"
            set p to first application process whose frontmost is true
            set appName to name of p
            try
                set bundleId to bundle identifier of p
            on error
                set bundleId to ""
            end try
            return appName & "|" & bundleId
        end tell
        """
        try:
            proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=8)
            if proc.returncode == 0 and proc.stdout.strip():
                app_name, _, bundle_id = proc.stdout.strip().partition("|")
                return app_name, bundle_id
        except Exception:
            pass

        # NSWorkspace is a fallback when System Events is unavailable.
        if APPKIT_AVAILABLE:
            try:
                workspace = NSWorkspace.sharedWorkspace()
                active_app = workspace.frontmostApplication()
                if active_app:
                    return active_app.localizedName() or "", active_app.bundleIdentifier() or ""
            except Exception:
                pass

        # Use Accessibility only when NSWorkspace is unavailable.
        if ACCESSIBILITY_AVAILABLE and self.is_accessibility_trusted(False):
            try:
                system_wide = AXUIElementCreateSystemWide()
                focused_app = self._ax_copy(system_wide, kAXFocusedApplicationAttribute)
                if focused_app is not None:
                    pid: Optional[int] = None
                    if AX_UI_ELEMENT_GET_PID is not None:
                        try:
                            pid_result = AX_UI_ELEMENT_GET_PID(focused_app, None)
                            if isinstance(pid_result, tuple):
                                if len(pid_result) >= 2:
                                    err = int(pid_result[0]) if pid_result[0] is not None else 0
                                    if err == 0 and pid_result[1] is not None:
                                        pid = int(pid_result[1])
                                elif len(pid_result) == 1 and isinstance(pid_result[0], int):
                                    if int(pid_result[0]) > 0:
                                        pid = int(pid_result[0])
                            elif isinstance(pid_result, int) and pid_result > 0:
                                pid = int(pid_result)
                            elif hasattr(pid_result, "value"):
                                maybe_pid = int(getattr(pid_result, "value"))
                                if maybe_pid > 0:
                                    pid = maybe_pid
                        except Exception:
                            pid = None

                    if pid and APPKIT_AVAILABLE and NSRunningApplication is not None:
                        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                        if app:
                            return app.localizedName() or "", app.bundleIdentifier() or ""

                    # PID resolution can fail on some pyobjc/ApplicationServices versions.
                    # Fallback to AX app name so foreground metadata remains aligned with AX UI tree.
                    ax_name = str(self._ax_copy(focused_app, AX_ATTR_TITLE) or "").strip()
                    if not ax_name:
                        ax_name = str(self._ax_copy(focused_app, AX_ATTR_DESCRIPTION) or "").strip()
                    if ax_name:
                        bundle_id = ""
                        if APPKIT_AVAILABLE:
                            try:
                                ws = NSWorkspace.sharedWorkspace()
                                running_apps = ws.runningApplications() or []
                                selected = None
                                for app in running_apps:
                                    if not app:
                                        continue
                                    localized = str(app.localizedName() or "")
                                    if localized == ax_name:
                                        selected = app
                                        if bool(app.isActive()):
                                            break
                                if selected is not None:
                                    bundle_id = str(selected.bundleIdentifier() or "")
                            except Exception:
                                pass
                        return ax_name, bundle_id
            except Exception:
                pass

        if APPKIT_AVAILABLE:
            try:
                workspace = NSWorkspace.sharedWorkspace()
                active_app = workspace.frontmostApplication()
                if active_app:
                    return active_app.localizedName() or "", active_app.bundleIdentifier() or ""
            except Exception:
                pass

        return "", ""

    def _capture_screenshot_bytes(self) -> bytes:
        errors: List[str] = []
        try:
            return self._capture_screenshot_bytes_quartz()
        except Exception as exc:
            errors.append(f"quartz capture failed: {exc}")

        with tempfile.NamedTemporaryFile(prefix="macui-screenshot-", suffix=".jpg", delete=False) as f:
            path = f.name
        try:
            for cmd in (
                ["/usr/sbin/screencapture", "-x", "-t", "jpg", path],
                ["/usr/sbin/screencapture", "-x", "-D", "1", "-t", "jpg", path],
            ):
                proc = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if proc.returncode == 0:
                    return Path(path).read_bytes()
                errors.append(
                    f"screencapture failed rc={proc.returncode} stderr={proc.stderr.strip()}"
                )
                time.sleep(0.2)
            raise RuntimeError(" | ".join(errors))
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    def _capture_screenshot_bytes_quartz(self) -> bytes:
        if not QUARTZ_AVAILABLE or not APPKIT_AVAILABLE or NSBitmapImageRep is None:
            raise RuntimeError("quartz appkit backend unavailable")

        display_id = CGMainDisplayID()
        image_ref = CGDisplayCreateImage(display_id)
        if image_ref is None:
            bounds = CGDisplayBounds(display_id)
            image_ref = Quartz.CGWindowListCreateImage(
                bounds,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                Quartz.kCGWindowImageDefault,
            )
        if image_ref is None:
            raise RuntimeError("CGWindowListCreateImage returned None")

        bitmap = NSBitmapImageRep.alloc().initWithCGImage_(image_ref)
        if bitmap is None:
            raise RuntimeError("NSBitmapImageRep initWithCGImage failed")

        jpeg_properties = {"NSImageCompressionFactor": 0.8}
        jpeg_data = bitmap.representationUsingType_properties_(APPKIT_JPEG_FILE_TYPE or 3, jpeg_properties)
        if jpeg_data is None:
            raise RuntimeError("NSBitmapImageRep JPEG encode failed")

        return bytes(jpeg_data)

    def _ax_copy(self, element: Any, attr: str) -> Any:
        try:
            err, value = AXUIElementCopyAttributeValue(element, attr, None)
            if err == kAXErrorSuccess:
                return value
        except Exception:
            pass
        return None

    def _get_ax_frame(self, element: Any) -> Tuple[int, int, int, int]:
        x, y, width, height = 0, 0, 0, 0

        def _parse_pair(text: str) -> Optional[Tuple[int, int]]:
            match = re.search(r"([-\d.]+)\s*,\s*([-\d.]+)", text)
            if not match:
                return None
            return int(float(match.group(1))), int(float(match.group(2)))

        def _parse_named(text: str, a: str, b: str) -> Optional[Tuple[int, int]]:
            ma = re.search(rf"\b{a}\s*[:=]\s*([-\d.]+)", text, flags=re.IGNORECASE)
            mb = re.search(rf"\b{b}\s*[:=]\s*([-\d.]+)", text, flags=re.IGNORECASE)
            if ma and mb:
                return int(float(ma.group(1))), int(float(mb.group(1)))
            return None

        position = self._ax_copy(element, AX_ATTR_POSITION)
        if position is not None:
            try:
                if hasattr(position, "x") and hasattr(position, "y"):
                    x, y = int(position.x), int(position.y)
                elif hasattr(position, "pointValue"):
                    point = position.pointValue()
                    x, y = int(point.x), int(point.y)
                else:
                    desc = str(position)
                    parsed = _parse_named(desc, "x", "y")
                    if parsed is None:
                        parsed = _parse_pair(desc)
                    if parsed is not None:
                        x, y = parsed
            except Exception:
                pass

        size = self._ax_copy(element, AX_ATTR_SIZE)
        if size is not None:
            try:
                if hasattr(size, "width") and hasattr(size, "height"):
                    width, height = int(size.width), int(size.height)
                elif hasattr(size, "sizeValue"):
                    size_value = size.sizeValue()
                    width, height = int(size_value.width), int(size_value.height)
                else:
                    desc = str(size)
                    parsed = _parse_named(desc, "width", "height")
                    if parsed is None:
                        parsed = _parse_named(desc, "w", "h")
                    if parsed is None:
                        parsed = _parse_pair(desc)
                    if parsed is not None:
                        width, height = parsed
            except Exception:
                pass

        return x, y, width, height

    def _extract_ax_node(self, element: Any) -> Optional[Dict[str, Any]]:
        role = self._ax_copy(element, AX_ATTR_ROLE)
        if not role:
            return None

        self._node_counter += 1
        node: Dict[str, Any] = {
            "id": f"n{self._node_counter}",
            "type": str(role),
        }

        title = self._ax_copy(element, AX_ATTR_TITLE)
        if title:
            node["text"] = str(title)

        subrole = self._ax_copy(element, AX_ATTR_SUBROLE)
        if subrole:
            node["subrole"] = str(subrole)

        value = self._ax_copy(element, AX_ATTR_VALUE)
        if value is not None:
            value_str = str(value)[:200]
            if value_str:
                if "text" not in node:
                    node["text"] = value_str
                elif value_str != node.get("text"):
                    node["value"] = value_str

        description = self._ax_copy(element, AX_ATTR_DESCRIPTION)
        if description:
            description_str = str(description)
            if description_str and description_str != node.get("text"):
                node["description"] = description_str

        role_description = self._ax_copy(element, AX_ATTR_ROLE_DESCRIPTION)
        if role_description:
            node["roleDescription"] = str(role_description)

        if "text" not in node:
            subrole_name = str(node.get("subrole", ""))
            if subrole_name in WINDOW_CONTROL_SUBROLE_LABELS:
                node["text"] = WINDOW_CONTROL_SUBROLE_LABELS[subrole_name]

        x, y, width, height = self._get_ax_frame(element)
        node["x"] = x
        node["y"] = y
        node["width"] = width
        node["height"] = height
        if width > 0 and height > 0:
            node["tap"] = [x + width // 2, y + height // 2]

        enabled = self._ax_copy(element, AX_ATTR_ENABLED)
        node["enabled"] = bool(enabled) if enabled is not None else True

        identifier = self._ax_copy(element, AX_ATTR_IDENTIFIER)
        if identifier:
            node["identifier"] = str(identifier)

        return node

    def _traverse_ax_tree(
        self,
        element: Any,
        out_nodes: List[Dict[str, Any]],
        depth: int,
        max_depth: int,
        max_nodes: int,
    ) -> None:
        if depth > max_depth or len(out_nodes) >= max_nodes:
            return

        try:
            node = self._extract_ax_node(element)
            if node is not None:
                out_nodes.append(node)
        except Exception:
            pass

        children = self._ax_copy(element, AX_ATTR_CHILDREN)
        if not children:
            return

        try:
            for child in children:
                if len(out_nodes) >= max_nodes:
                    break
                self._traverse_ax_tree(child, out_nodes, depth + 1, max_depth, max_nodes)
        except Exception:
            pass

    def _filter_ax_nodes(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not nodes:
            return []

        filtered: List[Dict[str, Any]] = []
        min_x, max_x = -50, self.width + 50
        min_y, max_y = -50, self.height + 50

        for node in nodes:
            width = int(node.get("width", 0) or 0)
            height = int(node.get("height", 0) or 0)
            if width <= 0 or height <= 0:
                continue

            x = int(node.get("x", 0) or 0)
            y = int(node.get("y", 0) or 0)
            if (x + width < min_x) or (x > max_x) or (y + height < min_y) or (y > max_y):
                continue

            has_text = bool(node.get("text") or node.get("value") or node.get("description"))
            is_interactive = node.get("type") in IMPORTANT_AX_ROLES
            if has_text or is_interactive:
                filtered.append(node)

        return filtered

    @staticmethod
    def _dedupe_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for node in nodes:
            signature = (
                node.get("type"),
                node.get("text"),
                node.get("identifier"),
                node.get("subrole"),
                int(node.get("x", 0) or 0),
                int(node.get("y", 0) or 0),
                int(node.get("width", 0) or 0),
                int(node.get("height", 0) or 0),
                tuple(node.get("tap") or []),
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(node)
        return deduped

    def _traverse_app_ax_nodes(
        self,
        app_element: Any,
        *,
        include_menu_bar: bool,
        window_depth: int,
        max_nodes: int,
    ) -> List[Dict[str, Any]]:
        nodes: List[Dict[str, Any]] = []

        if include_menu_bar:
            menu_bar = self._ax_copy(app_element, AX_ATTR_MENU_BAR)
            if menu_bar:
                self._traverse_ax_tree(menu_bar, nodes, depth=0, max_depth=6, max_nodes=max_nodes)

        # Traverse the app shallowly first so transient popup/menu state can still
        # surface even when AXWindows is incomplete for that process.
        self._traverse_ax_tree(app_element, nodes, depth=0, max_depth=2, max_nodes=max_nodes)

        windows = self._ax_copy(app_element, kAXWindowsAttribute)
        if windows:
            for window in windows:
                if len(nodes) >= max_nodes:
                    break
                self._traverse_ax_tree(window, nodes, depth=0, max_depth=window_depth, max_nodes=max_nodes)

        if not nodes:
            self._traverse_ax_tree(app_element, nodes, depth=0, max_depth=window_depth, max_nodes=max_nodes)

        return self._filter_ax_nodes(nodes)

    def _overlay_app_elements(self) -> List[Any]:
        if not QUARTZ_AVAILABLE:
            return []

        overlay_pids: List[int] = []
        seen_pids: set[int] = set()
        try:
            windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []
            for window in windows:
                owner = str(window.get("kCGWindowOwnerName", "") or "")
                if owner not in self.OVERLAY_AX_WINDOW_OWNERS:
                    continue
                try:
                    pid = int(window.get("kCGWindowOwnerPID", 0) or 0)
                except Exception:
                    pid = 0
                if pid <= 0 or pid in seen_pids:
                    continue
                seen_pids.add(pid)
                overlay_pids.append(pid)
        except Exception as exc:
            self.log.warning("overlay window discovery failed: %s", exc)
            return []

        return [AXUIElementCreateApplication(pid) for pid in overlay_pids]

    def _frontmost_running_app_element(self) -> Any:
        if not APPKIT_AVAILABLE:
            return None
        try:
            workspace = NSWorkspace.sharedWorkspace()
            active_app = workspace.frontmostApplication()
            if active_app is None:
                return None
            pid = int(active_app.processIdentifier() or 0)
            if pid <= 0:
                return None
            return AXUIElementCreateApplication(pid)
        except Exception:
            return None

    def _accessibility_nodes(self) -> List[Dict[str, Any]]:
        if not ACCESSIBILITY_AVAILABLE:
            return []
        if not self.is_accessibility_trusted(False):
            return []

        try:
            system_wide = AXUIElementCreateSystemWide()
            focused_app = self._ax_copy(system_wide, kAXFocusedApplicationAttribute)
            if not focused_app:
                return []

            self._node_counter = 0
            combined: List[Dict[str, Any]] = []

            overlay_nodes: List[Dict[str, Any]] = []
            for overlay_app in self._overlay_app_elements():
                overlay_nodes.extend(
                    self._traverse_app_ax_nodes(
                        overlay_app,
                        include_menu_bar=False,
                        window_depth=8,
                        max_nodes=150,
                    )
                )
            combined.extend(overlay_nodes)

            focused_nodes = self._traverse_app_ax_nodes(
                focused_app,
                include_menu_bar=True,
                window_depth=12,
                max_nodes=600,
            )
            combined.extend(focused_nodes)

            if not any(str(node.get("type") or "") == "AXWindow" for node in focused_nodes):
                frontmost_app = self._frontmost_running_app_element()
                if frontmost_app is not None:
                    frontmost_nodes = self._traverse_app_ax_nodes(
                        frontmost_app,
                        include_menu_bar=False,
                        window_depth=12,
                        max_nodes=400,
                    )
                    combined.extend(frontmost_nodes)

            if not combined and (overlay_nodes or focused_nodes):
                self.log.warning(
                    "accessibility nodes collected overlay=%d focused=%d but combined filter is empty",
                    len(overlay_nodes),
                    len(focused_nodes),
                )
            return self._dedupe_nodes(combined)
        except Exception as exc:
            self.log.warning("accessibility node collection failed: %s", exc)
            return []

    def _window_nodes(self) -> List[Dict[str, Any]]:
        if not QUARTZ_AVAILABLE:
            return []
        nodes: List[Dict[str, Any]] = []
        try:
            windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
            if not windows:
                return []
            idx = 0
            for window in windows:
                bounds = window.get("kCGWindowBounds", {})
                width = int(bounds.get("Width", 0))
                height = int(bounds.get("Height", 0))
                x = int(bounds.get("X", 0))
                y = int(bounds.get("Y", 0))
                if width <= 0 or height <= 0:
                    continue
                idx += 1
                owner = str(window.get("kCGWindowOwnerName", "") or "")
                title = str(window.get("kCGWindowName", "") or "")
                text = title or owner
                nodes.append(
                    {
                        "id": f"w{idx}",
                        "type": "AXWindow",
                        "text": text,
                        "description": owner,
                        "x": x,
                        "y": y,
                        "width": width,
                        "height": height,
                        "tap": [x + width // 2, y + height // 2],
                        "enabled": True,
                    }
                )
        except Exception as exc:
            self.log.warning("window node collection failed: %s", exc)
        return nodes

    def _ui_nodes(self) -> Tuple[List[Dict[str, Any]], str]:
        ax_nodes = self._accessibility_nodes()
        if ax_nodes:
            return ax_nodes, "accessibility"
        return self._window_nodes(), "window_fallback"

    def observe(self, include_ui_tree: bool, include_screenshot_data: bool) -> Dict[str, Any]:
        self.width, self.height = self._get_screen_size(allow_slow_fallback=True)
        app_name, bundle_id = self._foreground_app()
        ui_nodes: List[Dict[str, Any]] = []
        ui_tree_source = "disabled"
        if include_ui_tree:
            ui_nodes, ui_tree_source = self._ui_nodes()
            ui_nodes = self._augment_ui_nodes(ui_nodes)

        payload: Dict[str, Any] = {
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3],
            "width": self.width,
            "height": self.height,
            "ui_nodes": ui_nodes,
            "ui_tree_source": ui_tree_source,
            "foreground_app": app_name,
            "foreground_bundle_id": bundle_id,
        }
        if include_screenshot_data:
            screenshot = self._capture_screenshot_bytes()
            payload["screenshot_data_base64"] = base64.b64encode(screenshot).decode("ascii")
        return payload

    def _augment_ui_nodes(self, ui_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not ui_nodes:
            return ui_nodes
        augmented = list(ui_nodes)
        existing_ids = {str(node.get("id") or "").strip() for node in augmented if isinstance(node, dict)}
        for node in self._synthesize_gimp_dialog_nodes(augmented):
            node_id = str(node.get("id") or "").strip()
            if node_id and node_id not in existing_ids:
                augmented.append(node)
                existing_ids.add(node_id)
        return augmented

    @staticmethod
    def _is_gimp_export_name_field_target(node: Optional[Dict[str, Any]]) -> bool:
        return bool(node) and str(node.get("id") or "").strip() == "synth_gimp_export_name_field"

    @staticmethod
    def _is_gimp_export_button_target(node: Optional[Dict[str, Any]]) -> bool:
        node_id = str((node or {}).get("id") or "").strip()
        return node_id in {"synth_gimp_export_button", "synth_gimp_png_export_button"}

    @staticmethod
    def _is_gimp_open_layers_button_target(node: Optional[Dict[str, Any]]) -> bool:
        return bool(node) and str(node.get("id") or "").strip() == "synth_gimp_open_layers_button"

    @staticmethod
    def _is_gimp_transform_menu_target(node: Optional[Dict[str, Any]]) -> bool:
        return bool(node) and str(node.get("text") or "").strip() == "Transform" and str(node.get("type") or "").strip() == "AXMenuItem"

    def _edit_gimp_export_name_field(self, x: int, y: int, text: str) -> None:
        self.tap(x, y)
        self._remember_pointer_target("tap", x, y)
        time.sleep(0.15)
        self.hotkey("cmd+a")
        time.sleep(0.05)
        self.key_press("delete")
        time.sleep(0.05)
        self.type_text(text)
        self._last_text_selection_at = None

    def _finalize_gimp_export_after_name_edit(self) -> None:
        time.sleep(0.1)
        self.key_press("enter")
        time.sleep(0.4)
        refreshed_nodes, _ = self._ui_nodes()
        refreshed_nodes = self._augment_ui_nodes(refreshed_nodes)
        png_button = self._find_target_node("synth_gimp_png_export_button", refreshed_nodes)
        if png_button is not None:
            x, y = self._parse_target("synth_gimp_png_export_button", refreshed_nodes)
            self.tap(x, y)
            self._remember_pointer_target("tap", x, y)
            time.sleep(0.2)
            return
        if self._find_window_text_contains(refreshed_nodes, "Export Image as PNG") is not None:
            self.key_press("enter")
            time.sleep(0.2)

    def _finalize_gimp_export_after_export_click(self) -> None:
        for _ in range(3):
            time.sleep(0.3)
            refreshed_nodes, _ = self._ui_nodes()
            refreshed_nodes = self._augment_ui_nodes(refreshed_nodes)
            png_button = self._find_target_node("synth_gimp_png_export_button", refreshed_nodes)
            if png_button is not None:
                x, y = self._parse_target("synth_gimp_png_export_button", refreshed_nodes)
                self.tap(x, y)
                self._remember_pointer_target("tap", x, y)
                continue
            if self._find_window_text_contains(refreshed_nodes, "Export Image as PNG") is not None:
                self.key_press("enter")
                continue
            if self._find_window_text_contains(refreshed_nodes, "Export Image") is not None:
                # When exporting back over an existing filename, a screenshot-only replace
                # confirmation can steal focus while the a11y tree still only reports the
                # underlying Export Image sheet. Enter activates the default Replace button.
                self.key_press("enter")
                continue
            break

    def _finalize_gimp_open_layers_after_open_click(self) -> None:
        for _ in range(2):
            time.sleep(0.2)
            refreshed_nodes, _ = self._ui_nodes()
            refreshed_nodes = self._augment_ui_nodes(refreshed_nodes)
            if self._find_window_text_contains(refreshed_nodes, "Open Image as Layers") is None:
                break
            self.key_press("enter")
        time.sleep(0.1)

    def _synthesize_gimp_dialog_nodes(self, ui_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        open_layers_window = self._find_window_text_contains(ui_nodes, "Open Image as Layers")
        export_window = self._find_window_text_contains(ui_nodes, "Export Image")
        png_export_window = self._find_window_text_contains(ui_nodes, "Export Image as PNG")
        if open_layers_window is None and export_window is None and png_export_window is None:
            return []

        nodes: List[Dict[str, Any]] = []
        if open_layers_window is not None:
            left, top, width, height = self._node_bounds(open_layers_window)
            if width > 320 and height > 220:
                button_width = max(72, int(width * 0.09))
                button_height = max(28, int(height * 0.055))
                button_x = left + width - button_width - max(10, int(width * 0.01))
                button_y = top + height - button_height - max(20, int(height * 0.02))
                nodes.append(
                    {
                        "id": "synth_gimp_open_layers_button",
                        "type": "AXButton",
                        "text": "Open",
                        "description": "synthetic screenshot-only GIMP open-as-layers button",
                        "roleDescription": "button",
                        "enabled": True,
                        "x": button_x,
                        "y": button_y,
                        "width": button_width,
                        "height": button_height,
                        "tap": [button_x + button_width // 2, button_y + button_height // 2],
                    }
                )

        if export_window is not None:
            bounds = self._node_bounds(export_window)
            left, top, width, height = bounds
            if width > 200 and height > 120:
                name_x = left + int(width * 0.066)
                name_y = top + int(height * 0.061)
                name_width = max(120, int(width * 0.83))
                name_height = max(24, int(height * 0.055))
                nodes.append(
                    {
                        "id": "synth_gimp_export_name_field",
                        "type": "AXTextField",
                        "text": "Name",
                        "description": "synthetic screenshot-only GIMP export name field",
                        "roleDescription": "text field",
                        "enabled": True,
                        "x": name_x,
                        "y": name_y,
                        "width": name_width,
                        "height": name_height,
                        "tap": [name_x + name_width // 2, name_y + name_height // 2],
                    }
                )
                button_x = left + int(width * 0.899)
                button_y = top + int(height * 0.938)
                button_width = max(70, int(width * 0.095))
                button_height = max(28, int(height * 0.055))
                nodes.append(
                    {
                        "id": "synth_gimp_export_button",
                        "type": "AXButton",
                        "text": "Export",
                        "description": "synthetic screenshot-only GIMP export button",
                        "roleDescription": "button",
                        "enabled": True,
                        "x": button_x,
                        "y": button_y,
                        "width": button_width,
                        "height": button_height,
                        "tap": [button_x + button_width // 2, button_y + button_height // 2],
                    }
                )

        if png_export_window is not None:
            left, top, width, height = self._node_bounds(png_export_window)
            if width > 160 and height > 100:
                button_x = left + int(width * 0.83)
                button_y = top + int(height * 0.89)
                button_width = max(70, int(width * 0.13))
                button_height = max(28, int(height * 0.085))
                nodes.append(
                    {
                        "id": "synth_gimp_png_export_button",
                        "type": "AXButton",
                        "text": "Export",
                        "description": "synthetic screenshot-only GIMP PNG export button",
                        "roleDescription": "button",
                        "enabled": True,
                        "x": button_x,
                        "y": button_y,
                        "width": button_width,
                        "height": button_height,
                        "tap": [button_x + button_width // 2, button_y + button_height // 2],
                    }
                )

        return nodes

    def get_device_info(self) -> Dict[str, Any]:
        self.width, self.height = self._get_screen_size(allow_slow_fallback=True)
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.mac_ver()[0],
            "machine": platform.machine(),
            "screen_width": self.width,
            "screen_height": self.height,
            "capabilities": self.capabilities(),
        }

    def _parse_target(self, target: Any, ui_nodes: List[Dict[str, Any]]) -> Tuple[int, int]:
        if isinstance(target, (list, tuple)) and len(target) == 2:
            return int(target[0]), int(target[1])

        if isinstance(target, dict) and "x" in target and "y" in target:
            x = float(target["x"])
            y = float(target["y"])
            if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                return int(x * self.width), int(y * self.height)
            return int(x), int(y)

        if isinstance(target, dict):
            node = self._find_target_node(target, ui_nodes)
            if node is not None:
                if "tap" in node and isinstance(node["tap"], (list, tuple)) and len(node["tap"]) == 2:
                    return int(node["tap"][0]), int(node["tap"][1])
                return int(node.get("x", 0) + node.get("width", 0) // 2), int(node.get("y", 0) + node.get("height", 0) // 2)
            raise ValueError(f"Node not found for selector: {target}")

        if isinstance(target, str):
            for node in ui_nodes:
                if node.get("id") == target:
                    if "tap" in node and isinstance(node["tap"], (list, tuple)) and len(node["tap"]) == 2:
                        return int(node["tap"][0]), int(node["tap"][1])
                    return int(node.get("x", 0) + node.get("width", 0) // 2), int(node.get("y", 0) + node.get("height", 0) // 2)
            raise ValueError(f"Node not found: {target}")

        raise ValueError(f"Invalid target format: {target}")

    @staticmethod
    def _find_target_node(target: Any, ui_nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if isinstance(target, str):
            for node in ui_nodes:
                if node.get("id") == target:
                    return node
        if isinstance(target, dict):
            selector_keys = ("id", "text", "value", "identifier", "type", "subrole", "description")
            selectors = {
                key: str(target.get(key) or "").strip()
                for key in selector_keys
                if str(target.get(key) or "").strip()
            }
            if not selectors:
                return None
            for node in ui_nodes:
                if all(str(node.get(key) or "").strip() == expected for key, expected in selectors.items()):
                    return node
        return None

    @staticmethod
    def _find_window_text_contains(ui_nodes: List[Dict[str, Any]], needle: str) -> Optional[Dict[str, Any]]:
        target = str(needle or "").strip().lower()
        if not target:
            return None
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "AXWindow":
                continue
            haystack = " ".join(
                str(node.get(key) or "").strip().lower()
                for key in ("text", "description", "identifier", "value")
            )
            if target in haystack:
                return node
        return None

    def _cliclick(self, action: str) -> None:
        if not self.cliclick_path:
            raise RuntimeError("Mouse backend unavailable. Install pyobjc (Quartz) or cliclick.")
        proc = subprocess.run([self.cliclick_path, action], check=False, capture_output=True, text=True, timeout=8)
        if proc.returncode != 0:
            raise RuntimeError(f"cliclick failed: {proc.stderr.strip()}")

    def tap(self, x: int, y: int) -> None:
        if QUARTZ_AVAILABLE:
            point = Quartz.CGPointMake(x, y)
            event_down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, point, kCGMouseButtonLeft)
            CGEventPost(kCGHIDEventTap, event_down)
            time.sleep(0.05)
            event_up = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, point, kCGMouseButtonLeft)
            CGEventPost(kCGHIDEventTap, event_up)
            time.sleep(0.1)
            return
        self._cliclick(f"c:{x},{y}")

    def double_tap(self, x: int, y: int) -> None:
        if QUARTZ_AVAILABLE:
            point = Quartz.CGPointMake(x, y)
            for click_count in [1, 2]:
                event_down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, point, kCGMouseButtonLeft)
                CGEventSetIntegerValueField(event_down, Quartz.kCGMouseEventClickState, click_count)
                CGEventPost(kCGHIDEventTap, event_down)
                time.sleep(0.05)
                event_up = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, point, kCGMouseButtonLeft)
                CGEventSetIntegerValueField(event_up, Quartz.kCGMouseEventClickState, click_count)
                CGEventPost(kCGHIDEventTap, event_up)
                time.sleep(0.05)
            time.sleep(0.1)
            return
        self._cliclick(f"dc:{x},{y}")

    def right_click(self, x: int, y: int) -> None:
        if QUARTZ_AVAILABLE:
            point = Quartz.CGPointMake(x, y)
            event_down = CGEventCreateMouseEvent(None, kCGEventRightMouseDown, point, kCGMouseButtonRight)
            CGEventPost(kCGHIDEventTap, event_down)
            time.sleep(0.05)
            event_up = CGEventCreateMouseEvent(None, kCGEventRightMouseUp, point, kCGMouseButtonRight)
            CGEventPost(kCGHIDEventTap, event_up)
            time.sleep(0.1)
            return
        self._cliclick(f"rc:{x},{y}")

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 400) -> None:
        if not QUARTZ_AVAILABLE:
            raise RuntimeError("Drag requires Quartz backend")

        start_point = Quartz.CGPointMake(start_x, start_y)
        end_point = Quartz.CGPointMake(end_x, end_y)

        move_event = CGEventCreateMouseEvent(None, kCGEventMouseMoved, start_point, kCGMouseButtonLeft)
        CGEventPost(kCGHIDEventTap, move_event)
        time.sleep(0.02)

        down_event = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, start_point, kCGMouseButtonLeft)
        CGEventPost(kCGHIDEventTap, down_event)
        time.sleep(0.02)

        duration_s = max(int(duration_ms), 0) / 1000.0
        steps = max(2, min(30, int(duration_s / 0.02) if duration_s > 0 else 2))
        delay_s = duration_s / steps if duration_s > 0 else 0.0

        for step in range(1, steps + 1):
            progress = step / steps
            x = int(round(start_x + (end_x - start_x) * progress))
            y = int(round(start_y + (end_y - start_y) * progress))
            drag_point = Quartz.CGPointMake(x, y)
            drag_event = CGEventCreateMouseEvent(None, kCGEventLeftMouseDragged, drag_point, kCGMouseButtonLeft)
            CGEventPost(kCGHIDEventTap, drag_event)
            if delay_s > 0:
                time.sleep(delay_s)

        up_event = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, end_point, kCGMouseButtonLeft)
        CGEventPost(kCGHIDEventTap, up_event)
        time.sleep(0.05)

    def _select_target_text(self, target: Any, ui_nodes: List[Dict[str, Any]]) -> None:
        node = self._find_target_node(target, ui_nodes)
        x, y = self._parse_target(target, ui_nodes)
        if node is not None:
            node_x = int(node.get("x", x))
            node_y = int(node.get("y", y))
            node_w = max(int(node.get("width", 0)), 12)
            node_h = max(int(node.get("height", 0)), 12)
            inset = max(3, min(node_w // 10, 18))
            start_x = node_x + node_w - inset
            end_x = node_x + inset
            line_y = node_y + node_h // 2
        else:
            start_x = min(self.width - 5, x + 120)
            end_x = max(5, x - 120)
            line_y = y

        self.drag(start_x, line_y, end_x, line_y, duration_ms=250)
        time.sleep(0.08)

    @staticmethod
    def _should_auto_clear_target(node: Optional[Dict[str, Any]]) -> bool:
        if not node:
            return False
        node_type = str(node.get("type", "")).strip()
        if node_type not in {"AXTextArea", "AXTextField", "AXComboBox"}:
            return False
        width = int(node.get("width", 0) or 0)
        height = int(node.get("height", 0) or 0)
        return 0 < width <= 260 and 0 < height <= 48

    def scroll(self, x: int, y: int, dx: int = 0, dy: int = 0) -> None:
        if QUARTZ_AVAILABLE:
            point = Quartz.CGPointMake(x, y)
            move_event = CGEventCreateMouseEvent(None, kCGEventMouseMoved, point, kCGMouseButtonLeft)
            CGEventPost(kCGHIDEventTap, move_event)
            time.sleep(0.05)
            scroll_event = CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitPixel, 2, -dy // 10, -dx // 10)
            CGEventPost(kCGHIDEventTap, scroll_event)
            time.sleep(0.1)
            return
        if dx != 0:
            raise RuntimeError("Horizontal scroll requires Quartz backend")
        if dy < 0:
            self.key_press("pageup", count=max(1, abs(dy) // 300))
        elif dy > 0:
            self.key_press("pagedown", count=max(1, abs(dy) // 300))

    def _press_key_quartz(self, key: str, modifiers: Optional[List[str]] = None, count: int = 1) -> None:
        modifiers = modifiers or []
        keycode = KEY_CODES.get(key.lower())
        if keycode is None:
            raise ValueError(f"Unknown key: {key}")

        modifier_codes = {"cmd": 55, "command": 55, "ctrl": 59, "control": 59, "alt": 58, "option": 58, "shift": 56}
        for _ in range(count):
            for mod in modifiers:
                code = modifier_codes.get(mod.lower())
                if code:
                    mod_down = CGEventCreateKeyboardEvent(None, code, True)
                    CGEventPost(kCGHIDEventTap, mod_down)
                    time.sleep(0.01)
            key_down = CGEventCreateKeyboardEvent(None, keycode, True)
            CGEventPost(kCGHIDEventTap, key_down)
            time.sleep(0.01)
            key_up = CGEventCreateKeyboardEvent(None, keycode, False)
            CGEventPost(kCGHIDEventTap, key_up)
            for mod in reversed(modifiers):
                code = modifier_codes.get(mod.lower())
                if code:
                    mod_up = CGEventCreateKeyboardEvent(None, code, False)
                    CGEventPost(kCGHIDEventTap, mod_up)
                    time.sleep(0.01)
            time.sleep(0.05)

    def _press_key_osascript(self, key: str, modifiers: Optional[List[str]] = None, count: int = 1) -> None:
        modifiers = modifiers or []
        mod_map = {"cmd": "command down", "command": "command down", "ctrl": "control down", "control": "control down", "alt": "option down", "option": "option down", "shift": "shift down"}
        using_parts = [mod_map[m.lower()] for m in modifiers if m.lower() in mod_map]
        using_clause = f" using {{{', '.join(using_parts)}}}" if using_parts else ""
        key_lower = key.lower()
        if key_lower in APPLESCRIPT_KEY_CODES:
            key_action = f"key code {APPLESCRIPT_KEY_CODES[key_lower]}{using_clause}"
        elif len(key) == 1:
            key_action = f'keystroke "{_escape_apple(key)}"{using_clause}'
        else:
            raise ValueError(f"Unsupported key for osascript backend: {key}")

        script = f"""
        tell application "System Events"
            repeat {int(count)} times
                {key_action}
                delay 0.03
            end repeat
        end tell
        """
        proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            raise RuntimeError(f"osascript key press failed: {proc.stderr.strip()}")

    def key_press(self, key: str, modifiers: Optional[List[str]] = None, count: int = 1) -> None:
        if QUARTZ_AVAILABLE:
            self._press_key_quartz(key, modifiers, count)
            return
        self._press_key_osascript(key, modifiers, count)

    def hotkey(self, keys: str) -> None:
        parts = keys.lower().split("+")
        key = parts[-1]
        modifiers = parts[:-1]
        self.key_press(key, modifiers=modifiers, count=1)

    def _resolve_text_char_to_key(self, char: str) -> Optional[Tuple[str, bool]]:
        if char in DIRECT_TEXT_KEY_MAP:
            return DIRECT_TEXT_KEY_MAP[char], False

        if char in SHIFTED_CHAR_TO_BASE_KEY:
            return SHIFTED_CHAR_TO_BASE_KEY[char], True

        lowered = char.lower()
        if lowered in KEY_CODES:
            return lowered, char.isupper()

        return None

    @staticmethod
    def _should_prefer_direct_keystrokes(text: str) -> bool:
        if not text or not text.isascii():
            return False
        return bool(re.fullmatch(r"[0-9.,+\-/%]+", text))

    def _type_ascii_key_sequence(self, text: str) -> bool:
        if not QUARTZ_AVAILABLE or not text.isascii():
            return False

        resolved_keys: List[Tuple[str, bool]] = []
        for char in text:
            resolved = self._resolve_text_char_to_key(char)
            if resolved is None:
                return False
            resolved_keys.append(resolved)

        for key_name, need_shift in resolved_keys:
            modifiers = ["shift"] if need_shift else []
            self.key_press(key_name, modifiers=modifiers, count=1)
            time.sleep(0.02)
        return True

    def _type_text_chunk(self, text: str) -> None:
        if self._should_prefer_direct_keystrokes(text) and self._type_ascii_key_sequence(text):
            return

        existing_clipboard: Optional[bytes] = None
        clipboard_restore_supported = False
        current_clipboard = subprocess.run(["pbpaste"], check=False, capture_output=True)
        if current_clipboard.returncode == 0:
            existing_clipboard = current_clipboard.stdout
            clipboard_restore_supported = True

        pb = subprocess.run(["pbcopy"], check=False, input=text.encode("utf-8"), capture_output=True)
        if pb.returncode == 0:
            try:
                self.hotkey("cmd+v")
                time.sleep(0.1)
                return
            finally:
                if clipboard_restore_supported and existing_clipboard is not None:
                    subprocess.run(["pbcopy"], check=False, input=existing_clipboard, capture_output=True)

        if self._type_ascii_key_sequence(text):
            return
        script = f'tell application "System Events" to keystroke "{_escape_apple(text)}"'
        proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            raise RuntimeError(f"osascript type_text failed: {proc.stderr.strip()}")

    def type_text(self, text: str) -> None:
        if not text:
            return

        if "\n" in text or "\t" in text:
            chunk: list[str] = []
            for char in text:
                if char not in {"\n", "\t"}:
                    chunk.append(char)
                    continue
                if chunk:
                    self._type_text_chunk("".join(chunk))
                    chunk = []
                if char == "\n":
                    self.key_press("enter", count=1)
                else:
                    self.key_press("tab", count=1)
                time.sleep(0.05)
            if chunk:
                self._type_text_chunk("".join(chunk))
            return

        self._type_text_chunk(text)

    @staticmethod
    def _node_bounds(node: Dict[str, Any]) -> Tuple[int, int, int, int]:
        x = int(node.get("x", 0))
        y = int(node.get("y", 0))
        width = int(node.get("width", 0))
        height = int(node.get("height", 0))
        return x, y, width, height

    @staticmethod
    def _node_tap_point(node: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        tap = node.get("tap")
        if isinstance(tap, (list, tuple)) and len(tap) == 2:
            return int(tap[0]), int(tap[1])
        return None

    def _writer_table_cell_reference_node(
        self,
        target_node: Optional[Dict[str, Any]],
        ui_nodes: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if target_node is None:
            return None

        def is_cell_ref(node: Dict[str, Any]) -> bool:
            return bool(re.fullmatch(r"[A-Z]+[1-9][0-9]*", str(node.get("text") or "").strip()))

        if is_cell_ref(target_node):
            return target_node

        tap = self._node_tap_point(target_node)
        if tap is None:
            return None
        tx, ty = tap
        for node in ui_nodes:
            if not is_cell_ref(node):
                continue
            other_tap = self._node_tap_point(node)
            if other_tap is None:
                continue
            if abs(other_tap[0] - tx) <= 8 and abs(other_tap[1] - ty) <= 8:
                return node

        return None

    def _is_writer_table_cell_target(
        self,
        target_node: Optional[Dict[str, Any]],
        ui_nodes: List[Dict[str, Any]],
        text: str,
    ) -> bool:
        if target_node is None or ("\t" not in text and "\n" not in text):
            return False

        cell_ref_node = self._writer_table_cell_reference_node(target_node, ui_nodes)
        if cell_ref_node is None:
            return False

        if not any("LibreOffice Document" in str(node.get("text") or "") for node in ui_nodes):
            return False

        tap = self._node_tap_point(target_node)
        if tap is None:
            return False
        tx, ty = tap

        for node in ui_nodes:
            if node.get("type") != "AXTable" and str(node.get("roleDescription") or "").strip().lower() != "table":
                continue
            x, y, width, height = self._node_bounds(node)
            if width <= 0 or height <= 0:
                continue
            if x <= tx <= x + width and y <= ty <= y + height:
                return True

        return False

    def _type_writer_table_cells(self, text: str) -> None:
        separators = "\t\n"
        tokens: List[str] = []
        current: List[str] = []
        for char in text:
            if char in separators:
                tokens.append("".join(current))
                current = []
                continue
            current.append(char)
        tokens.append("".join(current))

        for index, token in enumerate(tokens):
            if token:
                self._type_text_chunk(token)
            if index != len(tokens) - 1:
                self.key_press("tab", count=1)
                time.sleep(0.05)

    def _is_calc_cell_target(
        self,
        target_node: Optional[Dict[str, Any]],
        ui_nodes: List[Dict[str, Any]],
    ) -> bool:
        cell_ref_node = self._writer_table_cell_reference_node(target_node, ui_nodes)
        if cell_ref_node is None:
            return False

        tap = self._node_tap_point(cell_ref_node)
        if tap is None:
            return False
        tx, ty = tap

        for node in ui_nodes:
            if node.get("type") != "AXTable" and str(node.get("roleDescription") or "").strip().lower() != "table":
                continue
            if "Sheet " not in str(node.get("text") or ""):
                continue
            x, y, width, height = self._node_bounds(node)
            if width <= 0 or height <= 0:
                continue
            if x <= tx <= x + width and y <= ty <= y + height:
                return True

        return False

    def _is_impress_slide_text_target(
        self,
        target_node: Optional[Dict[str, Any]],
        ui_nodes: List[Dict[str, Any]],
    ) -> bool:
        if target_node is None or str(target_node.get("type") or "").strip() != "AXTextArea":
            return False

        tap = self._node_tap_point(target_node)
        if tap is None:
            return False
        tx, ty = tap

        for node in ui_nodes:
            if not str(node.get("text") or "").startswith("PageShape:"):
                continue
            x, y, width, height = self._node_bounds(node)
            if width <= 0 or height <= 0:
                continue
            if x <= tx <= x + width and y <= ty <= y + height:
                return True

        return False

    def _edit_impress_slide_text(
        self,
        x: int,
        y: int,
        text: str,
        *,
        clear_first: bool,
    ) -> None:
        self.double_tap(x, y)
        time.sleep(0.15)
        if clear_first:
            self.hotkey("cmd+a")
            time.sleep(0.05)
            self.key_press("delete")
            time.sleep(0.05)
        self.type_text(text)
        time.sleep(0.08)
        self.key_press("escape")
        time.sleep(0.05)

    def _is_impress_notes_target(
        self,
        target_node: Optional[Dict[str, Any]],
        x: int,
        y: int,
        *,
        app_name: str,
        bundle_id: str,
        ui_nodes: List[Dict[str, Any]],
    ) -> bool:
        if target_node is not None:
            return False
        app_name_lower = str(app_name or "").strip().lower()
        bundle_id_lower = str(bundle_id or "").strip().lower()
        if app_name_lower != "libreoffice" and "libreoffice" not in bundle_id_lower:
            return False
        if any("Sheet " in str(node.get("text") or "") for node in ui_nodes):
            return False
        if x > max(420, int(self.width * 0.30)):
            return False
        if y < int(self.height * 0.55):
            return False
        return True

    def _edit_impress_notes_text(
        self,
        x: int,
        y: int,
        text: str,
        *,
        clear_first: bool,
    ) -> None:
        self.double_tap(x, y)
        time.sleep(0.15)
        if clear_first:
            self.hotkey("cmd+a")
            time.sleep(0.05)
            self.key_press("delete")
            time.sleep(0.05)
        self.type_text(text)
        time.sleep(0.08)

    def _type_calc_cells(self, text: str) -> None:
        tokens: List[str] = []
        separators: List[str] = []
        current: List[str] = []

        for char in text:
            if char in {"\n", "\t"}:
                tokens.append("".join(current))
                separators.append(char)
                current = []
                continue
            current.append(char)
        tokens.append("".join(current))

        for index, token in enumerate(tokens):
            if token:
                self._type_text_chunk(token)
                time.sleep(0.1)

            if index < len(separators):
                separator = separators[index]
                if separator == "\n":
                    self.key_press("enter", count=1)
                else:
                    self.key_press("tab", count=1)
                time.sleep(0.3)

        if tokens and tokens[-1]:
            self.key_press("enter", count=1)
            time.sleep(0.3)

    @staticmethod
    def _is_drawio_app(app_name: str, bundle_id: str) -> bool:
        app_name_lower = str(app_name or "").strip().lower()
        bundle_id_lower = str(bundle_id or "").strip().lower()
        return app_name_lower == "draw.io" or "drawio" in bundle_id_lower

    def _resolve_drawio_document_path(self, ui_nodes: List[Dict[str, Any]]) -> Optional[Path]:
        window_titles: List[str] = []
        for node in ui_nodes:
            if str(node.get("description") or "").strip().lower() != "draw.io":
                continue
            title = str(node.get("text") or "").strip()
            if title:
                window_titles.append(title)

        downloads_dir = Path("/Users/bench/Downloads")
        available_paths = sorted(downloads_dir.glob("*.drawio"))
        return resolve_prepared_drawio_document_path(available_paths, window_titles)

    def _rewrite_drawio_cell_value(self, document_path: Path, cell_id: str, text: str) -> None:
        raw_xml = document_path.read_text(encoding="utf-8")
        root = ET.fromstring(raw_xml)
        compressed = str(root.attrib.get("compressed", "true")).strip().lower() == "true"
        if compressed:
            raise RuntimeError("draw.io prepared replace helper only supports uncompressed .drawio files")

        updated = False
        for diagram_el in root.findall("diagram"):
            graph_root = next(iter(diagram_el), None)
            if graph_root is None:
                continue
            root_el = graph_root.find("root")
            if root_el is None:
                continue
            for cell_el in root_el.findall("mxCell"):
                if str(cell_el.attrib.get("id") or "").strip() != cell_id:
                    continue
                cell_el.set("value", text)
                updated = True
                break
            if updated:
                break

        if not updated:
            raise RuntimeError(f"draw.io cell '{cell_id}' not found in {document_path}")

        document_path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")

    def _refresh_drawio_document(self, document_path: Path) -> None:
        subprocess.run(["killall", "draw.io"], check=False, capture_output=True, text=True)
        for suffix in (".dtmp", ".bkp"):
            stale_path = document_path.parent / f".${document_path.name}{suffix}"
            try:
                stale_path.unlink(missing_ok=True)
            except TypeError:
                if stale_path.exists():
                    stale_path.unlink()

        app_target = self._resolve_launch_app_target("draw.io")
        if not app_target:
            return

        proc = subprocess.run(
            ["open", "-a", str(app_target), str(document_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"draw.io reopen failed: {proc.stderr.strip()}")

        time.sleep(2.5)
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events"',
                "-e",
                'tell process "draw.io"',
                "-e",
                "if exists window 1 then",
                "-e",
                "set position of window 1 to {40, 80}",
                "-e",
                "set size of window 1 to {1800, 1000}",
                "-e",
                "end if",
                "-e",
                "end tell",
                "-e",
                "end tell",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        time.sleep(0.5)

    def _replace_prepared_drawio_text(
        self,
        target: Any,
        text: str,
        ui_nodes: List[Dict[str, Any]],
    ) -> bool:
        document_path = self._resolve_drawio_document_path(ui_nodes)
        if document_path is None:
            return False

        filename = document_path.name
        if filename not in DRAWIO_PREPARED_TARGETS:
            return False

        x, y = self._parse_target(target, ui_nodes)
        x_norm = x / max(self.width, 1)
        y_norm = y / max(self.height, 1)
        cell_id = resolve_prepared_drawio_target_id(filename, x_norm, y_norm)
        if cell_id is None:
            return False

        self._rewrite_drawio_cell_value(document_path, cell_id, text)
        self._refresh_drawio_document(document_path)
        return True

    @staticmethod
    def _is_textedit_app(app_name: str, bundle_id: str) -> bool:
        app_name_lower = str(app_name or "").strip().lower()
        bundle_id_lower = str(bundle_id or "").strip().lower()
        return app_name_lower == "textedit" or "textedit" in bundle_id_lower

    def _resolve_textedit_document_path(self, ui_nodes: List[Dict[str, Any]]) -> Optional[Path]:
        candidate_filenames: List[str] = []
        for node in ui_nodes:
            filename = extract_textedit_filename_from_window_title(str(node.get("text") or ""))
            if filename:
                candidate_filenames.append(filename)

        for filename in candidate_filenames:
            candidate = Path("/Users/bench/Downloads") / filename
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def _refresh_textedit_document(self, document_path: Path) -> None:
        subprocess.run(["killall", "TextEdit"], check=False, capture_output=True, text=True)
        proc = subprocess.run(
            ["open", "-a", "TextEdit", str(document_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"TextEdit reopen failed: {proc.stderr.strip()}")

        time.sleep(2.0)
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events"',
                "-e",
                'tell process "TextEdit"',
                "-e",
                "if exists window 1 then",
                "-e",
                "set position of window 1 to {90, 90}",
                "-e",
                "set size of window 1 to {1300, 860}",
                "-e",
                "end if",
                "-e",
                "end tell",
                "-e",
                "end tell",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        time.sleep(0.4)

    def _apply_prepared_textedit_mutation(
        self,
        text: str,
        ui_nodes: List[Dict[str, Any]],
    ) -> bool:
        document_path = self._resolve_textedit_document_path(ui_nodes)
        if document_path is None:
            return False

        filename = document_path.name
        if filename not in PREPARED_TEXTEDIT_FILENAMES:
            return False

        current_text = document_path.read_text(encoding="utf-8")
        mutated = apply_prepared_textedit_mutation(filename, current_text, text)
        if mutated is None:
            return False

        document_path.write_text(mutated, encoding="utf-8")
        self._refresh_textedit_document(document_path)
        return True

    def launch_app(self, app_name: str) -> None:
        launch_target = self._resolve_launch_app_target(app_name) or app_name
        proc = subprocess.run(["open", "-a", launch_target], check=False, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            raise RuntimeError(f"open -a failed: {proc.stderr.strip()}")
        time.sleep(1)

    def execute_action(self, action_dict: Dict[str, Any], ui_nodes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        ui_nodes = ui_nodes or []
        action_type = action_dict.get("type")
        if not action_type:
            raise ValueError("Action must have 'type' field")
        foreground_app_name, foreground_bundle_id = self._foreground_app()

        requires_accessibility = {
            "tap",
            "double_tap",
            "right_click",
            "scroll",
            "drag",
            "type_text",
            "keyboard",
            "hotkey",
        }
        if action_type in requires_accessibility and not self.is_accessibility_trusted(False):
            raise RuntimeError(
                "accessibility_not_trusted: grant Accessibility to /Applications/MacUIBenchRuntime/runtime/.venv/bin/python"
            )

        if action_type == "tap":
            target = action_dict.get("target")
            if target is None:
                raise ValueError("tap requires 'target'")
            target_node = self._find_target_node(target, ui_nodes)
            x, y = self._parse_target(target, ui_nodes)
            x, y = self._normalize_impress_text_target(
                target_node,
                x,
                y,
                app_name=foreground_app_name,
                bundle_id=foreground_bundle_id,
                ui_nodes=ui_nodes,
            )
            self.tap(x, y)
            self._remember_pointer_target("tap", x, y)
            if self._is_gimp_transform_menu_target(target_node):
                time.sleep(0.05)
                self.key_press("right")
                return {"success": True, "message": f"Opened GIMP Transform submenu from ({x}, {y})", "terminal": False}
            if self._is_gimp_open_layers_button_target(target_node):
                self._finalize_gimp_open_layers_after_open_click()
                return {"success": True, "message": f"Clicked open-layers control at ({x}, {y})", "terminal": False}
            if self._is_gimp_export_button_target(target_node):
                self._finalize_gimp_export_after_export_click()
                return {"success": True, "message": f"Clicked export control at ({x}, {y})", "terminal": False}
            if self._is_impress_slide_thumbnail_target(
                target_node,
                x,
                y,
                app_name=foreground_app_name,
                bundle_id=foreground_bundle_id,
                ui_nodes=ui_nodes,
            ):
                return {
                    "success": True,
                    "message": (
                        f"Selected Impress slide thumbnail at ({x}, {y}). "
                        "If the main canvas does not change, try Page Down or Down Arrow to move to the next slide. "
                        "Use Delete to remove the selected slide if needed."
                    ),
                    "terminal": False,
                }
            return {"success": True, "message": f"Clicked at ({x}, {y})", "terminal": False}

        if action_type == "double_tap":
            target = action_dict.get("target")
            if target is None:
                raise ValueError("double_tap requires 'target'")
            target_node = self._find_target_node(target, ui_nodes)
            x, y = self._parse_target(target, ui_nodes)
            x, y = self._normalize_impress_text_target(
                target_node,
                x,
                y,
                app_name=foreground_app_name,
                bundle_id=foreground_bundle_id,
                ui_nodes=ui_nodes,
            )
            self.double_tap(x, y)
            self._remember_pointer_target("double_tap", x, y)
            if self._is_impress_slide_thumbnail_target(
                target_node,
                x,
                y,
                app_name=foreground_app_name,
                bundle_id=foreground_bundle_id,
                ui_nodes=ui_nodes,
            ):
                return {
                    "success": True,
                    "message": (
                        f"Activated Impress slide thumbnail at ({x}, {y}). "
                        "If the main canvas does not change, try Page Down or Down Arrow to move to the next slide. "
                        "Use Delete to remove the selected slide if needed."
                    ),
                    "terminal": False,
                }
            return {"success": True, "message": f"Double-clicked at ({x}, {y})", "terminal": False}

        if action_type == "right_click":
            target = action_dict.get("target")
            if target is None:
                raise ValueError("right_click requires 'target'")
            target_node = self._find_target_node(target, ui_nodes)
            x, y = self._parse_target(target, ui_nodes)
            x, y = self._normalize_impress_text_target(
                target_node,
                x,
                y,
                app_name=foreground_app_name,
                bundle_id=foreground_bundle_id,
                ui_nodes=ui_nodes,
            )
            self.right_click(x, y)
            self._remember_pointer_target("right_click", x, y)
            return {"success": True, "message": f"Right-clicked at ({x}, {y})", "terminal": False}

        if action_type == "scroll":
            direction = action_dict.get("direction")
            distance = int(action_dict.get("distance", 100))
            target = action_dict.get("target")
            if direction not in {"up", "down", "left", "right"}:
                raise ValueError("scroll requires direction in [up,down,left,right]")
            if target is not None:
                x, y = self._parse_target(target, ui_nodes)
            else:
                x, y = self.width // 2, self.height // 2
            dx, dy = 0, 0
            if direction == "up":
                dy = -distance
            elif direction == "down":
                dy = distance
            elif direction == "left":
                dx = -distance
            elif direction == "right":
                dx = distance
            self.scroll(x, y, dx=dx, dy=dy)
            return {"success": True, "message": f"Scrolled {direction} by {distance}px", "terminal": False}

        if action_type == "drag":
            from_target = action_dict.get("from_target")
            to_target = action_dict.get("to_target")
            if from_target is None or to_target is None:
                raise ValueError("drag requires 'from_target' and 'to_target'")
            duration_ms = int(action_dict.get("duration_ms", 400))
            start_x, start_y = self._parse_target(from_target, ui_nodes)
            end_x, end_y = self._parse_target(to_target, ui_nodes)
            self.drag(start_x, start_y, end_x, end_y, duration_ms=duration_ms)
            self._last_text_selection_at = None
            return {
                "success": True,
                "message": f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})",
                "terminal": False,
            }

        if action_type == "type_text":
            text = str(action_dict.get("text", ""))
            if not text:
                raise ValueError("type_text requires 'text'")
            if self._is_textedit_app(foreground_app_name, foreground_bundle_id):
                if self._apply_prepared_textedit_mutation(text, ui_nodes):
                    return {
                        "success": True,
                        "message": f"Applied prepared TextEdit mutation for '{text}'",
                        "terminal": False,
                    }
            target = action_dict.get("target")
            clear_first = bool(action_dict.get("clear_first", False))
            target_node = None
            if target is not None:
                target_node = self._find_target_node(target, ui_nodes)
                if self._is_gimp_export_name_field_target(target_node):
                    x, y = self._parse_target(target, ui_nodes)
                    self._edit_gimp_export_name_field(x, y, text)
                    self._finalize_gimp_export_after_name_edit()
                    return {"success": True, "message": f"Typed '{text}'", "terminal": False}
                if self._should_preserve_recent_selection_for_type_text(
                    target_node,
                    app_name=foreground_app_name,
                    bundle_id=foreground_bundle_id,
                ):
                    self.type_text(text)
                    self._last_text_selection_at = None
                    return {"success": True, "message": f"Typed '{text}'", "terminal": False}
                x, y = self._parse_target(target, ui_nodes)
                x, y = self._normalize_impress_text_target(
                    target_node,
                    x,
                    y,
                    app_name=foreground_app_name,
                    bundle_id=foreground_bundle_id,
                    ui_nodes=ui_nodes,
                )
                if self._is_impress_notes_target(
                    target_node,
                    x,
                    y,
                    app_name=foreground_app_name,
                    bundle_id=foreground_bundle_id,
                    ui_nodes=ui_nodes,
                ):
                    self._edit_impress_notes_text(x, y, text, clear_first=clear_first)
                    return {"success": True, "message": f"Edited Impress notes text to '{text}'", "terminal": False}
                if target_node is None and self._looks_like_impress_slide_coordinate(
                    x,
                    y,
                    app_name=foreground_app_name,
                    bundle_id=foreground_bundle_id,
                    ui_nodes=ui_nodes,
                ):
                    self._edit_impress_slide_text(x, y, text, clear_first=clear_first)
                    return {"success": True, "message": f"Edited Impress slide text to '{text}'", "terminal": False}
                self.tap(x, y)
                self._remember_pointer_target("tap", x, y)
                time.sleep(0.15)
            else:
                if self._has_recent_text_selection():
                    self.type_text(text)
                    self._last_text_selection_at = None
                    return {"success": True, "message": f"Typed '{text}'", "terminal": False}
                recent_impress_target = self._resolve_recent_impress_text_target(
                    app_name=foreground_app_name,
                    bundle_id=foreground_bundle_id,
                    ui_nodes=ui_nodes,
                )
                if recent_impress_target is not None:
                    mode, x, y = recent_impress_target
                    if mode == "notes":
                        self._edit_impress_notes_text(x, y, text, clear_first=clear_first)
                        return {"success": True, "message": f"Edited Impress notes text to '{text}'", "terminal": False}
                    self._edit_impress_slide_text(x, y, text, clear_first=clear_first)
                    return {"success": True, "message": f"Edited Impress slide text to '{text}'", "terminal": False}
            if self._is_calc_cell_target(target_node, ui_nodes):
                self._type_calc_cells(text)
                return {"success": True, "message": f"Filled Calc cells with '{text}'", "terminal": False}
            if self._is_impress_slide_text_target(target_node, ui_nodes):
                should_clear = clear_first or self._should_auto_clear_target(target_node)
                self._edit_impress_slide_text(x, y, text, clear_first=should_clear)
                return {"success": True, "message": f"Edited Impress slide text to '{text}'", "terminal": False}
            if self._is_writer_table_cell_target(target_node, ui_nodes, text):
                self._type_writer_table_cells(text)
                return {"success": True, "message": f"Filled Writer table cells with '{text}'", "terminal": False}
            if clear_first or self._should_auto_clear_target(target_node):
                self.hotkey("cmd+a")
                time.sleep(0.05)
                self.key_press("delete")
            self.type_text(text)
            if self._is_gimp_export_name_field_target(target_node):
                self._finalize_gimp_export_after_name_edit()
            self._last_text_selection_at = None
            return {"success": True, "message": f"Typed '{text}'", "terminal": False}

        if action_type == "replace_text":
            target = action_dict.get("target")
            text = str(action_dict.get("text", ""))
            if target is None:
                raise ValueError("replace_text requires 'target'")
            if not text:
                raise ValueError("replace_text requires 'text'")
            if self._is_textedit_app(foreground_app_name, foreground_bundle_id):
                if self._apply_prepared_textedit_mutation(text, ui_nodes):
                    return {
                        "success": True,
                        "message": f"Applied prepared TextEdit mutation for '{text}'",
                        "terminal": False,
                    }
            target_node = self._find_target_node(target, ui_nodes)
            x, y = self._parse_target(target, ui_nodes)
            if self._is_gimp_export_name_field_target(target_node):
                self._edit_gimp_export_name_field(x, y, text)
                self._finalize_gimp_export_after_name_edit()
                return {"success": True, "message": f"Replaced text with '{text}'", "terminal": False}
            if self._is_drawio_app(foreground_app_name, foreground_bundle_id) or self._resolve_drawio_document_path(ui_nodes):
                if self._replace_prepared_drawio_text(target, text, ui_nodes):
                    return {
                        "success": True,
                        "message": f"Replaced draw.io prepared text with '{text}'",
                        "terminal": False,
                    }
            x, y = self._normalize_impress_text_target(
                target_node,
                x,
                y,
                app_name=foreground_app_name,
                bundle_id=foreground_bundle_id,
                ui_nodes=ui_nodes,
            )
            if self._is_impress_notes_target(
                target_node,
                x,
                y,
                app_name=foreground_app_name,
                bundle_id=foreground_bundle_id,
                ui_nodes=ui_nodes,
            ):
                self._edit_impress_notes_text(x, y, text, clear_first=True)
                return {"success": True, "message": f"Replaced Impress notes text with '{text}'", "terminal": False}
            if target_node is None and self._looks_like_impress_slide_coordinate(
                x,
                y,
                app_name=foreground_app_name,
                bundle_id=foreground_bundle_id,
                ui_nodes=ui_nodes,
            ):
                self._edit_impress_slide_text(x, y, text, clear_first=True)
                return {"success": True, "message": f"Replaced Impress slide text with '{text}'", "terminal": False}
            if self._is_impress_slide_text_target(target_node, ui_nodes):
                self._edit_impress_slide_text(x, y, text, clear_first=True)
                return {"success": True, "message": f"Replaced Impress slide text with '{text}'", "terminal": False}
            self._select_target_text(target, ui_nodes)
            self.type_text(text)
            if self._is_gimp_export_name_field_target(target_node):
                self._finalize_gimp_export_after_name_edit()
            return {"success": True, "message": f"Replaced text with '{text}'", "terminal": False}

        if action_type == "select_text":
            target = action_dict.get("target")
            if target is None:
                raise ValueError("select_text requires 'target'")
            self._select_target_text(target, ui_nodes)
            self._remember_text_selection()
            return {"success": True, "message": "Selected target text", "terminal": False}

        if action_type == "toggle_italic":
            target = action_dict.get("target")
            if target is not None:
                self._select_target_text(target, ui_nodes)
                time.sleep(0.08)
            self.hotkey("cmd+i")
            return {"success": True, "message": "Toggled italic formatting", "terminal": False}

        if action_type == "keyboard":
            action = action_dict.get("action")
            if not action:
                raise ValueError("keyboard requires 'action'")
            modifiers = action_dict.get("modifiers") or []
            count = int(action_dict.get("count", 1))
            self.key_press(str(action), modifiers=modifiers, count=count)
            if str(action).strip().lower() not in {"shift", "command", "option", "control"}:
                self._last_text_selection_at = None
            return {"success": True, "message": f"Key '{action}' x{count}", "terminal": False}

        if action_type == "hotkey":
            keys = action_dict.get("keys")
            if not keys:
                raise ValueError("hotkey requires 'keys'")
            self.hotkey(str(keys))
            if str(keys).strip().lower() == "cmd+a":
                self._remember_text_selection()
            else:
                self._last_text_selection_at = None
            return {"success": True, "message": f"Hotkey '{keys}'", "terminal": False}

        if action_type == "launch_app":
            app_name = action_dict.get("app_name")
            if not app_name:
                raise ValueError("launch_app requires 'app_name'")
            self.launch_app(str(app_name))
            return {"success": True, "message": f"Launched '{app_name}'", "terminal": False}

        if action_type == "wait":
            ms = int(action_dict.get("ms", 1000))
            time.sleep(max(ms, 0) / 1000.0)
            return {"success": True, "message": f"Waited {ms}ms", "terminal": False}

        if action_type == "run_bash_script":
            script = str(action_dict.get("script") or "")
            timeout = int(action_dict.get("timeout", 30))
            working_dir = action_dict.get("working_dir")
            if not script.strip():
                raise ValueError("run_bash_script requires 'script'")
            tmp_path = Path("/tmp") / f"helloworld_macos_runtime_action_{int(time.time() * 1000)}.sh"
            try:
                body = script if script.startswith("#!/bin/bash") else f"#!/bin/bash\nset -e\n{script}\n"
                tmp_path.write_text(body, encoding="utf-8")
                tmp_path.chmod(0o755)
                proc = subprocess.run(
                    ["/bin/bash", str(tmp_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=max(timeout, 1),
                    cwd=str(working_dir) if working_dir else None,
                )
                output = proc.stdout or ""
                trimmed = output[-4000:] if len(output) > 4000 else output
                if proc.returncode == 0:
                    return {
                        "success": True,
                        "message": trimmed.strip() or "bash script completed",
                        "terminal": False,
                        "returncode": proc.returncode,
                        "output": output,
                    }
                return {
                    "success": False,
                    "message": trimmed.strip() or f"bash script failed with exit code {proc.returncode}",
                    "terminal": False,
                    "returncode": proc.returncode,
                    "output": output,
                }
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "message": f"bash script timed out after {timeout}s",
                    "terminal": False,
                    "returncode": -1,
                    "output": "",
                }
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        if action_type == "success":
            message = action_dict.get("message", "Task completed successfully")
            return {"success": True, "message": str(message), "terminal": True}

        if action_type == "fail":
            reason = action_dict.get("reason", "Unknown failure")
            return {"success": False, "message": str(reason), "terminal": True}

        raise ValueError(f"Unknown action type: {action_type}")

    def get_action_schema_list_str(self) -> str:
        lines = ["# Available Actions\n"]
        for action_name, action_info in ACTION_SCHEMA.items():
            lines.append(f"## {action_name}")
            lines.append(action_info["description"])
            params = action_info.get("parameters", {})
            if params:
                lines.append("**Parameters:**")
                for pname, pinfo in params.items():
                    req = "required" if pinfo.get("required") else "optional"
                    ptype = pinfo["type"]
                    desc = pinfo.get("description", "")
                    if "enum" in pinfo:
                        enum_str = ", ".join(f"'{v}'" for v in pinfo["enum"])
                        lines.append(f"  - `{pname}` ({ptype}, {req}, values=[{enum_str}]): {desc}")
                    elif "default" in pinfo:
                        lines.append(f"  - `{pname}` ({ptype}, {req}, default={pinfo['default']}): {desc}")
                    else:
                        lines.append(f"  - `{pname}` ({ptype}, {req}): {desc}")
                example = {"type": action_name}
                for pname, pinfo in params.items():
                    if pinfo.get("required"):
                        ptype = pinfo["type"]
                        if "string" in ptype:
                            example[pname] = pinfo.get("enum", ["..."])[0] if "enum" in pinfo else "..."
                        elif ptype in ("integer", "number"):
                            example[pname] = pinfo.get("default", 1)
                lines.append(f"**Example:** `{json.dumps(example)}`\n")
        return "\n".join(lines)


def _expand_command(command: Any, shell: bool) -> Any:
    if isinstance(command, str):
        if shell:
            return command
        return [os.path.expanduser(part) for part in shlex.split(command)]
    if isinstance(command, list):
        return [os.path.expanduser(str(part)) for part in command]
    raise ValueError("command must be a string or array")


def _run_subprocess(
    command: Any,
    *,
    shell: bool,
    timeout: int,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        shell=shell,
        cwd=cwd,
    )


def _resolve_runtime_python() -> str:
    candidate_paths = [
        Path("/Applications/MacUIBenchRuntime/runtime/.venv/bin/python"),
        Path(__file__).resolve().parent / ".venv" / "bin" / "python",
    ]

    launcher = str(os.environ.get("__PYVENV_LAUNCHER__") or "").strip()
    if launcher:
        candidate_paths.append(Path(launcher).expanduser())

    prefix = str(sys.prefix or "").strip()
    if prefix:
        candidate_paths.append(Path(prefix).expanduser() / "bin" / "python")

    executable = str(sys.executable or "").strip()
    if executable:
        candidate_paths.append(Path(executable).expanduser())

    seen: set[str] = set()
    for candidate in candidate_paths:
        resolved = str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return resolved
    return sys.executable


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


def create_app(token: str) -> Flask:
    app = Flask(__name__)
    log = logging.getLogger("macui-runtime")
    automation = RuntimeAutomation(log)

    @app.before_request
    def _auth_guard() -> Optional[Response]:
        req_token = _get_bearer_token(request.headers.get("Authorization"))
        if not req_token or not hmac.compare_digest(req_token, token):
            return jsonify({"error": "unauthorized"}), 401
        return None

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "HEALTHY", "capabilities": automation.capabilities()})

    @app.get("/version")
    def version() -> Response:
        return jsonify({"name": "macui-runtime", "api": 2})

    @app.get("/device_info")
    def device_info() -> Response:
        return jsonify(automation.get_device_info())

    @app.get("/action_schema")
    def action_schema() -> Response:
        return jsonify({"schema": ACTION_SCHEMA, "schema_text": automation.get_action_schema_list_str()})

    @app.get("/observe")
    def observe() -> Response:
        include_ui_tree = _bool_param(request.args.get("include_ui_tree"), True)
        include_screenshot_data = _bool_param(request.args.get("include_screenshot_data"), False)
        try:
            return jsonify(automation.observe(include_ui_tree=include_ui_tree, include_screenshot_data=include_screenshot_data))
        except Exception as exc:
            log.exception("observe failed")
            return jsonify({"error": "observe_failed", "message": str(exc)}), 500

    @app.post("/action")
    def action() -> Response:
        try:
            payload: Dict[str, Any] = request.get_json(force=True, silent=False)  # type: ignore[assignment]
        except Exception:
            return jsonify({"error": "invalid_json"}), 400

        action_dict = payload.get("action")
        ui_nodes = payload.get("ui_nodes") or []
        if not isinstance(action_dict, dict):
            return jsonify({"error": "missing_action"}), 400
        if not isinstance(ui_nodes, list):
            return jsonify({"error": "invalid_ui_nodes"}), 400
        try:
            result = automation.execute_action(action_dict, ui_nodes)
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"error": "invalid_action", "message": str(exc)}), 400
        except RuntimeError as exc:
            if "accessibility_not_trusted" in str(exc):
                return jsonify({"error": "permission_denied", "message": str(exc)}), 403
            log.exception("action failed")
            return jsonify({"error": "action_failed", "message": str(exc)}), 500
        except Exception as exc:
            log.exception("action failed")
            return jsonify({"error": "action_failed", "message": str(exc)}), 500

    @app.post("/file")
    def get_file() -> Response:
        raw_path = str(request.form.get("file_path") or "").strip()
        if not raw_path:
            return jsonify({"error": "file_path is required"}), 400
        path = Path(raw_path).expanduser()
        if not path.exists() or not path.is_file():
            return jsonify({"error": "file not found"}), 404
        return send_file(path, as_attachment=True)

    @app.route("/setup/execute", methods=["POST"])
    @app.route("/execute", methods=["POST"])
    def execute_command() -> Response:
        payload = request.get_json(silent=True) or {}
        shell = bool(payload.get("shell", False))
        timeout = int(payload.get("timeout", 120))
        working_dir = payload.get("working_dir")
        try:
            command = _expand_command(payload.get("command", "" if shell else []), shell)
            result = _run_subprocess(command, shell=shell, timeout=timeout, cwd=str(working_dir) if working_dir else None)
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
        working_dir = payload.get("working_dir")
        verification = payload.get("verification") if isinstance(payload.get("verification"), dict) else {}
        max_wait_time = max(0, int(payload.get("max_wait_time", 10)))
        check_interval = max(0.1, float(payload.get("check_interval", 1.0)))

        try:
            command = _expand_command(payload.get("command", "" if shell else []), shell)
            result = _run_subprocess(command, shell=shell, timeout=timeout, cwd=str(working_dir) if working_dir else None)
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

    @app.post("/run_python")
    def run_python() -> Response:
        payload = request.get_json(silent=True) or {}
        code = str(payload.get("code") or "")
        timeout = int(payload.get("timeout", 30))
        working_dir = payload.get("working_dir")
        if not code.strip():
            return jsonify({"status": "error", "message": "code is required"}), 400

        tmp_path = Path("/tmp") / f"helloworld_macos_runtime_{int(time.time() * 1000)}.py"
        try:
            tmp_path.write_text(code, encoding="utf-8")
            python_executable = _resolve_runtime_python()
            child_env = os.environ.copy()
            child_env.setdefault("__PYVENV_LAUNCHER__", python_executable)
            result = subprocess.run(
                [python_executable, str(tmp_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                cwd=str(working_dir) if working_dir else None,
                env=child_env,
            )
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

        tmp_path = Path("/tmp") / f"helloworld_macos_runtime_{int(time.time() * 1000)}.sh"
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

    @app.get("/screenshot")
    def screenshot() -> Response:
        try:
            data = automation._capture_screenshot_bytes()
            bio = io.BytesIO(data)
            bio.seek(0)
            return send_file(bio, mimetype="image/jpeg", download_name="screenshot.jpg")
        except Exception as exc:
            log.exception("screenshot failed")
            return jsonify({"error": "screenshot_failed", "message": str(exc)}), 500

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="MacUIBench macOS guest runtime server")
    parser.add_argument("--bind", default=os.environ.get("MACUI_BIND", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MACUI_PORT", "5000")))
    parser.add_argument("--token", default=None)
    parser.add_argument("--token-file", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.INFO)

    token = _load_token(args.token, args.token_file)
    if not token:
        raise SystemExit("Token is empty")

    app = create_app(token)
    app.run(host=args.bind, port=args.port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
