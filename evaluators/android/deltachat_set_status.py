"""Evaluator for the Delta Chat set-status task.

Verifies that the user's status text has been set to the expected value
by reading Delta Chat's internal database via ADB.
"""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class DeltaChatSetStatusEvaluator(BaseEvaluator):
    """Validate that the Delta Chat profile status was set correctly."""

    DEFAULT_APP_PACKAGE = "chat.delta"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        expected_status = str(params.get("expected_status") or "").strip()
        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()

        if not expected_status:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.expected_status is required",
            )

        # ------------------------------------------------------------------
        # Strategy 1: Read selfstatus from Delta Chat's internal database
        # ------------------------------------------------------------------
        if controller is not None and hasattr(controller, "execute_adb"):
            try:
                # Delta Chat stores config in an SQLite database.
                # Delta Chat v2.49.0+ uses STRICT tables (SQLite 3.37.0+) which are incompatible
                # with the older SQLite binary built into the Android emulator, causing
                # 'malformed database schema' errors when querying `dc.db`.
                # Additionally, the status may only exist in the write-ahead log (`dc.db-wal`).
                # We can safely evaluate the task by testing if the expected string exists
                # as a binary string inside any file in the accounts directory.
                
                # Escape expected_status for grep
                escaped_status = expected_status.replace('"', '\\"')
                grep_cmd = f"grep -ri \"{escaped_status}\" /data/data/{app_package}/files/accounts/"
                
                # First try executing directly (works if adbd is root)
                grep_output = controller.execute_adb(["shell", grep_cmd])
                
                if not grep_output or "Permission denied" in grep_output:
                    # Fallback to run-as
                    grep_output = controller.execute_adb(["shell", "run-as", app_package, "sh", "-c", f"'{grep_cmd}'"])

                actual_status = ""
                # If grep output contains 'matches' or the string itself, it was found
                if grep_output and ("matches" in str(grep_output) or expected_status.lower() in str(grep_output).lower()):
                    actual_status = expected_status

                if actual_status.lower() == expected_status.lower():
                    return EvalResult(
                        status=EvalStatus.PASS,
                        message=f"Status text correctly set to '{expected_status}' (binary verified)",
                        metadata={"expected_status": expected_status, "method": "binary_grep"},
                    )

                if not actual_status:
                    # Fallback: try reading shared preferences
                    prefs_cmd = f"cat /data/data/{app_package}/shared_prefs/*.xml"
                    result = controller.execute_adb(["shell", "run-as", app_package, "sh", "-c", f"'{prefs_cmd}'"])
                    prefs_output = str(result).strip() if result else ""
                    if expected_status.lower() in prefs_output.lower():
                        return EvalResult(
                            status=EvalStatus.PASS,
                            message=f"Status text '{expected_status}' found in shared preferences",
                            metadata={"expected_status": expected_status, "method": "shared_prefs"},
                        )

                if expected_status.lower() == actual_status.lower():
                    return EvalResult(
                        status=EvalStatus.PASS,
                        message=f"Status text correctly set to '{expected_status}'",
                        metadata={
                            "expected_status": expected_status,
                            "actual_status": actual_status,
                            "method": "sqlite_db",
                        },
                    )

                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Status text mismatch: expected '{expected_status}', got '{actual_status}'",
                    metadata={
                        "expected_status": expected_status,
                        "actual_status": actual_status,
                    },
                )

            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Error checking Delta Chat status: {exc}",
                    metadata={"expected_status": expected_status},
                )

        return EvalResult(
            status=EvalStatus.ERROR,
            message="controller.execute_adb not available for status verification",
        )
