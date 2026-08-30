"""Evaluator for SystemBluetoothTurnOn task.

Verifies that Bluetooth has been successfully turned on by querying the
Android system settings via ADB.

Reference: android_world/task_evals/single/system.py
           _SystemBluetoothToggle.is_successful()
"""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class SystemBluetoothTurnOnEvaluator(BaseEvaluator):
    """Validate that Bluetooth is in the expected state (on or off)."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        expected_state = str(params.get("expected_state", "on")).strip().lower()

        if expected_state not in ("on", "off"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"expected_state must be 'on' or 'off', got '{expected_state}'",
            )

        # ------------------------------------------------------------------
        # Strategy 1: Query Bluetooth state via ADB
        # ------------------------------------------------------------------
        if controller is not None and hasattr(controller, "execute_adb"):
            try:
                result = controller.execute_adb([
                    "shell", "settings", "get", "global", "bluetooth_on",
                ])
                bluetooth_status = str(result).strip() if result else ""

                if expected_state == "on":
                    # Bluetooth is on when the value is "1"
                    is_correct = bluetooth_status == "1"
                else:
                    # Bluetooth is off when the value is "0"
                    is_correct = bluetooth_status == "0"

                if is_correct:
                    return EvalResult(
                        status=EvalStatus.PASS,
                        message=f"Bluetooth is '{expected_state}' as expected",
                        metadata={
                            "expected_state": expected_state,
                            "bluetooth_on_value": bluetooth_status,
                        },
                    )
                else:
                    actual_state = "on" if bluetooth_status == "1" else "off"
                    return EvalResult(
                        status=EvalStatus.FAIL,
                        message=(
                            f"Expected Bluetooth '{expected_state}', "
                            f"but it is '{actual_state}' "
                            f"(bluetooth_on={bluetooth_status})"
                        ),
                        metadata={
                            "expected_state": expected_state,
                            "actual_state": actual_state,
                            "bluetooth_on_value": bluetooth_status,
                        },
                    )

            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Error querying Bluetooth state: {exc}",
                    metadata={"expected_state": expected_state},
                )

        # ------------------------------------------------------------------
        # Strategy 2: Inspect the final observation UI tree
        # ------------------------------------------------------------------
        final_observation = context.get("final_observation")
        if final_observation is not None:
            ui_nodes = getattr(final_observation, "ui_nodes", []) or []

            for node in ui_nodes:
                text = str(getattr(node, "text", "") or "").lower()
                desc = str(getattr(node, "content_description", "") or "").lower()
                combined = text + " " + desc

                if "bluetooth" in combined:
                    # Look for toggle state indicators
                    checked = getattr(node, "checked", None)
                    if checked is not None:
                        bt_on = bool(checked)
                        expected_on = expected_state == "on"
                        if bt_on == expected_on:
                            return EvalResult(
                                status=EvalStatus.PASS,
                                message=f"Bluetooth toggle shows '{expected_state}'",
                                metadata={
                                    "expected_state": expected_state,
                                    "checked": bt_on,
                                },
                            )
                        else:
                            return EvalResult(
                                status=EvalStatus.FAIL,
                                message=f"Bluetooth toggle shows the opposite state",
                                metadata={
                                    "expected_state": expected_state,
                                    "checked": bt_on,
                                },
                            )

            return EvalResult(
                status=EvalStatus.UNDETERMINED,
                message="Bluetooth toggle not found in the UI tree",
                metadata={"expected_state": expected_state},
            )

        return EvalResult(
            status=EvalStatus.ERROR,
            message="Neither controller.execute_adb nor final_observation available",
        )
