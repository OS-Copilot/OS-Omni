"""
Action schema + action execution engine.
"""

import json
import ast
import contextlib
import io
import signal
import threading
import time
from typing import Any, Dict, List

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

ACTION_SCHEMA = {
    "tap": {
        "description": "Tap the specified element or position",
        "parameters": {
            "target": {"type": "string|array|object", "required": True, "description": "Target: node ID (e.g. 'n5'), pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}"}
        }
    },
    "double_tap": {
        "description": "Double tap the specified element or position",
        "parameters": {
            "target": {"type": "string|array|object", "required": True, "description": "Target: node ID, pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}"}
        }
    },
    "long_press": {
        "description": "Long press the specified element or position",
        "parameters": {
            "target": {"type": "string|array|object", "required": True, "description": "Target: node ID, pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}"},
            "duration_ms": {"type": "integer", "required": False, "default": 1000, "description": "Duration of press (milliseconds)"}
        }
    },
    "drag": {
        "description": "Drag from one element or position to another. Useful for reordering list items or moving sliders.",
        "parameters": {
            "from": {"type": "string|array|object", "required": True, "description": "Start point: node ID, pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}"},
            "to": {"type": "string|array|object", "required": True, "description": "End point: node ID, pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}"},
            "duration_ms": {"type": "integer", "required": False, "default": 800, "description": "Drag duration (milliseconds). Use a longer duration such as 800-1500ms for precise list reordering."}
        }
    },
    "scroll": {
        "description": "Scroll the screen or specified container",
        "parameters": {
            "direction": {"type": "string", "required": True, "enum": ["up", "down", "left", "right"], "description": "Scroll direction"},
            "distance": {"type": "number", "required": False, "default": 0.5, "description": "Scroll distance (screen ratio 0.0-1.0)"},
            "target": {"type": "string|array|object", "required": False, "description": "Optional scroll center: node ID, pixel coords [x, y], or normalized coords"},
            "duration_ms": {"type": "integer", "required": False, "default": 150, "description": "Scroll animation duration (milliseconds)"}
        }
    },
    "type_text": {
        "description": "Type text into the input field",
        "parameters": {
            "target": {"type": "string|array|object", "required": True, "description": "Target input field: node ID, pixel coords [x, y], or normalized coords"},
            "text": {"type": "string", "required": True, "description": "Text to input"},
            "clear_first": {"type": "boolean", "required": False, "default": False, "description": "Whether to clear the field before input"}
        }
    },
    "keyboard": {
        "description": "Send keyboard action (submit form/text, delete text, dismiss keyboard). Use 'enter'/'search'/'go' to submit, 'backspace'/'delete' to remove text",
        "parameters": {
            "action": {"type": "string", "required": True, "enum": ["enter", "search", "go", "backspace", "delete", "escape"], "description": "'enter'/'search'/'go' submit the form/text, 'backspace' deletes one char, 'delete' deletes selection, 'escape' dismisses"},
            "count": {"type": "integer", "required": False, "default": 1, "description": "Number of times to repeat the keyboard action. Mainly useful for repeated backspace/delete."}
        }
    },
    "clipboard": {
        "description": "Clipboard operations",
        "parameters": {
            "action": {"type": "string", "required": True, "enum": ["set", "get", "paste"], "description": "'set' copies text to clipboard, 'get' retrieves clipboard content, 'paste' pastes into current focus"},
            "text": {"type": "string", "required": False, "description": "Text to copy (required for 'set' action)"}
        }
    },
    "alert": {
        "description": "Handle system alerts/popups",
        "parameters": {
            "action": {"type": "string", "required": True, "enum": ["accept", "dismiss"], "description": "'accept' confirms the alert, 'dismiss' closes it"}
        }
    },
    "system": {
        "description": "Perform common system operations",
        "parameters": {
            "action": {"type": "string", "required": True, "enum": ["home", "hideKeyboard"], "description": "System action to perform: 'home' returns to home screen, 'hideKeyboard' hides the keyboard"}
        }
    },
    "launch_app": {
        "description": "Launch the specified application",
        "parameters": {
            "bundle_id": {"type": "string", "required": True, "description": "Application's Bundle ID, e.g., 'com.apple.mobilesafari'"}
        }
    },
    "wait": {
        "description": "Wait for a specified time",
        "parameters": {
            "ms": {"type": "integer", "required": False, "default": 1000, "description": "Wait time (milliseconds)"}
        }
    },
    "success": {
        "description": "Task successfully completed",
        "parameters": {
            "message": {"type": "string", "required": False, "description": "Success message"}
        }
    },
    "fail": {
        "description": "Task could not be completed",
        "parameters": {
            "reason": {"type": "string", "required": True, "description": "Reason for failure"}
        }
    }
}


def _appium_code_policy_error(code: str) -> str | None:
    try:
        tree = ast.parse(str(code or ""))
    except SyntaxError:
        return None

    if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)):
        return "outside_appium_framework: imports are not available in iOS Appium code mode"

    referenced_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    if "driver" not in referenced_names:
        return "outside_appium_framework: code must use the provided Appium `driver`"
    return None


def _run_with_best_effort_timeout(fn, timeout_seconds: int):
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        return fn()

    def _raise_timeout(_signum, _frame):
        raise TimeoutError(f"Timed out after {timeout_seconds}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    try:
        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, max(1, int(timeout_seconds)))
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


class iOSActionEngine:
    """Action schema rendering and execution layer."""

    def __init__(self, runtime):
        self.runtime = runtime
        self._action_handlers = {
            "tap": self._exec_tap,
            "double_tap": self._exec_double_tap,
            "long_press": self._exec_long_press,
            "drag": self._exec_drag,
            "scroll": self._exec_scroll,
            "type_text": self._exec_type_text,
            "keyboard": self._exec_keyboard,
            "clipboard": self._exec_clipboard,
            "alert": self._exec_alert,
            "system": self._exec_system,
            "launch_app": self._exec_launch_app,
            "wait": self._exec_wait,
            "success": self._exec_success,
            "fail": self._exec_fail,
            "seed_state": self._exec_seed_state,
        }

    def _schema_with_target_descriptions(self, *, allow_node_ids: bool) -> Dict[str, Any]:
        schema_copy = json.loads(json.dumps(ACTION_SCHEMA))
        coord_only_text = "pixel coords [x, y], or normalized coords {'x': 0.5, 'y': 0.5}. Do not use node IDs"

        for action_type, schema in schema_copy.items():
            params = schema.get("parameters", {})
            for param_name, pinfo in params.items():
                if param_name != "target":
                    continue
                if allow_node_ids:
                    continue
                description = str(pinfo.get("description", ""))
                if "Target:" in description:
                    pinfo["description"] = f"Target: {coord_only_text}"
                else:
                    pinfo["description"] = coord_only_text

        return schema_copy

    def _render_action_schema_list_str(self, *, allow_node_ids: bool) -> str:
        lines = ["# Available Actions", ""]
        action_schema = self._schema_with_target_descriptions(allow_node_ids=allow_node_ids)

        for action_type, schema in action_schema.items():
            lines.append(f"## {action_type}")
            lines.append(schema["description"])

            example = {"type": action_type}
            params = schema.get("parameters", {})

            if params:
                lines.append("**Parameters:**")
                for pname, pinfo in params.items():
                    req = "required" if pinfo.get("required") else "optional"
                    default = f", default={pinfo['default']}" if "default" in pinfo else ""
                    enum = f", values={pinfo['enum']}" if "enum" in pinfo else ""
                    lines.append(
                        f"  - `{pname}` ({pinfo['type']}, {req}{default}{enum}): {pinfo['description']}"
                    )

                    if pinfo.get("required"):
                        ptype = pinfo["type"]
                        if "string" in ptype and allow_node_ids:
                            example[pname] = pinfo["enum"][0] if "enum" in pinfo else "..."
                        elif pname == "target" and not allow_node_ids:
                            example[pname] = {"x": 0.5, "y": 0.5}
                        elif ptype in ("integer", "number"):
                            example[pname] = pinfo.get("default", 1)

            lines.append(f"**Example:** `{json.dumps(example, ensure_ascii=False)}`")
            lines.append("")

        return "\n".join(lines)

    def get_action_schema_list_str(self) -> str:
        return self._render_action_schema_list_str(allow_node_ids=True)

    def get_coordinate_action_schema_list_str(self) -> str:
        return self._render_action_schema_list_str(allow_node_ids=False)

    def get_action_schema_json(self) -> Dict[str, Any]:
        return ACTION_SCHEMA

    def run_python_script(self, code: str, *, timeout: int = 120) -> Dict[str, Any]:
        code = str(code or "").strip()
        timeout_seconds = max(1, int(timeout or 120))
        if not code:
            return {
                "status": "error",
                "message": "code is required",
                "output": "",
                "error": "code is required",
                "return_code": -1,
                "terminal": True,
                "terminal_action_type": "fail",
            }

        policy_error = _appium_code_policy_error(code)
        if policy_error:
            return {
                "status": "error",
                "message": policy_error,
                "output": "",
                "error": policy_error,
                "return_code": -1,
                "terminal": True,
                "terminal_action_type": "fail",
            }

        output = io.StringIO()
        error_output = io.StringIO()
        safe_builtins = {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "float": float,
            "int": int,
            "len": len,
            "list": list,
            "max": max,
            "min": min,
            "print": print,
            "range": range,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
            "Exception": Exception,
            "RuntimeError": RuntimeError,
            "TimeoutError": TimeoutError,
            "ValueError": ValueError,
        }
        namespace = {
            "__builtins__": safe_builtins,
            "__name__": "__ios_appium_action__",
            "driver": self.runtime.driver,
            "time": time,
            "AppiumBy": AppiumBy,
            "WebDriverWait": WebDriverWait,
            "EC": EC,
            "TimeoutException": TimeoutException,
            "NoSuchElementException": NoSuchElementException,
            "WebDriverException": WebDriverException,
        }

        def _exec_code():
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
                exec(compile(code, "<ios_reflection_pyautogui_action>", "exec"), namespace, namespace)

        try:
            _run_with_best_effort_timeout(_exec_code, timeout_seconds)
            return {
                "status": "success",
                "message": "Appium Python code executed",
                "output": output.getvalue(),
                "error": error_output.getvalue(),
                "return_code": 0,
                "terminal": False,
                "terminal_action_type": None,
            }
        except NameError as exc:
            message = f"outside_appium_framework: {exc}"
            return {
                "status": "error",
                "message": message,
                "output": output.getvalue(),
                "error": message,
                "return_code": -1,
                "terminal": True,
                "terminal_action_type": "fail",
            }
        except TimeoutError as exc:
            return {
                "status": "error",
                "message": str(exc),
                "output": output.getvalue(),
                "error": str(exc),
                "return_code": -1,
                "terminal": False,
                "terminal_action_type": None,
            }
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            return {
                "status": "error",
                "message": message,
                "output": output.getvalue(),
                "error": message,
                "return_code": -1,
                "terminal": False,
                "terminal_action_type": None,
            }

    def execute_action(self, action: Any, ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        action_dict = json.loads(action) if isinstance(action, str) else action
        action_type = action_dict.get("type")
        if not action_type:
            raise ValueError("Action JSON missing 'type' field")

        handler = self._action_handlers.get(action_type)
        if handler is None:
            raise ValueError(f"Unsupported action type: {action_type}")
        return handler(action_dict, ui_nodes)

    def _exec_tap(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        target = action_dict.get("target")
        if not target:
            raise ValueError("tap requires 'target'")
        x, y = self.runtime.parse_target(target, ui_nodes)
        self.runtime.tap_px(x, y)
        return {"success": True, "message": f"Tapped at ({x}, {y})", "terminal": False}

    def _exec_double_tap(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        target = action_dict.get("target")
        if not target:
            raise ValueError("double_tap requires 'target'")
        x, y = self.runtime.parse_target(target, ui_nodes)
        self.runtime.double_tap_px(x, y)
        return {"success": True, "message": f"Double tapped at ({x}, {y})", "terminal": False}

    def _exec_long_press(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        target = action_dict.get("target")
        if not target:
            raise ValueError("long_press requires 'target'")
        duration_ms = action_dict.get("duration_ms", 1000)
        x, y = self.runtime.parse_target(target, ui_nodes)
        self.runtime.long_press_px(x, y, duration=duration_ms / 1000.0)
        return {"success": True, "message": f"Long pressed at ({x}, {y}) for {duration_ms}ms", "terminal": False}

    def _exec_drag(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        start = action_dict.get("from")
        end = action_dict.get("to")
        if not start or not end:
            raise ValueError("drag requires 'from' and 'to'")
        duration_ms = action_dict.get("duration_ms", 800)
        start_x, start_y = self.runtime.parse_target(start, ui_nodes)
        end_x, end_y = self.runtime.parse_target(end, ui_nodes)
        self.runtime.drag_px(start_x, start_y, end_x, end_y, duration_s=duration_ms / 1000.0)
        return {
            "success": True,
            "message": f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y}) for {duration_ms}ms",
            "terminal": False,
        }

    def _exec_scroll(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        direction = action_dict.get("direction", "down")
        distance = action_dict.get("distance", 0.5)
        target = action_dict.get("target")
        duration_ms = action_dict.get("duration_ms", 150)
        center_x, center_y = (None, None)
        if target:
            center_x, center_y = self.runtime.parse_target(target, ui_nodes)
        self.runtime.scroll_at_point(direction, distance, center_x, center_y, duration_ms)
        return {"success": True, "message": f"Scrolled {direction}", "terminal": False}

    def _exec_type_text(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        target = action_dict.get("target")
        text = action_dict.get("text")
        if not target or not text:
            raise ValueError("type_text requires 'target' and 'text'")
        clear_first = action_dict.get("clear_first", False)
        x, y = self.runtime.parse_target(target, ui_nodes)
        keyboard_was_shown = False
        try:
            keyboard_was_shown = bool(self.runtime.is_keyboard_shown())
        except Exception:
            keyboard_was_shown = False

        if keyboard_was_shown:
            try:
                self.runtime.type_text(text, clear_first, timeout_seconds=2.0)
            except WebDriverException:
                self.runtime.tap_px(x, y)
                time.sleep(0.5)
                self.runtime.type_text(text, clear_first, timeout_seconds=3.0)
        else:
            self.runtime.tap_px(x, y)
            time.sleep(0.5)
            self.runtime.type_text(text, clear_first, timeout_seconds=3.0)
        msg = f"Typed '{text[:20]}...'" if len(text) > 20 else f"Typed '{text}'"
        return {"success": True, "message": msg, "terminal": False}

    def _exec_keyboard(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        kb_action = action_dict.get("action")
        if not kb_action:
            raise ValueError("keyboard requires 'action'")
        count = action_dict.get("count", 1)
        key_map = {
            "enter": "\n",
            "search": "\n",
            "go": "\n",
            "backspace": "\b",
            "delete": "\u007F",
            "escape": "\u001B",
        }
        key_char = key_map.get(kb_action.lower())
        if not key_char:
            raise ValueError(f"Unknown keyboard action: {kb_action}")
        self.runtime.send_keys_to_active_element(key_char, repeat=count)
        return {"success": True, "message": f"Keyboard action '{kb_action}' x{count}", "terminal": False}

    def _exec_clipboard(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        clip_action = action_dict.get("action")
        if not clip_action:
            raise ValueError("clipboard requires 'action'")

        if clip_action == "set":
            text = action_dict.get("text")
            if not text:
                raise ValueError("clipboard set requires 'text'")
            self.runtime.set_clipboard_text(text)
            return {"success": True, "message": "Clipboard set", "terminal": False}

        if clip_action == "get":
            text = self.runtime.get_clipboard_text()
            return {"success": True, "message": f"Clipboard: {text}", "terminal": False, "data": text}

        if clip_action == "paste":
            self.runtime.paste()
            return {"success": True, "message": "Pasted from clipboard", "terminal": False}

        raise ValueError(f"Unknown clipboard action: {clip_action}")

    def _exec_alert(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        alert_action = action_dict.get("action")
        if not alert_action:
            raise ValueError("alert requires 'action'")

        if alert_action == "accept":
            result = self.runtime.alert_accept()
            return {"success": result, "message": "Alert accepted" if result else "No alert found", "terminal": False}

        if alert_action == "dismiss":
            result = self.runtime.alert_dismiss()
            return {"success": result, "message": "Alert dismissed" if result else "No alert found", "terminal": False}

        raise ValueError(f"Unknown alert action: {alert_action}")

    def _exec_system(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        sys_action = action_dict.get("action")
        if not sys_action:
            raise ValueError("system requires 'action'")

        if sys_action == "hideKeyboard":
            try:
                self.runtime.hide_keyboard()
                return {"success": True, "message": "Keyboard hidden", "terminal": False}
            except WebDriverException:
                return {"success": True, "message": "Keyboard not visible or already hidden", "terminal": False}

        system_actions = {
            "home": (self.runtime.press_home, "Returned to home screen"),
        }
        entry = system_actions.get(sys_action)
        if entry is None:
            raise ValueError(f"Unknown system action: {sys_action}")
        fn, message = entry
        fn()
        return {"success": True, "message": message, "terminal": False}

    def _exec_launch_app(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        bundle_id = action_dict.get("bundle_id")
        if not bundle_id:
            raise ValueError("launch_app requires 'bundle_id'")
        self.runtime.activate_app(bundle_id)
        return {"success": True, "message": f"Launched {bundle_id}", "terminal": False}

    def _exec_wait(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        ms = action_dict.get("ms", 1000)
        time.sleep(ms / 1000.0)
        return {"success": True, "message": f"Waited {ms}ms", "terminal": False}

    def _exec_seed_state(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        from platforms.ios.oracle_state import apply_seed_state

        return apply_seed_state(self.runtime, action_dict)

    def _exec_success(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        message = action_dict.get("message", "Task completed")
        return {"success": True, "message": message, "terminal": True}

    def _exec_fail(self, action_dict: Dict[str, Any], ui_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        reason = action_dict.get("reason", "Unknown failure")
        return {"success": False, "message": reason, "terminal": True}
