from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.launcher import prepare_execution_summary
from core.llm.types import ModelSpec
from core.specs.errors import SpecValidationError
from core.specs.loader import load_execution_spec, load_task_specs
from core.specs.types import PreparedExecution


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_PATH = REPO_ROOT / "tasks" / "windows" / "notepad_append_text.yaml"


def _write_execution(path: Path, extra: str = "") -> None:
    path.write_text(
        "\n".join(
            [
                "tasks:",
                f"  - {TASK_PATH}",
                "models:",
                "  - gpt5_4",
                "action_mode: code_adapter",
                "observation_mode: screenshot_only",
                "history_window: 3",
                extra,
            ]
        ),
        encoding="utf-8",
    )


class ExecutionActionModeContractTests(unittest.TestCase):
    def test_loader_preserves_code_adapter_action_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            execution_path = Path(tmpdir) / "execution.yaml"
            _write_execution(execution_path)

            spec = load_execution_spec(execution_path)

        self.assertEqual(spec.action_mode, "code_adapter")
        self.assertEqual(spec.observation_mode, "screenshot_only")
        self.assertEqual(spec.history_window, 3)

    def test_loader_strips_action_mode_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            execution_path = Path(tmpdir) / "execution.yaml"
            _write_execution(execution_path)
            text = execution_path.read_text(encoding="utf-8")
            execution_path.write_text(text.replace("action_mode: code_adapter", "action_mode: ' code_adapter '"), encoding="utf-8")

            spec = load_execution_spec(execution_path)

        self.assertEqual(spec.action_mode, "code_adapter")

    def test_loader_rejects_removed_runtime_fields(self) -> None:
        stale_fields = ["agent: {}", "decision_backend: json"]
        for stale_field in stale_fields:
            with self.subTest(stale_field=stale_field):
                with tempfile.TemporaryDirectory() as tmpdir:
                    execution_path = Path(tmpdir) / "execution.yaml"
                    _write_execution(execution_path, extra=stale_field)

                    with self.assertRaises(SpecValidationError):
                        load_execution_spec(execution_path)

    def test_execution_summary_reports_code_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            execution_path = Path(tmpdir) / "execution.yaml"
            _write_execution(execution_path)
            execution = load_execution_spec(execution_path)

        prepared = PreparedExecution(
            execution=execution,
            tasks=load_task_specs(execution.task_paths),
            models=[
                ModelSpec(
                    model_id="gpt5_4",
                    provider="openai",
                    model_name="gpt-5.4",
                    api_key_env="OPENAI_API_KEY",
                )
            ],
            platform="windows",
        )

        summary = prepare_execution_summary(prepared)

        self.assertEqual(summary["action_mode"], "code_adapter")
        self.assertEqual(summary["platform"], "windows")
        self.assertEqual(summary["task_count"], 1)


if __name__ == "__main__":
    unittest.main()
