"""LNX-055 / LNX-071: the release-packet briefs fix the *first* sentence(s) of
notes/release-summary.md, not the seeded "Keep this note ..." line or the line layout.

The Gedit workspace evaluators are run against a local workspace (their guest command is
plain bash + python3).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from core.evaluation import EvalStatus
from evaluators.linux.notepadqq import NotepadqqWorkspaceEvaluator
from evaluators.linux.vscode import VSCodeWorkspaceEvaluator

ROOT = Path(__file__).resolve().parents[1]
NOTEPADQQ = ROOT / "tasks/v1/linux/notepadqq_prepare_release_packet_hard.yaml"
VSCODE = ROOT / "tasks/v1/linux/vscode_prepare_release_packet_hard.yaml"

NQ_FIRST = ("Release 5.4.2 is owned by Elena Park and rolls out on 2026-06-12 for linux, windows, "
            "and android.")
NQ_SECOND = "QA is Ready for sign-off and rollback is owned by Mina Sol."
VS_FIRST = ("Release 2.7.4 is owned by Priya Nair and rolls out on 2026-05-02 with fast-sync, "
            "side-panel, and share-sheet enabled.")


class LocalBash:
    def run_bash_script(self, script, timeout=20):
        done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=timeout)
        return {"returncode": done.returncode, "output": done.stdout or done.stderr}


def _evaluate(task_path: Path, evaluator, tmp_path: Path, summary: str):
    params = yaml.safe_load(task_path.read_text(encoding="utf-8"))["evaluation"]["params"]
    workspace = tmp_path / "workspace"
    for item in params["files"]:
        target = workspace / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if "json" in item:
            target.write_text(json.dumps(item["json"], indent=2) + "\n", encoding="utf-8")
        else:
            target.write_text(summary, encoding="utf-8")
    params = {**params, "workspace_path": str(workspace)}
    return evaluator.evaluate({"controller": LocalBash(), "params": params})


@pytest.mark.parametrize("summary", [
    f"{NQ_FIRST} {NQ_SECOND}\n\nKeep this note short.\n",  # the saved Opus 5.5 file
    f"{NQ_FIRST} {NQ_SECOND}\n",
    f"{NQ_FIRST}\n{NQ_SECOND}\n",
])
def test_notepadqq_summary_opening_with_both_sentences_passes(tmp_path, summary):
    result = _evaluate(NOTEPADQQ, NotepadqqWorkspaceEvaluator(), tmp_path, summary)
    assert result.status == EvalStatus.PASS, result.message


@pytest.mark.parametrize("summary", [
    # The placeholder is still the first sentence: the old substring check passed this.
    f"Summary goes here. {NQ_FIRST} {NQ_SECOND}\n\nKeep this note short.\n",
    f"{NQ_FIRST}\n\nKeep this note short.\n",
    f"{NQ_SECOND} {NQ_FIRST}\n",
])
def test_notepadqq_summary_not_opening_with_the_two_sentences_fails(tmp_path, summary):
    result = _evaluate(NOTEPADQQ, NotepadqqWorkspaceEvaluator(), tmp_path, summary)
    assert result.status == EvalStatus.FAIL
    assert "release-summary.md" in result.message


@pytest.mark.parametrize("summary", [
    f"{VS_FIRST}\n\n",  # the saved Opus 5.5 file (failed the original byte-exact check)
    f"{VS_FIRST}\n\nKeep this note under 2 sentences.\n",
])
def test_vscode_summary_opening_with_the_sentence_passes(tmp_path, summary):
    result = _evaluate(VSCODE, VSCodeWorkspaceEvaluator(), tmp_path, summary)
    assert result.status == EvalStatus.PASS, result.message


@pytest.mark.parametrize("summary", [
    f"Release summary goes here. {VS_FIRST}\n",
    "Release summary goes here.\n\nKeep this note under 2 sentences.\n",
])
def test_vscode_summary_not_opening_with_the_sentence_fails(tmp_path, summary):
    result = _evaluate(VSCODE, VSCodeWorkspaceEvaluator(), tmp_path, summary)
    assert result.status == EvalStatus.FAIL
