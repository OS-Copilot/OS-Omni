from pathlib import Path

import pytest
import yaml

from platforms.ios import cli


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_PATH = REPO_ROOT / "tasks/v1/ios/contacts_add_contact_card.yaml"


def _run_execution(monkeypatch, tmp_path, **execution_fields):
    execution_path = tmp_path / "ios_exec.yaml"
    execution_path.write_text(
        yaml.safe_dump({"tasks": [str(TASK_PATH)], "models": ["fake_model"], **execution_fields}),
        encoding="utf-8",
    )
    captured = []
    monkeypatch.setattr(cli, "IOS_RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(cli, "_run_benchmark_command", lambda args: captured.append(args) or 0)
    exit_code = cli._run_execution_command(type("Args", (), {"execution": str(execution_path)})())
    return exit_code, captured


def test_execution_max_steps_is_passed_to_benchmark(monkeypatch, tmp_path):
    exit_code, captured = _run_execution(monkeypatch, tmp_path, max_steps=300)

    assert exit_code == 0
    assert [args.max_steps for args in captured] == [300]


def test_execution_without_max_steps_keeps_task_limit(monkeypatch, tmp_path):
    _, captured = _run_execution(monkeypatch, tmp_path)

    assert [args.max_steps for args in captured] == [None]


@pytest.mark.parametrize("value", [0, -1, "300", True])
def test_execution_rejects_invalid_max_steps(monkeypatch, tmp_path, value):
    with pytest.raises(ValueError, match="max_steps"):
        _run_execution(monkeypatch, tmp_path, max_steps=value)


def test_v1_ios_execution_uses_300_max_steps():
    execution = yaml.safe_load((REPO_ROOT / "executions/v1/ios.yaml").read_text(encoding="utf-8"))

    assert execution["max_steps"] == 300
