from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTIONS_DIR = REPO_ROOT / "executions"
MACOS_TASKS_DIR = REPO_ROOT / "tasks" / "v1" / "macos"


class ExecutionCorpusContractTests(unittest.TestCase):
    def test_all_execution_action_modes_are_code_adapter(self) -> None:
        checked: list[Path] = []
        stale_modes: list[str] = []

        for path in sorted(EXECUTIONS_DIR.rglob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or "action_mode" not in raw:
                continue
            checked.append(path)
            mode: Any = raw["action_mode"]
            if mode != "code_adapter":
                stale_modes.append(f"{path.relative_to(REPO_ROOT)}: {mode!r}")

        self.assertGreater(len(checked), 0, "expected execution YAML files with action_mode")
        self.assertEqual(stale_modes, [])

    def test_macos_corpus_uses_allapps_base_vm(self) -> None:
        checked: list[Path] = []
        stale_overrides: list[str] = []

        macos_corpus = [
            *sorted((EXECUTIONS_DIR / "v1").glob("macos*.yaml")),
            *sorted(MACOS_TASKS_DIR.glob("*.yaml")),
        ]
        for path in macos_corpus:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            checked.append(path)
            for label, payload in (
                ("top-level", raw),
                ("metadata", raw.get("metadata")),
                ("init.params", (raw.get("init") or {}).get("params") if isinstance(raw.get("init"), dict) else None),
            ):
                if isinstance(payload, dict) and payload.get("base_vm_name") not in (None, "", "allapps-base"):
                    stale_overrides.append(
                        f"{path.relative_to(REPO_ROOT)} {label}: {payload['base_vm_name']!r}"
                    )

        self.assertGreater(len(checked), 0, "expected macOS corpus YAML files")
        self.assertEqual(stale_overrides, [])


if __name__ == "__main__":
    unittest.main()
