"""LNX-066: qa66 seed folders.

The brief says the existing Local Folders "must remain in place"; the task's verifier_rules
say a seed folder missing from the snapshot must not fail an otherwise correct answer.  The
initializer records the folders directly under Local Folders, and only those must still be
there at the end; a seed folder the snapshot never had stays diagnostic.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.evaluation import EvalStatus
from evaluators.cua_review.evaluators.linux import thunderbird

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tasks/v1/linux/thunderbird_qa66_mail_folder_search_calendar.yaml"
GUEST_PROFILE = "/home/user/.thunderbird/t5q2a5hp.default-release"
GUEST_BASELINE = "/tmp/os_omni_qa66_seed_folders.json"


class LocalPython:
    def run_python_script(self, code, timeout=60):
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout)
        return {"returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr}


def _task():
    return yaml.safe_load(TASK.read_text(encoding="utf-8"))


def _baseline_snippet() -> str:
    script = _task()["init"]["params"]["steps"][0]["script"]
    block = script.split("# Record the folders", 1)[1].split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    return block


def _profile(tmp_path: Path, seed_folders) -> Path:
    local = tmp_path / "profile" / "Mail" / "Local Folders"
    local.mkdir(parents=True)
    for name in [*seed_folders, "Unsent Messages"]:
        (local / name).write_text("", encoding="utf-8")
        (local / (name + ".msf")).write_text("", encoding="utf-8")
    return local


def _run_init(tmp_path: Path) -> Path:
    baseline = tmp_path / "baseline.json"
    code = _baseline_snippet().replace(GUEST_PROFILE, str(tmp_path / "profile")).replace(GUEST_BASELINE, str(baseline))
    subprocess.run([sys.executable, "-c", code], check=True)
    return baseline


def _finish(local: Path) -> None:
    (local / "qa66box").write_text("", encoding="utf-8")
    (local / "qa66box.msf").write_text("", encoding="utf-8")


def _evaluate(tmp_path: Path, monkeypatch, *, baseline: Path | None):
    monkeypatch.setattr(thunderbird, "read_calendar_evidence",
                        lambda controller, params: {"profiles": [{"events": [{"title": "qa66 event"}]}]})
    params = dict(_task()["evaluation"]["params"])
    params["profile_dir"] = str(tmp_path / "profile")
    if baseline is None:
        params.pop("seed_folder_baseline_path")
    else:
        params["seed_folder_baseline_path"] = str(baseline)
    return thunderbird.ThunderbirdFolderCalendarEvaluator().evaluate({"controller": LocalPython(), "params": params})


SEEDS = _task()["evaluation"]["params"]["expected_seed_folders"]


def test_untouched_seed_folders_and_new_folder_pass(tmp_path, monkeypatch):
    local = _profile(tmp_path, SEEDS)
    baseline = _run_init(tmp_path)
    _finish(local)
    result = _evaluate(tmp_path, monkeypatch, baseline=baseline)
    assert result.status == EvalStatus.PASS, result.metadata
    assert set(SEEDS) <= set(result.metadata["seed_folder_baseline"])


@pytest.mark.parametrize("how", ["deleted", "moved_to_trash", "nested"])
def test_a_seed_folder_the_agent_removed_fails(tmp_path, monkeypatch, how):
    local = _profile(tmp_path, SEEDS)
    baseline = _run_init(tmp_path)
    _finish(local)
    (local / "Bills.msf").unlink()
    if how == "deleted":
        (local / "Bills").unlink()
    else:
        parent = local / ("Trash.sbd" if how == "moved_to_trash" else "qa66box.sbd")
        parent.mkdir()
        shutil.move(str(local / "Bills"), str(parent / "Bills"))
    result = _evaluate(tmp_path, monkeypatch, baseline=baseline)
    assert result.status == EvalStatus.FAIL
    assert result.metadata["failures"] == ["seed_folder:Bills"]


def test_old_evaluator_let_a_removed_seed_folder_pass(tmp_path, monkeypatch):
    # Without a recorded baseline every seed folder is diagnostic, as after bacd178.
    local = _profile(tmp_path, SEEDS)
    _finish(local)
    (local / "Bills").unlink()
    result = _evaluate(tmp_path, monkeypatch, baseline=None)
    assert result.status == EvalStatus.PASS
    assert result.metadata["diagnostic_failures"] == ["seed_folder:Bills"]


def test_seed_folder_missing_from_the_snapshot_stays_diagnostic(tmp_path, monkeypatch):
    local = _profile(tmp_path, [name for name in SEEDS if name != "Promotions Receipts"])
    baseline = _run_init(tmp_path)
    _finish(local)
    result = _evaluate(tmp_path, monkeypatch, baseline=baseline)
    assert result.status == EvalStatus.PASS
    assert result.metadata["diagnostic_failures"] == ["seed_folder:Promotions Receipts"]


def test_missing_qa66box_still_fails(tmp_path, monkeypatch):
    _profile(tmp_path, SEEDS)
    baseline = _run_init(tmp_path)
    result = _evaluate(tmp_path, monkeypatch, baseline=baseline)
    assert result.status == EvalStatus.FAIL
    assert result.metadata["failures"] == ["folder:qa66box"]
