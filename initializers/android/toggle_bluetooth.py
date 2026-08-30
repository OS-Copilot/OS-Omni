"""Initializer for setting Bluetooth to a known state on Android.

Sets Bluetooth to a specified initial state (on/off) via ADB before the
task begins, ensuring the agent starts from a deterministic precondition.

Reference: android_world/task_evals/single/system.py
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class ToggleBluetoothInitializer(BaseInitializer):
    """Set Bluetooth to the desired initial state before the episode starts."""

    DEFAULT_WAIT_MS = 500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for Bluetooth initialization",
            )

        initial_state = str(params.get("initial_state", "off")).strip().lower()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)

        if initial_state not in ("on", "off"):
            return InitResult(
                status=InitStatus.FAIL,
                message=f"initial_state must be 'on' or 'off', got '{initial_state}'",
            )

        try:
            if not hasattr(controller, "execute_adb"):
                return InitResult(
                    status=InitStatus.ERROR,
                    message="controller.execute_adb is required for Bluetooth toggle",
                )

            # Use svc bluetooth command to toggle Bluetooth
            action = "enable" if initial_state == "on" else "disable"
            controller.execute_adb(["shell", "svc", "bluetooth", action])

            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            # Verify the state was set correctly
            result = controller.execute_adb([
                "shell", "settings", "get", "global", "bluetooth_on",
            ])
            actual_value = str(result).strip() if result else ""
            expected_value = "1" if initial_state == "on" else "0"

            if actual_value != expected_value:
                # Some devices need the settings approach instead
                controller.execute_adb([
                    "shell", "settings", "put", "global", "bluetooth_on",
                    expected_value,
                ])
                if wait_ms > 0:
                    time.sleep(wait_ms / 1000.0)
                result = controller.execute_adb([
                    "shell", "settings", "get", "global", "bluetooth_on",
                ])
                actual_value = str(result).strip() if result else ""

            if actual_value != expected_value:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=(
                        f"Bluetooth initialization did not reach '{initial_state}' "
                        f"(bluetooth_on={actual_value!r}, expected={expected_value})"
                    ),
                    metadata={
                        "initial_state": initial_state,
                        "wait_ms": wait_ms,
                        "bluetooth_on_value": actual_value,
                        "expected_value": expected_value,
                    },
                )

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to set Bluetooth to '{initial_state}': {exc}",
                metadata={"initial_state": initial_state, "wait_ms": wait_ms},
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Set Bluetooth to '{initial_state}'",
            metadata={"initial_state": initial_state, "wait_ms": wait_ms},
        )
