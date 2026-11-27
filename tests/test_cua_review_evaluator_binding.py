"""Reviewed evaluators receive the task binding they were written against."""

from __future__ import annotations

import json
from pathlib import Path

from core.evaluation import EvalStatus, load_evaluator
from core.evaluation.context import task_binding_context, with_task_binding
from core.specs.loader import load_task_spec
from platforms.macos.host.core.types import load_task_from_file

REPO_ROOT = Path(__file__).resolve().parents[1]


class _Guest:
    """Controller whose guest commands fail or return fixed output."""

    def __init__(self, stdout: str = "", returncode: int = 1):
        self.stdout = stdout
        self.returncode = returncode
        self.scripts: list[str] = []

    def _run(self, script, timeout=None):
        self.scripts.append(script)
        return {"returncode": self.returncode, "stdout": self.stdout, "output": self.stdout}

    run_python_script = run_bash_script = run_powershell_script = _run


def _spec(relative: str):
    return load_task_spec(REPO_ROOT / relative)


def test_binding_supplies_source_instruction_and_original_evaluator() -> None:
    spec = _spec("tasks/v1/android/deltachat_bot_evidence_device_location_684193.yaml")
    provenance = spec.metadata["cua_tasks_review"]
    binding = task_binding_context(spec)

    assert binding["task_id"] == spec.task_id
    assert binding["evaluator_id"] == provenance["original_evaluator_id"]
    assert binding["instruction"] == provenance["source_instruction"]
    assert binding["instruction"] != spec.instruction
    assert with_task_binding({"task_id": "kept"}, spec)["task_id"] == "kept"


def test_binding_reads_provenance_for_macos_runner_tasks() -> None:
    path = REPO_ROOT / "tasks/v1/macos/deltachat_atlas_access_fixes.yaml"
    task = load_task_from_file(str(path))
    spec = load_task_spec(path)
    binding = task_binding_context(task)

    assert binding["task_id"] == spec.task_id
    assert binding["instruction"] == spec.metadata["cua_tasks_review"]["source_instruction"]


def test_opentrip_seed_baseline_is_read_from_the_guest() -> None:
    from evaluators.cua_review.platforms.linux.opentrip_support import (
        read_opentrip_seed_baseline,
    )

    seed = {"benchmarkAccount": {"name": "Ada", "phone": "+1 555 0100"}, "defaultBookings": []}
    guest = _Guest(stdout="window.opentripSeed = " + json.dumps(seed) + ";", returncode=0)
    payload = read_opentrip_seed_baseline(guest, seed_data_path="/guest/only/seed-data.js")

    assert guest.scripts and "/guest/only/seed-data.js" in guest.scripts[0]
    assert payload["state"]["session"]["user"]["phone"] == "15550100"


def test_opendriver_logout_fails_when_the_store_is_unreadable() -> None:
    spec = _spec("tasks/v1/windows/opendriver_rider_account_support_logout.yaml")
    context = with_task_binding(
        {"params": dict(spec.evaluation.params), "controller": _Guest()}, spec
    )
    result = load_evaluator(spec.evaluation.evaluator_id).evaluate(context)

    assert result.status is EvalStatus.FAIL
    assert "store_present" in result.metadata["failed_checks"]


def test_openfood_local_state_sidecar_is_shipped() -> None:
    assert (REPO_ROOT / "evaluators/windows/checks/openfood_local_state.ps1").is_file()
