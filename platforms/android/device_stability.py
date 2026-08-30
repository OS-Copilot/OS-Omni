"""Small recovery helpers for long Android benchmark runs."""

from __future__ import annotations

import time
from typing import Any, Mapping


_SYSTEM_DIALOG_SELECTORS = (
    {"resource_id": "android:id/aerr_wait"},
    {"text": "Wait"},
    {"resource_id": "android:id/aerr_close"},
    {"text": "Close app"},
    {"resource_id": "android:id/close_app"},
    {"text": "OK"},
)


def wait_for_device_stable(
    controller: Any,
    *,
    attempts: int = 5,
    delay_seconds: float = 1.0,
) -> dict[str, Any]:
    """Wait for basic ADB services to respond before a task initializer runs."""

    metadata: dict[str, Any] = {"attempts": 0, "dismissed_dialogs": 0}
    for attempt in range(1, max(1, attempts) + 1):
        metadata["attempts"] = attempt
        controller.execute_adb(["wait-for-device"])
        controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
        metadata["dismissed_dialogs"] += dismiss_system_dialogs(controller)

        state = str(controller.execute_adb(["get-state"]) or "").strip()
        boot_completed = str(
            controller.execute_adb(["shell", "getprop", "sys.boot_completed"]) or ""
        ).strip()
        wm_size = str(controller.execute_adb(["shell", "wm", "size"]) or "").strip()
        metadata.update(
            {
                "state": state,
                "boot_completed": boot_completed,
                "wm_size": wm_size,
            }
        )
        if state == "device" and boot_completed == "1" and "x" in wm_size:
            return metadata
        time.sleep(max(delay_seconds, 0.0))

    return metadata


def dismiss_system_dialogs(controller: Any, *, max_dialogs: int = 3) -> int:
    """Dismiss Android ANR/crash dialogs that can poison later initializers."""

    dismissed = 0
    for _ in range(max(0, max_dialogs)):
        nodes = _observe_nodes(controller)
        node = _find_node(nodes, _SYSTEM_DIALOG_SELECTORS)
        if node is None:
            break
        tap = node.get("tap")
        if not isinstance(tap, Mapping):
            break
        controller.execute_adb(["shell", "input", "tap", str(int(tap["x"])), str(int(tap["y"]))])
        dismissed += 1
        time.sleep(0.8)
    return dismissed


def _observe_nodes(controller: Any) -> list[dict[str, Any]]:
    try:
        observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
    except Exception:
        return []
    return [dict(node) for node in (getattr(observation, "ui_nodes", None) or [])]


def _find_node(
    nodes: list[dict[str, Any]],
    selectors: tuple[dict[str, str], ...],
) -> dict[str, Any] | None:
    for selector in selectors:
        for node in nodes:
            if _node_matches(node, selector):
                return node
    return None


def _node_matches(node: Mapping[str, Any], selector: Mapping[str, str]) -> bool:
    for key, expected in selector.items():
        if key == "resource_id":
            actual = str(node.get("resource_id") or node.get("resource-id") or "")
        elif key == "text":
            actual = str(node.get("text") or "")
        else:
            actual = str(node.get(key) or "")
        if actual != expected:
            return False
    return True
