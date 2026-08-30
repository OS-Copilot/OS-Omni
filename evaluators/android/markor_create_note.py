"""Evaluator for MarkorCreateNote task.

Verifies that a note with the specified filename and text content has been
created in the Markor app by checking the filesystem on the Android device
via ADB.

Reference: android_world/task_evals/single/markor.py
"""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


# Default Markor documents directory on Android
_MARKOR_DOCUMENTS_DIR = "/storage/emulated/0/Documents/markor"
_MARKOR_QUICKNOTE_DIR = "/storage/emulated/0/Documents/QuickNote"


class MarkorCreateNoteEvaluator(BaseEvaluator):
    """Validate that a Markor note was created with the expected content."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        expected_file_name = str(params.get("file_name", "")).strip()
        expected_text = str(params.get("text", "")).strip()
        allowed_directories = [
            str(path).strip().rstrip("/")
            for path in (
                params.get("allowed_directories")
                or [_MARKOR_DOCUMENTS_DIR, _MARKOR_QUICKNOTE_DIR]
            )
            if str(path).strip()
        ]
        allow_recursive_search = bool(params.get("allow_recursive_search", False))

        if not expected_file_name:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.file_name is required",
            )

        # ------------------------------------------------------------------
        # Strategy 1: Check file existence and content via ADB
        # ------------------------------------------------------------------
        if controller is not None and hasattr(controller, "execute_adb"):
            try:
                searched_paths = [f"{base}/{expected_file_name}" for base in allowed_directories]
                file_path = searched_paths[0]

                # Step 1: Check only known Markor output directories by default.
                for candidate_path in searched_paths:
                    exists_result = controller.execute_adb([
                        "shell", "test", "-f", candidate_path, "&&", "echo", "EXISTS",
                        "||", "echo", "NOT_FOUND",
                    ])
                    exists_output = str(exists_result).strip() if exists_result else ""
                    if "EXISTS" in exists_output:
                        file_path = candidate_path
                        break
                else:
                    if allow_recursive_search:
                        find_result = controller.execute_adb([
                            "shell", "find", "/storage/emulated/0",
                            "-name", expected_file_name,
                            "-type", "f",
                        ])
                        find_output = str(find_result).strip() if find_result else ""

                        if find_output and expected_file_name in find_output:
                            # Take the first match
                            file_path = find_output.splitlines()[0].strip()
                        else:
                            return EvalResult(
                                status=EvalStatus.FAIL,
                                message=f"File '{expected_file_name}' not found on the device",
                                metadata={
                                    "expected_file_name": expected_file_name,
                                    "searched_paths": searched_paths,
                                },
                            )
                    else:
                        return EvalResult(
                            status=EvalStatus.FAIL,
                            message=f"File '{expected_file_name}' not found in known Markor note directories",
                            metadata={
                                "expected_file_name": expected_file_name,
                                "searched_paths": searched_paths,
                            },
                        )

                # Step 2: Read the file content and compare
                if expected_text:
                    content_result = controller.execute_adb([
                        "shell", "cat", file_path,
                    ])
                    actual_content = str(content_result).strip() if content_result else ""

                    if self._text_matches(expected_text, actual_content):
                        return EvalResult(
                            status=EvalStatus.PASS,
                            message=f"Note '{expected_file_name}' created with correct content",
                            metadata={
                                "expected_file_name": expected_file_name,
                                "file_path": file_path,
                                "content_length": len(actual_content),
                            },
                        )
                    else:
                        return EvalResult(
                            status=EvalStatus.FAIL,
                            message=(
                                f"Note '{expected_file_name}' exists but content "
                                f"does not match expected text"
                            ),
                            metadata={
                                "expected_file_name": expected_file_name,
                                "expected_text": expected_text[:200],
                                "actual_content": actual_content[:200],
                                "file_path": file_path,
                            },
                        )
                else:
                    # No text to verify, just file existence
                    return EvalResult(
                        status=EvalStatus.PASS,
                        message=f"Note '{expected_file_name}' exists on the device",
                        metadata={
                            "expected_file_name": expected_file_name,
                            "file_path": file_path,
                        },
                    )

            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Error checking Markor note: {exc}",
                    metadata={
                        "expected_file_name": expected_file_name,
                        "expected_text": expected_text[:100],
                    },
                )

        # ------------------------------------------------------------------
        # Strategy 2: Inspect the final observation UI tree
        # ------------------------------------------------------------------
        final_observation = context.get("final_observation")
        if final_observation is not None:
            ui_nodes = getattr(final_observation, "ui_nodes", []) or []
            file_name_without_ext = expected_file_name.rsplit(".", 1)[0]

            name_visible = False
            content_visible = False

            for node in ui_nodes:
                text = str(getattr(node, "text", "") or "")
                if not text:
                    if isinstance(node, dict):
                        text = str(node.get("text", "") or "")

                if file_name_without_ext.lower() in text.lower():
                    name_visible = True
                if expected_text and expected_text.lower() in text.lower():
                    content_visible = True

            if name_visible and (content_visible or not expected_text):
                return EvalResult(
                    status=EvalStatus.PASS,
                    message=f"Note '{expected_file_name}' and its content are visible in the UI",
                    metadata={
                        "expected_file_name": expected_file_name,
                        "name_visible": name_visible,
                        "content_visible": content_visible,
                    },
                )
            elif name_visible:
                return EvalResult(
                    status=EvalStatus.UNDETERMINED,
                    message=f"Note name is visible but content could not be verified from UI",
                    metadata={
                        "expected_file_name": expected_file_name,
                        "name_visible": name_visible,
                        "content_visible": content_visible,
                    },
                )
            else:
                return EvalResult(
                    status=EvalStatus.UNDETERMINED,
                    message="Could not confirm note creation from UI alone",
                    metadata={
                        "expected_file_name": expected_file_name,
                    },
                )

        return EvalResult(
            status=EvalStatus.ERROR,
            message="Neither controller.execute_adb nor final_observation available",
        )

    @staticmethod
    def _text_matches(expected: str, actual: str) -> bool:
        """Fuzzy text comparison, ignoring leading/trailing whitespace."""
        return expected.strip().lower() in actual.strip().lower()
