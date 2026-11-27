"""Android v1 gates no instruction states, already removed before the 2026-11-04
row verification; these tests pin the removal (scan rows AND-018/022 step
minimum, AND-023/024/027/029 OpenFood baseline file, AND-047/048/050/052
OpenPhoto baseline file)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.evaluation import EvalStatus

REPO_ROOT = Path(__file__).resolve().parents[1]
ANDROID_TASKS = REPO_ROOT / "tasks" / "v1" / "android"


def _task(name: str) -> dict[str, Any]:
    return yaml.safe_load((ANDROID_TASKS / f"{name}.yaml").read_text(encoding="utf-8"))


def _evaluator_class(task: dict[str, Any]):
    module_name, class_name = task["evaluation"]["evaluator_id"].split(":", 1)
    module = importlib.import_module(module_name)
    return module, getattr(module, class_name)


class _Controller:
    def execute_adb(self, args: list[str]) -> str:
        return ""


def _short_run(tmp_path: Path, steps: int) -> str:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lines = [json.dumps({"step_index": index + 1}) for index in range(steps)]
    (run_dir / "trajectory.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(run_dir)


# ------------------------------------------------- OpenDriver step minimum
@pytest.mark.parametrize(
    ("name", "collector", "reader"),
    [
        ("opendriver_rider_three_scheduled_bay_rides_20260729", "_collect_scheduled_evidence", "read_backend_snapshot"),
        ("opendriver_seeded_driver_profile_document_arrival_5930_20260729", "_collect_driver_evidence", "read_public_backend_snapshot"),
    ],
)
def test_opendriver_correct_state_in_few_steps_passes(monkeypatch, tmp_path, name, collector, reader) -> None:
    task = _task(name)
    params = task["evaluation"]["params"]
    assert params["min_agent_steps"] > 3  # the recorded minimum is still reported
    module, cls = _evaluator_class(task)
    monkeypatch.setattr(module, reader, lambda *args, **kwargs: {"responses": {}})
    monkeypatch.setattr(module, "read_accessibility_text", lambda controller: "")
    monkeypatch.setattr(cls, collector, classmethod(lambda klass, **kwargs: {"checks": {"state_matches": True}}))

    result = cls().evaluate({"controller": _Controller(), "params": params, "run_dir": _short_run(tmp_path, 3)})

    assert result.status is EvalStatus.PASS, result.metadata["failures"]
    assert "min_agent_steps_met" not in result.metadata["checks"]
    assert result.metadata["trajectory"]["agent_step_count"] == 3
    assert result.metadata["trajectory"]["min_agent_steps_met"] is False


# ------------------------------------------------- OpenFood baseline file
OPENFOOD_TASKS = (
    "openfood_dumpling_biryani_coupon_merchant_clean_20260731",
    "openfood_poke_sushi_wallet_merchant_clean_20260729",
    "openfood_smokehouse_espresso_feast20_merchant_clean_20260801",
    "openfood_smokehouse_pizza_merchant_ops_clean_20260729",
)


@pytest.mark.parametrize("name", OPENFOOD_TASKS)
def test_openfood_full_run_without_the_baseline_file_is_judged_on_state(monkeypatch, tmp_path, name) -> None:
    task = _task(name)
    _, cls = _evaluator_class(task)
    monkeypatch.setattr(cls, "_collect_state", classmethod(lambda klass, context, params: {}))
    for method in ("_check_orders", "_check_support_ticket", "_check_coupon_evidence",
                   "_check_process_events", "_check_merchant_state", "_check_final_ui"):
        monkeypatch.setattr(cls, method, lambda self, *args, **kwargs: [])
    run_dir = tmp_path / "run"
    run_dir.mkdir()  # the v1 initializer writes no openfood_baseline.json here

    params = task["evaluation"]["params"]
    result = cls().evaluate({"controller": _Controller(), "params": params, "run_dir": str(run_dir)})
    assert result.status is EvalStatus.PASS, result.metadata["failures"]

    # The old default (require the file) failed every full v1 run regardless of state.
    strict = cls().evaluate(
        {"controller": _Controller(), "params": dict(params, require_clean_initializer_baseline=True), "run_dir": str(run_dir)}
    )
    assert strict.metadata["failures"] == ["initializer baseline file is missing: openfood_baseline.json"]


# ------------------------------------------------- OpenPhoto baseline file
OPENPHOTO_TASKS = (
    "openphoto_clown_dual_calibrated_export_20260804",
    "openphoto_coastal_dual_calibrated_export_20260803",
    "openphoto_cooking_dual_calibrated_export_20260804",
    "openphoto_guitar_dual_calibrated_export_20260804",
)


@pytest.mark.parametrize("name", OPENPHOTO_TASKS)
def test_openphoto_full_run_without_the_baseline_file_is_not_failed_for_it(tmp_path, name) -> None:
    task = _task(name)
    _, cls = _evaluator_class(task)
    run_dir = tmp_path / "run"
    run_dir.mkdir()  # no openphoto_calibrated_baseline.json (e.g. the initializer could not write it)
    params = task["evaluation"]["params"]

    result = cls().evaluate({"controller": _Controller(), "params": params, "run_dir": str(run_dir)})
    assert result.metadata["checks"]["baseline_available_or_not_required"] is True
    assert "baseline_available_or_not_required" not in result.metadata["failures"]

    strict = cls().evaluate(
        {"controller": _Controller(), "params": dict(params, require_baseline_for_run_dir=True), "run_dir": str(run_dir)}
    )
    assert strict.metadata["checks"]["baseline_available_or_not_required"] is False
