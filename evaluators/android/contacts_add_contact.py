"""Evaluator for ContactsAddContact task.

Checks whether a contact with the given name and phone number has been
successfully created on the Android device by querying the contacts
content provider via ADB.

Reference: android_world/task_evals/single/contacts.py
           android_world/task_evals/common_validators/contacts_validators.py
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class ContactsAddContactEvaluator(BaseEvaluator):
    """Validate that a contact with the expected name and number exists."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        expected_name = str(params.get("name", "")).strip()
        expected_number = str(params.get("number", "")).strip()

        if not expected_name:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.name is required",
            )

        # ------------------------------------------------------------------
        # Strategy 1: Query contacts via ADB content provider
        # ------------------------------------------------------------------
        if controller is not None and hasattr(controller, "execute_adb"):
            try:
                # Query the contacts content provider for the display name
                result = controller.execute_adb([
                    "shell", "content", "query",
                    "--uri", "content://com.android.contacts/contacts",
                    "--projection", "display_name",
                ])
                contacts_output = str(result) if result else ""

                name_found = self._name_matches(expected_name, contacts_output)

                if not name_found:
                    return EvalResult(
                        status=EvalStatus.FAIL,
                        message=f"Contact '{expected_name}' not found in contacts database",
                        metadata={
                            "expected_name": expected_name,
                            "expected_number": expected_number,
                            "contacts_output": contacts_output[:500],
                        },
                    )

                # If a phone number is expected, verify it as well
                if expected_number:
                    phone_result = controller.execute_adb([
                        "shell", "content", "query",
                        "--uri", "content://com.android.contacts/data/phones",
                        "--projection", "display_name:data1",
                    ])
                    phone_output = str(phone_result) if phone_result else ""
                    number_found = self._number_matches(
                        expected_number, phone_output
                    )

                    if not number_found:
                        return EvalResult(
                            status=EvalStatus.FAIL,
                            message=(
                                f"Contact '{expected_name}' exists but phone "
                                f"number '{expected_number}' was not found"
                            ),
                            metadata={
                                "expected_name": expected_name,
                                "expected_number": expected_number,
                                "phone_output": phone_output[:500],
                            },
                        )

                return EvalResult(
                    status=EvalStatus.PASS,
                    message=f"Contact '{expected_name}' with number '{expected_number}' found",
                    metadata={
                        "expected_name": expected_name,
                        "expected_number": expected_number,
                    },
                )

            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Error querying contacts: {exc}",
                    metadata={
                        "expected_name": expected_name,
                        "expected_number": expected_number,
                    },
                )

        # ------------------------------------------------------------------
        # Strategy 2: Inspect the final observation UI tree
        # ------------------------------------------------------------------
        final_observation = context.get("final_observation")
        if final_observation is not None:
            ui_nodes = getattr(final_observation, "ui_nodes", []) or []
            name_visible = any(
                self._text_contains(expected_name, str(getattr(node, "text", "") or ""))
                for node in ui_nodes
            )

            if name_visible:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message=f"Contact '{expected_name}' is visible in the UI",
                    metadata={
                        "expected_name": expected_name,
                        "expected_number": expected_number,
                    },
                )
            else:
                return EvalResult(
                    status=EvalStatus.UNDETERMINED,
                    message=(
                        "Could not confirm contact creation from UI alone; "
                        "contact name not visible on final screen"
                    ),
                    metadata={
                        "expected_name": expected_name,
                        "expected_number": expected_number,
                    },
                )

        return EvalResult(
            status=EvalStatus.ERROR,
            message="Neither controller.execute_adb nor final_observation available",
        )

    @staticmethod
    def _normalize_number(number: str) -> str:
        """Strip all non-digit characters for comparison."""
        return re.sub(r"\D", "", number)

    @classmethod
    def _name_matches(cls, expected: str, output: str) -> bool:
        """Check if the expected name appears in the ADB query output."""
        return expected.lower() in output.lower()

    @classmethod
    def _number_matches(cls, expected: str, output: str) -> bool:
        """Check if the expected phone number appears in the ADB query output."""
        normalized_expected = cls._normalize_number(expected)
        normalized_output = cls._normalize_number(output)
        return normalized_expected in normalized_output

    @staticmethod
    def _text_contains(expected: str, actual: str) -> bool:
        return expected.lower().strip() in actual.lower().strip()
