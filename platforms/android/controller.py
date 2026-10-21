"""ADB-based controller for Android platform.

Unlike Windows/Linux which use HTTP guest runtime servers, the Android
platform communicates directly with the emulator via ADB.

Mirrors the WindowsRuntimeController / LinuxRuntimeController interface
so that the shared BaseEpisodeRunner can work with Android via duck typing.
"""

from __future__ import annotations

from copy import deepcopy
import json
import logging
import os
import re
import subprocess
import shutil
import shlex
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from platforms.android.host_env import android_tool_env

logger = logging.getLogger(__name__)


def _resolve_adb_path() -> str:
    env = android_tool_env(apply_to_process=True)
    found = shutil.which("adb")
    if found:
        return found

    sdk_root = env.get("ANDROID_HOME") or env.get("ANDROID_SDK_ROOT")
    sdk_roots = [Path(sdk_root)] if sdk_root else []
    userprofile = env.get("USERPROFILE")
    if userprofile:
        sdk_roots.append(Path(userprofile) / ".helloworld-android" / "Sdk")

    for root in sdk_roots:
        candidate = root / "platform-tools" / "adb.exe"
        if candidate.exists():
            return str(candidate)
    return "adb"


# ---------------------------------------------------------------------------
# Android action schema — defines actions the LLM agent can take
# ---------------------------------------------------------------------------

ANDROID_ACTION_SCHEMA: Dict[str, Any] = {
    "actions": {
        "tap": {
            "description": "Tap the specified element or position.",
            "parameters": {
                "target": {
                    "type": "string|array|object",
                    "required": True,
                    "description": "Target: node text/resource-id/content-desc, pixel coords [x, y], normalized coords {'x': 0.5, 'y': 0.5}, or legacy object {'x': 540, 'y': 1200}.",
                },
            },
            "required": ["target"],
        },
        "long_press": {
            "description": "Long press the specified element or position.",
            "parameters": {
                "target": {
                    "type": "string|array|object",
                    "required": True,
                    "description": "Target: node text/resource-id/content-desc, pixel coords [x, y], normalized coords {'x': 0.5, 'y': 0.5}, or legacy object {'x': 540, 'y': 1200}.",
                },
                "duration_ms": {"type": "integer", "required": False, "description": "Duration in ms", "default": 1000},
            },
            "required": ["target"],
        },
        "swipe": {
            "description": "Swipe from one position to another.",
            "parameters": {
                "from_target": {
                    "type": "string|array|object",
                    "required": True,
                    "description": "Swipe start: node text/resource-id/content-desc, pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}.",
                },
                "to_target": {
                    "type": "string|array|object",
                    "required": True,
                    "description": "Swipe end: node text/resource-id/content-desc, pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}.",
                },
                "duration_ms": {"type": "integer", "required": False, "description": "Duration in ms", "default": 300},
            },
            "required": ["from_target", "to_target"],
        },
        "type_text": {
            "description": "Type text, optionally after tapping a target input field.",
            "parameters": {
                "text": {"type": "string", "required": True, "description": "Text to type"},
                "target": {
                    "type": "string|array|object",
                    "required": False,
                    "description": "Optional target input field: node text/resource-id/content-desc, pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}.",
                },
                "clear_first": {"type": "boolean", "required": False, "default": False, "description": "Whether to clear the focused field before typing."},
            },
            "required": ["text"],
        },
        "input_text": {
            "description": "Legacy alias for type_text into the currently focused field.",
            "parameters": {
                "text": {"type": "string", "required": True, "description": "Text to type"},
            },
            "required": ["text"],
        },
        "keyboard": {
            "description": "Send a keyboard or system key action.",
            "parameters": {
                "action": {
                    "type": "string",
                    "required": True,
                    "enum": ["enter", "back", "home", "escape", "backspace", "delete", "space", "search"],
                    "description": "Keyboard/system action to send.",
                },
                "count": {"type": "integer", "required": False, "default": 1, "description": "Number of repeated key presses."},
            },
            "required": ["action"],
        },
        "press_key": {
            "description": "Legacy Android keycode action, e.g. KEYCODE_HOME, KEYCODE_BACK, KEYCODE_ENTER.",
            "parameters": {
                "keycode": {"type": "string", "required": True, "description": "Android keycode name"},
            },
            "required": ["keycode"],
        },
        "launch_app": {
            "description": "Launch an app by package name.",
            "parameters": {
                "app_name": {"type": "string", "required": True, "description": "App package name"},
            },
            "required": ["app_name"],
        },
        "scroll": {
            "description": "Scroll the screen or specified container.",
            "parameters": {
                "direction": {
                    "type": "string",
                    "required": True,
                    "enum": ["up", "down", "left", "right"],
                    "description": "Scroll direction.",
                },
                "distance": {"type": "number", "required": False, "default": 0.5, "description": "Scroll distance as a screen ratio."},
                "target": {
                    "type": "string|array|object",
                    "required": False,
                    "description": "Optional scroll center: node text/resource-id/content-desc, pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}.",
                },
                "duration_ms": {"type": "integer", "required": False, "default": 300, "description": "Scroll duration in ms."},
            },
            "required": ["direction"],
        },
        "wait": {
            "description": "Wait for the UI to settle.",
            "parameters": {
                "ms": {"type": "integer", "required": False, "default": 1000, "description": "Milliseconds to wait."},
            },
            "required": [],
        },
        "success": {
            "description": "Declare the task is completed successfully.",
            "parameters": {
                "message": {"type": "string", "required": False, "description": "Success message"},
            },
            "required": [],
            "terminal": True,
        },
        "fail": {
            "description": "Declare the task has failed.",
            "parameters": {
                "message": {"type": "string", "required": False, "description": "Failure reason"},
            },
            "required": [],
            "terminal": True,
        },
    }
}

_SCREENSHOT_ONLY_TARGET_PARAM_OVERRIDES: Dict[tuple[str, str], str] = {
    (
        "tap",
        "target",
    ): (
        "Target: pixel coords [x, y], normalized coords {'x': 0.5, 'y': 0.5}, "
        "or legacy object {'x': 540, 'y': 1200}. Do not use text labels, "
        "resource-id values, or content-desc strings in screenshot-only mode."
    ),
    (
        "long_press",
        "target",
    ): (
        "Target: pixel coords [x, y], normalized coords {'x': 0.5, 'y': 0.5}, "
        "or legacy object {'x': 540, 'y': 1200}. Do not use text labels, "
        "resource-id values, or content-desc strings in screenshot-only mode."
    ),
    (
        "swipe",
        "from_target",
    ): (
        "Swipe start: pixel coords [x, y] or normalized coords {'x': 0.5, 'y': 0.5}. "
        "Do not use text labels, resource-id values, or content-desc strings in screenshot-only mode."
    ),
    (
        "swipe",
        "to_target",
    ): (
        "Swipe end: pixel coords [x, y] or normalized coords {'x': 0.5, 'y': 0.5}. "
        "Do not use text labels, resource-id values, or content-desc strings in screenshot-only mode."
    ),
    (
        "type_text",
        "target",
    ): (
        "Optional target input field: pixel coords [x, y] or normalized coords {'x': 0.5, 'y': 0.5}. "
        "Do not use text labels, resource-id values, or content-desc strings in screenshot-only mode."
    ),
    (
        "scroll",
        "target",
    ): (
        "Optional scroll center: pixel coords [x, y] or normalized coords {'x': 0.5, 'y': 0.5}. "
        "Do not use text labels, resource-id values, or content-desc strings in screenshot-only mode."
    ),
}


def _normalize_observation_mode(observation_mode: Optional[str]) -> str:
    return str(observation_mode or "").strip().lower() or "screenshot_and_a11y_tree"


def _build_android_action_schema_for_mode(observation_mode: Optional[str]) -> Dict[str, Any]:
    actions = deepcopy(ANDROID_ACTION_SCHEMA["actions"])
    if _normalize_observation_mode(observation_mode) != "screenshot_only":
        return actions

    for (action_name, param_name), description in _SCREENSHOT_ONLY_TARGET_PARAM_OVERRIDES.items():
        param_info = actions.get(action_name, {}).get("parameters", {}).get(param_name)
        if not isinstance(param_info, dict):
            continue
        param_info["type"] = "array|object"
        param_info["description"] = description

    return actions


# ---------------------------------------------------------------------------
# Observation dataclass — matches Windows/Linux Observation interface
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    """Observation from the Android device."""

    timestamp: str = ""
    width: int = 1080
    height: int = 1920
    ui_nodes: List[Dict[str, Any]] = field(default_factory=list)
    foreground_app: str = ""
    foreground_bundle_id: str = ""
    foreground_window: str = ""
    screenshot_data: Optional[bytes] = None

    def to_json(self) -> str:
        data = {
            "timestamp": self.timestamp,
            "width": self.width,
            "height": self.height,
            "ui_nodes": self.ui_nodes,
            "foreground_app": self.foreground_app,
        }
        return json.dumps(data, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ADB Controller
# ---------------------------------------------------------------------------

@dataclass
class AdbController:
    """Controller that interacts with an Android device/emulator via ADB.

    Implements the same duck-typing interface as WindowsRuntimeController
    so that BaseEpisodeRunner can use it directly.
    """

    adb_device: str = "emulator-5554"
    adb_path: str = field(default_factory=_resolve_adb_path)
    timeout: float = 30.0
    screenshot_dir: Optional[Path] = None
    width: int = 1080
    height: int = 1920

    def __post_init__(self):
        """Initialize device dimensions."""
        self._refresh_device_info()

    # -----------------------------------------------------------------------
    # Low-level ADB
    # -----------------------------------------------------------------------

    def execute_adb(self, args: list[str]) -> str:
        """Execute an ADB command and return stdout.

        Uses explicit UTF-8 encoding because ADB always outputs UTF-8,
        but on Chinese Windows the default subprocess encoding is GBK
        which causes UnicodeDecodeError on non-ASCII characters.
        """
        # ADB rejoins shell argv; retain literal text after action parsing.
        wire_args = args
        if args[:3] == ["shell", "input", "text"]:
            wire_args = args[:3] + [shlex.quote(value) for value in args[3:]]
        cmd = [self.adb_path, "-s", self.adb_device] + wire_args
        logger.debug("ADB command: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=android_tool_env(apply_to_process=True),
            )
            if result.returncode != 0 and result.stderr.strip():
                logger.warning("ADB stderr: %s", result.stderr.strip())
            if result.returncode != 0 and len(args) > 1 and args[:2] == ['shell', 'input']:
                raise RuntimeError(f'ADB GUI input failed ({result.returncode}): {result.stderr.strip()}')
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error("ADB command timed out: %s", " ".join(cmd))
            if len(args) > 1 and args[:2] == ['shell', 'input']:
                raise RuntimeError('ADB GUI input timed out')
            return ""

    # -----------------------------------------------------------------------
    # Device info & health
    # -----------------------------------------------------------------------

    def _refresh_device_info(self) -> None:
        """Try to get actual screen dimensions."""
        try:
            output = self.execute_adb(["shell", "wm", "size"])
            # Output: "Physical size: 1080x1920"
            if "x" in output:
                parts = output.split(":")[-1].strip().split("x")
                if len(parts) == 2:
                    self.width = int(parts[0])
                    self.height = int(parts[1])
        except Exception:
            pass

    def get_device_info(self) -> Dict[str, Any]:
        """Get device information."""
        return {
            "screen_width": self.width,
            "screen_height": self.height,
            "device": self.adb_device,
            "model": self.execute_adb(["shell", "getprop", "ro.product.model"]),
            "android_version": self.execute_adb(["shell", "getprop", "ro.build.version.release"]),
        }

    def health(self) -> Dict[str, str]:
        """Check if the device is reachable."""
        output = self.execute_adb(["get-state"])
        if "device" in output:
            return {"status": "HEALTHY", "state": output}
        return {"status": "UNHEALTHY", "state": output}

    # -----------------------------------------------------------------------
    # Screenshot (BaseEpisodeRunner interface)
    # -----------------------------------------------------------------------

    def update_screenshot_dir(self, new_dir: str) -> None:
        """Set the directory for saving screenshots."""
        self.screenshot_dir = Path(new_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def _remote_screenshot_path(self, label: str) -> str:
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(label or "screenshot"))[:40]
        return f"/sdcard/helloworld_{safe_label}_{os.getpid()}_{uuid4().hex}.png"

    def save_screenshot(self, prefix: str = "screenshot") -> str:
        """Take a screenshot and save to screenshot_dir. Returns the filepath.

        This matches the WindowsRuntimeController.save_screenshot interface.
        """
        if self.screenshot_dir is None:
            raise RuntimeError(
                "Screenshot directory is not configured. "
                "Call update_screenshot_dir() first."
            )

        if prefix == "final":
            filename = "final.png"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"{prefix}_{timestamp}.png"

        filepath = self.screenshot_dir / filename
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self.screenshot(filepath)

        return str(filepath)

    def screenshot(self, save_path: Path) -> Path:
        """Take a screenshot and save it to a specific path (legacy interface)."""
        from io import BytesIO
        from PIL import Image
        last_error = None
        for attempt in range(2):
            try:
                result = subprocess.run([self.adb_path, '-s', self.adb_device,
                                         'exec-out', 'screencap', '-p'],
                                        capture_output=True, timeout=45,
                                        env=android_tool_env(apply_to_process=True), check=True)
                with Image.open(BytesIO(result.stdout)) as image:
                    image.verify()
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(result.stdout)
                return save_path
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f'Unable to capture a fresh valid screenshot: {last_error}')

    def disable_touch_debug_overlays(self) -> None:
        """Hide Android developer touch overlays that contaminate screenshots."""
        for key in ("pointer_location", "show_touches"):
            try:
                self.execute_adb(["shell", "settings", "put", "system", key, "0"])
            except Exception as exc:
                logger.debug("Failed to disable Android setting %s: %s", key, exc)

    def _pull_remote_file(self, remote_path: str, save_path: Path) -> None:
        """Pull through a short temp path to avoid adb issues with deep Windows paths."""
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="android-pull-") as tmpdir:
            tmp_path = Path(tmpdir) / save_path.name
            self.execute_adb(["pull", remote_path, str(tmp_path)])
            if tmp_path.exists():
                shutil.move(str(tmp_path), str(save_path))

    # -----------------------------------------------------------------------
    # Observation (BaseEpisodeRunner interface)
    # -----------------------------------------------------------------------
    def get_ui_hierarchy(self, max_retries: int = 2) -> str:
        """Dump the UI hierarchy XML (accessibility tree).

        Uses ``uiautomator dump /dev/tty`` which pipes XML directly to
        stdout, avoiding file-creation race conditions.

        Retries once if the first attempt fails (e.g. during activity
        transitions).  Delays are kept short to preserve the episode
        timeout budget — on animation-heavy screens ``uiautomator``
        will fail regardless of retries.
        """
        import time

        for attempt in range(1, max_retries + 1):
            # Small delay to let UI settle
            time.sleep(0.3)

            raw = self.execute_adb(["exec-out", "uiautomator", "dump", "/dev/tty"])
            xml_str = self._extract_xml_from_dump(raw)
            if xml_str:
                return xml_str

            logger.warning(
                "UI hierarchy dump attempt %d/%d failed (%s), retrying...",
                attempt, max_retries, raw[:80] if raw else "empty",
            )
            if attempt < max_retries:
                time.sleep(0.8)

        logger.warning("UI hierarchy dump failed after %d attempts", max_retries)
        return ""

    @staticmethod
    def _extract_xml_from_dump(raw: str) -> str:
        """Extract valid XML from uiautomator dump /dev/tty output.

        The output looks like:
            <?xml ...>...<node .../></hierarchy>UI hierchary dumped to: /dev/tty
        We need to strip the trailing status message.
        """
        if not raw:
            return ""
        # Find the XML end tag
        end_marker = "</hierarchy>"
        idx = raw.find(end_marker)
        if idx >= 0:
            return raw[:idx + len(end_marker)]
        # Maybe the raw output is already clean XML
        stripped = raw.strip()
        if stripped.startswith("<?xml") or stripped.startswith("<hierarchy"):
            return stripped
        return ""

    def _parse_ui_nodes(self, xml_str: str) -> List[Dict[str, Any]]:
        """Parse Android UI hierarchy XML into a list of node dicts.

        Normalizes Android XML attribute names to Python-friendly names:
          content-desc  → content_description
          resource-id   → resource_id
          long-clickable → long_clickable
        This matches the android_world UIElement convention.
        """
        if not xml_str or not xml_str.strip():
            return []

        # Android XML attr → Python-friendly key
        _ATTR_MAP = {
            "content-desc": "content_description",
            "resource-id": "resource_id",
            "long-clickable": "long_clickable",
            "NAF": "not_accessibility_friendly",
        }

        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_str)
            nodes = []
            for node in root.iter("node"):
                raw_attrs = dict(node.attrib)
                # Normalize attribute names
                attrs: Dict[str, Any] = {}
                for key, value in raw_attrs.items():
                    normalized_key = _ATTR_MAP.get(key, key)
                    attrs[normalized_key] = value
                    # Keep original key too for backward compatibility
                    if normalized_key != key:
                        attrs[key] = value

                # Parse bounds "[x1,y1][x2,y2]" into structured data
                bounds_str = attrs.get("bounds", "")
                if bounds_str:
                    try:
                        parts = bounds_str.replace("][", ",").strip("[]").split(",")
                        if len(parts) == 4:
                            x1, y1, x2, y2 = [int(p) for p in parts]
                            attrs["tap"] = {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2}
                            attrs["rect"] = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
                    except (ValueError, IndexError):
                        pass
                nodes.append(attrs)
            return nodes
        except Exception:
            return []

    def get_current_activity(self) -> str:
        """Get the current foreground activity."""
        output = self.execute_adb([
            "shell", "dumpsys", "activity", "activities",
        ])
        for line in output.splitlines():
            if "mResumedActivity" in line or "mFocusedActivity" in line:
                return line.strip()
        return ""

    def observe(
        self,
        include_ui_tree: bool = True,
        include_screenshot_data: bool = False,
    ) -> Observation:
        """Read current environment observation.

        Returns an Observation dataclass matching the Windows/Linux interface.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        current_activity = self.get_current_activity()

        ui_nodes: List[Dict[str, Any]] = []
        if include_ui_tree:
            xml_str = self.get_ui_hierarchy()
            ui_nodes = self._parse_ui_nodes(xml_str)

        screenshot_data: Optional[bytes] = None
        if include_screenshot_data and self.screenshot_dir:
            try:
                tmp_path = self.screenshot_dir / "_observe_tmp.png"
                self.screenshot(tmp_path)
                screenshot_data = tmp_path.read_bytes()
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

        # Extract foreground app from activity string
        foreground_app = ""
        if current_activity:
            # Format: "mResumedActivity: ActivityRecord{... com.example.app/.MainActivity ...}"
            for part in current_activity.split():
                if "/" in part and "." in part:
                    foreground_app = part.split("/")[0]
                    break

        return Observation(
            timestamp=timestamp,
            width=self.width,
            height=self.height,
            ui_nodes=ui_nodes,
            foreground_app=foreground_app,
            foreground_bundle_id=foreground_app,
            foreground_window=current_activity,
            screenshot_data=screenshot_data,
        )

    # -----------------------------------------------------------------------
    # Action execution (BaseEpisodeRunner interface)
    # -----------------------------------------------------------------------

    def _parse_target(
        self,
        target: Any,
        ui_nodes: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[int, int]:
        """Resolve a node-ish target, pixel coords, or normalized coords."""
        if isinstance(target, (list, tuple)) and len(target) >= 2:
            return self._coords_from_xy(target[0], target[1])

        if isinstance(target, dict):
            if "x" in target and "y" in target:
                return self._coords_from_xy(target.get("x"), target.get("y"))

        if isinstance(target, str):
            stripped = target.strip()
            if not stripped:
                raise ValueError("target cannot be empty")
            parsed = self._parse_target_string_as_coords(stripped)
            if parsed is not None:
                return parsed
            node = self._find_ui_node(stripped, ui_nodes or [])
            if node is not None:
                center = self._node_center(node)
                if center is not None:
                    return center

        raise ValueError(f"Unsupported target: {target!r}")

    def _coords_from_xy(self, raw_x: Any, raw_y: Any) -> tuple[int, int]:
        x = float(raw_x)
        y = float(raw_y)
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            x *= self.width
            y *= self.height
        return self._clamp_point(round(x), round(y))

    def _parse_target_string_as_coords(self, text: str) -> Optional[tuple[int, int]]:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (list, tuple, dict)):
            return self._parse_target(parsed, [])

        coord_match = re.match(r"^\s*\[?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]?\s*$", text)
        if coord_match:
            return self._coords_from_xy(coord_match.group(1), coord_match.group(2))
        return None

    def _clamp_point(self, x: int, y: int) -> tuple[int, int]:
        max_x = max(0, int(self.width) - 1)
        max_y = max(0, int(self.height) - 1)
        return max(0, min(int(x), max_x)), max(0, min(int(y), max_y))

    def _find_ui_node(self, target: str, ui_nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        lowered = target.lower()
        keys = (
            "id",
            "index",
            "text",
            "resource_id",
            "resource-id",
            "content_description",
            "content-desc",
            "class",
        )
        for node in ui_nodes:
            for key in keys:
                value = str(node.get(key) or "").strip()
                if not value:
                    continue
                if value.lower() == lowered:
                    return node
        for node in ui_nodes:
            for key in ("text", "resource_id", "resource-id", "content_description", "content-desc"):
                value = str(node.get(key) or "").strip()
                if value and lowered in value.lower():
                    return node
        return None

    def _node_center(self, node: Dict[str, Any]) -> Optional[tuple[int, int]]:
        tap = node.get("tap")
        if isinstance(tap, dict) and "x" in tap and "y" in tap:
            return self._coords_from_xy(tap.get("x"), tap.get("y"))

        rect = node.get("rect")
        if isinstance(rect, dict) and {"x", "y", "w", "h"}.issubset(rect):
            return self._coords_from_xy(
                float(rect["x"]) + float(rect["w"]) / 2,
                float(rect["y"]) + float(rect["h"]) / 2,
            )

        bounds = str(node.get("bounds") or "")
        if bounds:
            try:
                parts = bounds.replace("][", ",").strip("[]").split(",")
                if len(parts) == 4:
                    x1, y1, x2, y2 = [int(p) for p in parts]
                    return self._clamp_point((x1 + x2) // 2, (y1 + y2) // 2)
            except ValueError:
                return None
        return None

    def _target_from_legacy_xy(self, action_dict: Dict[str, Any]) -> Any:
        if "target" in action_dict:
            return action_dict.get("target")
        if "x" in action_dict and "y" in action_dict:
            return [action_dict.get("x"), action_dict.get("y")]
        return None

    def validate_action_for_observation_mode(
        self,
        action_dict: Dict[str, Any],
        *,
        observation_mode: Optional[str],
    ) -> Optional[str]:
        normalized_mode = _normalize_observation_mode(observation_mode)
        if normalized_mode != "screenshot_only":
            return None

        action_type = str(action_dict.get("type") or "").strip().lower()
        if not action_type:
            return "action type cannot be empty"

        target_keys: List[str] = []
        if action_type in {"tap", "long_press", "type_text", "scroll"}:
            target_keys = ["target"]
        elif action_type == "swipe":
            target_keys = ["from_target", "to_target"]

        for key in target_keys:
            if key not in action_dict:
                continue
            target = action_dict.get(key)
            if not isinstance(target, str):
                continue
            stripped = target.strip()
            if not stripped:
                return f"{action_type}.{key} cannot be empty"
            if self._parse_target_string_as_coords(stripped) is None:
                return (
                    f"screenshot_only requires coordinate targets for {action_type}.{key}; "
                    f"got string target {target!r}"
                )

        return None

    def execute_action(
        self,
        action_dict: Dict[str, Any],
        ui_nodes: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Execute an action from the LLM agent.

        Interprets the action_dict (which has a 'type' field) and calls
        the appropriate ADB command. Returns a result dict.
        """
        action_type = str(action_dict.get("type", "")).strip().lower()

        if action_type == "tap":
            target = self._target_from_legacy_xy(action_dict)
            if target is None:
                raise ValueError("tap requires target or x/y")
            x, y = self._parse_target(target, ui_nodes or [])
            self.tap(x, y)
            return {"success": True, "message": f"Tapped at ({x}, {y})"}

        elif action_type == "long_press":
            target = self._target_from_legacy_xy(action_dict)
            if target is None:
                raise ValueError("long_press requires target or x/y")
            x, y = self._parse_target(target, ui_nodes or [])
            duration = int(action_dict.get("duration_ms", 1000))
            self.execute_adb([
                "shell", "input", "swipe",
                str(x), str(y), str(x), str(y), str(duration),
            ])
            return {"success": True, "message": f"Long pressed at ({x}, {y}) for {duration}ms"}

        elif action_type == "swipe":
            from_target = action_dict.get("from_target")
            to_target = action_dict.get("to_target")
            if from_target is None and {"x1", "y1"}.issubset(action_dict):
                from_target = [action_dict.get("x1"), action_dict.get("y1")]
            if to_target is None and {"x2", "y2"}.issubset(action_dict):
                to_target = [action_dict.get("x2"), action_dict.get("y2")]
            if from_target is None or to_target is None:
                raise ValueError("swipe requires from_target/to_target or x1/y1/x2/y2")
            x1, y1 = self._parse_target(from_target, ui_nodes or [])
            x2, y2 = self._parse_target(to_target, ui_nodes or [])
            duration = int(action_dict.get("duration_ms", 300))
            self.swipe(x1, y1, x2, y2, duration)
            return {"success": True, "message": f"Swiped ({x1},{y1})->({x2},{y2})"}

        elif action_type in {"type_text", "input_text"}:
            text = str(action_dict.get("text", ""))
            target = action_dict.get("target")
            if target is not None:
                x, y = self._parse_target(target, ui_nodes or [])
                self.tap(x, y)
                time.sleep(0.3)
            if bool(action_dict.get("clear_first", action_type == "input_text")):
                self._clear_focused_edit_text_if_needed(ui_nodes or [])
            self.input_text(text)
            return {"success": True, "message": f"Typed: {text[:50]}"}

        elif action_type == "keyboard":
            kb_action = str(action_dict.get("action", "")).strip().lower()
            count = max(1, int(action_dict.get("count", 1)))
            key_map = {
                "enter": "KEYCODE_ENTER",
                "search": "KEYCODE_ENTER",
                "back": "KEYCODE_BACK",
                "escape": "KEYCODE_BACK",
                "home": "KEYCODE_HOME",
                "backspace": "KEYCODE_DEL",
                "delete": "KEYCODE_DEL",
                "space": "KEYCODE_SPACE",
            }
            keycode = key_map.get(kb_action)
            if not keycode:
                raise ValueError(f"Unknown keyboard action: {kb_action}")
            for _ in range(count):
                self.press_key(keycode)
            return {"success": True, "message": f"Keyboard action: {kb_action} x{count}"}

        elif action_type == "press_key":
            keycode = str(action_dict.get("keycode", ""))
            self.press_key(keycode)
            return {"success": True, "message": f"Pressed key: {keycode}"}

        elif action_type == "launch_app":
            app_name = str(action_dict.get("app_name", ""))
            self.launch_app(app_name)
            return {"success": True, "message": f"Launched: {app_name}"}

        elif action_type == "scroll_up":
            mid_x = self.width // 2
            self.swipe(mid_x, self.height // 3, mid_x, self.height * 2 // 3, 300)
            return {"success": True, "message": "Scrolled up"}

        elif action_type == "scroll_down":
            mid_x = self.width // 2
            self.swipe(mid_x, self.height * 2 // 3, mid_x, self.height // 3, 300)
            return {"success": True, "message": "Scrolled down"}

        elif action_type == "scroll":
            direction = str(action_dict.get("direction", "down")).strip().lower()
            duration = int(action_dict.get("duration_ms", 300))
            distance_ratio = float(action_dict.get("distance", 0.5))
            target = action_dict.get("target")
            if target is not None:
                cx, cy = self._parse_target(target, ui_nodes or [])
            else:
                cx, cy = self.width // 2, self.height // 2
            dx = int(self.width * min(max(distance_ratio, 0.05), 1.0) * 0.5)
            dy = int(self.height * min(max(distance_ratio, 0.05), 1.0) * 0.5)
            if direction == "down":
                start, end = (cx, cy + dy), (cx, cy - dy)
            elif direction == "up":
                start, end = (cx, cy - dy), (cx, cy + dy)
            elif direction == "right":
                start, end = (cx + dx, cy), (cx - dx, cy)
            elif direction == "left":
                start, end = (cx - dx, cy), (cx + dx, cy)
            else:
                raise ValueError(f"Unknown scroll direction: {direction}")
            x1, y1 = self._clamp_point(*start)
            x2, y2 = self._clamp_point(*end)
            self.swipe(x1, y1, x2, y2, duration)
            return {"success": True, "message": f"Scrolled {direction}"}

        elif action_type == "wait":
            ms = max(0, int(action_dict.get("ms", action_dict.get("duration_ms", 1000))))
            time.sleep(ms / 1000.0)
            return {"success": True, "message": f"Waited {ms}ms"}

        elif action_type == "adb":
            args = action_dict.get("args")
            if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise ValueError("adb action requires string args list")
            output = self.execute_adb(args)
            message = str(action_dict.get("command") or "adb " + " ".join(args))
            return {"success": True, "message": message, "output": output[:500]}

        elif action_type == "adb_script":
            commands = action_dict.get("commands")
            if not isinstance(commands, list) or not commands:
                raise ValueError("adb_script action requires non-empty commands list")

            outputs: List[str] = []
            labels: List[str] = []
            for index, command in enumerate(commands, start=1):
                if not isinstance(command, dict):
                    raise ValueError(f"adb_script command #{index} must be an object")
                command_type = str(command.get("type") or "").strip()
                label = str(command.get("command") or command_type or f"command_{index}")
                labels.append(label)

                if command_type == "sleep":
                    seconds = float(command.get("seconds", 0.0))
                    time.sleep(max(0.0, min(seconds, 5.0)))
                    outputs.append("")
                    continue

                if command_type != "adb":
                    raise ValueError(f"adb_script command #{index} has unsupported type: {command_type}")
                args = command.get("args")
                if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                    raise ValueError(f"adb_script command #{index} requires string args list")
                outputs.append(self.execute_adb(args))

            return {
                "success": True,
                "message": "\n".join(labels),
                "output": "\n".join(output for output in outputs if output)[:500],
            }

        elif action_type == "success":
            msg = str(action_dict.get("message", "Task completed"))
            return {"success": True, "terminal": True, "message": msg}

        elif action_type == "fail":
            msg = str(action_dict.get("message", "Task failed"))
            return {"success": False, "terminal": True, "message": msg}

        else:
            return {"success": False, "message": f"Unknown action type: {action_type}"}

    # -----------------------------------------------------------------------
    # Action schema (BaseEpisodeRunner interface)
    # -----------------------------------------------------------------------

    def get_action_schema_list_str(self, observation_mode: Optional[str] = None) -> str:
        """Return action schema as human-readable text for json-mode prompts.

        IMPORTANT: The parser (parse_action_from_text) requires the JSON to
        contain a "type" key whose value is the action name.  This prompt MUST
        make that format unambiguous for the LLM.
        """
        normalized_mode = _normalize_observation_mode(observation_mode)
        action_schema = _build_android_action_schema_for_mode(normalized_mode)
        lines = [
            "You must respond with a single JSON object. "
            "The JSON object MUST contain a \"type\" field indicating the action name, "
            "plus the required parameters as top-level fields.",
            (
                "For screenshot-only tasks, use normalized or pixel coordinates only for tap/press/swipe targets. "
                "Do not use visible text labels, resource-id values, or content-desc strings as targets."
                if normalized_mode == "screenshot_only"
                else "Prefer target-based actions and normalized coordinates for screenshot-only tasks."
            ),
            "",
            "Available actions:",
            "",
        ]
        examples = {
            "tap": '{"type": "tap", "target": {"x": 0.7, "y": 0.93}}',
            "long_press": '{"type": "long_press", "target": [540, 1200]}',
            "swipe": '{"type": "swipe", "from_target": {"x": 0.5, "y": 0.8}, "to_target": {"x": 0.5, "y": 0.3}}',
            "type_text": '{"type": "type_text", "target": {"x": 0.5, "y": 0.4}, "text": "Hello World"}',
            "input_text": '{"type": "input_text", "text": "Hello World"}',
            "keyboard": '{"type": "keyboard", "action": "back"}',
            "press_key": '{"type": "press_key", "keycode": "KEYCODE_BACK"}',
            "launch_app": '{"type": "launch_app", "app_name": "com.android.settings"}',
            "scroll": '{"type": "scroll", "direction": "down"}',
            "scroll_up": '{"type": "scroll_up"}',
            "scroll_down": '{"type": "scroll_down"}',
            "success": '{"type": "success", "message": "Task completed"}',
            "fail": '{"type": "fail", "message": "Cannot complete task"}',
        }
        for name, spec in action_schema.items():
            desc = spec.get("description", "")
            params = spec.get("parameters", {})
            required = spec.get("required", [])
            param_strs = []
            for pname, pinfo in params.items():
                req_mark = " (required)" if pname in required or pinfo.get("required") else " (optional)"
                param_strs.append(
                    f"    - {pname}: {pinfo.get('type', 'any')} - "
                    f"{pinfo.get('description', '')}{req_mark}"
                )
            lines.append(f"  {name}: {desc}")
            if param_strs:
                lines.extend(param_strs)
            example = examples.get(name)
            if example:
                lines.append(f"    Example: {example}")
            lines.append("")

        lines.extend([
            "CRITICAL FORMAT RULES:",
            '- The "type" field is MANDATORY in every response.',
            '- All parameters are top-level fields in the same JSON object (NOT nested under "parameters").',
            '- Do NOT use "action", "action_type", or any other key instead of "type".',
            '- Return ONLY the JSON object, no explanation or markdown.',
            "",
            'For example, to tap a bottom tab: {"type": "tap", "target": {"x": 0.7, "y": 0.93}}',
            'Legacy pixel taps still work: {"type": "tap", "x": 756, "y": 2230}',
            'To go back: {"type": "keyboard", "action": "back"}',
        ])
        return "\n".join(lines)

    def get_action_schema_json(self, observation_mode: Optional[str] = None) -> Dict[str, Any]:
        """Return action schema as JSON for tool-calling mode."""
        return _build_android_action_schema_for_mode(observation_mode)

    # -----------------------------------------------------------------------
    # Basic actions
    # -----------------------------------------------------------------------

    def launch_app(self, app_name_or_package: str) -> str:
        """Launch an app by package name via monkey."""
        package_path = self.execute_adb(["shell", "pm", "path", app_name_or_package]).strip()
        if "package:" not in package_path:
            raise RuntimeError(f"App package is not installed: {app_name_or_package}")
        return self.execute_adb([
            "shell", "monkey", "-p", app_name_or_package,
            "-c", "android.intent.category.LAUNCHER", "1",
        ])

    def tap(self, x: int, y: int) -> str:
        """Tap at coordinates."""
        return self.execute_adb(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        """Swipe from (x1,y1) to (x2,y2)."""
        return self.execute_adb([
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms),
        ])

    def input_text(self, text: str) -> str:
        """Type text."""
        normalized = unicodedata.normalize("NFKD", text or "")
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_text = " ".join(ascii_text.replace("\n", " ").split())
        if not ascii_text:
            return ""

        last_result = ""
        tokens = ascii_text.split(" ")
        for index, token in enumerate(tokens):
            escaped = token.replace("&", "\\&").replace("<", "\\<").replace(">", "\\>")
            if escaped:
                last_result = self.execute_adb(["shell", "input", "text", escaped])
            if index < len(tokens) - 1:
                last_result = self.execute_adb(["shell", "input", "keyevent", "KEYCODE_SPACE"])
        return last_result

    def _clear_focused_edit_text_if_needed(self, ui_nodes: List[Dict[str, Any]]) -> None:
        for node in ui_nodes:
            if str(node.get("class") or "") != "android.widget.EditText":
                continue
            if str(node.get("focused") or "").lower() != "true":
                continue

            current_text = str(node.get("text") or "")
            if not current_text:
                return

            self.execute_adb(["shell", "input", "keyevent", "KEYCODE_MOVE_END"])
            clear_count = max(len(current_text) + 8, 32)
            for _ in range(clear_count):
                self.execute_adb(["shell", "input", "keyevent", "KEYCODE_DEL"])
            return

    def press_key(self, keycode: str) -> str:
        """Press a key by keycode name."""
        return self.execute_adb(["shell", "input", "keyevent", keycode])

    def press_home(self) -> str:
        return self.press_key("KEYCODE_HOME")

    def press_back(self) -> str:
        return self.press_key("KEYCODE_BACK")

    def press_enter(self) -> str:
        return self.press_key("KEYCODE_ENTER")

    def get_file(self, remote_path: str) -> bytes:
        """Pull a file from Android shared storage and return its bytes."""
        with tempfile.TemporaryDirectory(prefix="android-get-file-") as tmpdir:
            local_path = Path(tmpdir) / Path(remote_path).name
            self.execute_adb(["pull", remote_path, str(local_path)])
            if not local_path.is_file():
                raise FileNotFoundError(f"Android file pull failed: {remote_path}")
            return local_path.read_bytes()

    def upload_file(self, local_path: str, remote_path: str) -> str:
        """Push a local file to Android, creating the destination directory first."""
        src = Path(local_path).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Local file not found: {src}")
        remote_dir = str(Path(remote_path).parent).replace("\\", "/")
        if remote_dir and remote_dir != ".":
            self.execute_adb(["shell", "mkdir", "-p", remote_dir])
        return self.execute_adb(["push", str(src), remote_path])
