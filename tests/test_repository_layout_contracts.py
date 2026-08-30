from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutContractTests(unittest.TestCase):
    def test_protocol_docs_live_under_docs(self) -> None:
        protocol_dir = REPO_ROOT / "docs" / "protocol"

        self.assertTrue(protocol_dir.is_dir())
        self.assertFalse((REPO_ROOT / "protocol").exists())
        for required_doc in ("execution.md", "task.md", "model.md"):
            self.assertTrue((protocol_dir / required_doc).is_file(), required_doc)

    def test_results_are_ignored_but_docs_are_trackable(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/results/", gitignore.splitlines())

        ignored_result = subprocess.run(
            ["git", "check-ignore", "-q", "results/contract-test.json"],
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(ignored_result.returncode, 0)

        tracked_doc = subprocess.run(
            ["git", "check-ignore", "-q", "docs/protocol/execution.md"],
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(tracked_doc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
