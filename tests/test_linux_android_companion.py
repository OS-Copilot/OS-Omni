import json
from pathlib import Path

import pytest
import yaml

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux import android_companion as composite
from platforms.linux.android_companion import CompanionSettings, scrcpy_script

ROOT = Path(__file__).resolve().parents[1]
TASKS = sorted((ROOT / "tasks/v1/cross_device").glob("linux_android_*.yaml"))


def _trajectory(tmp_path, codes):
    path = tmp_path / "trajectory.jsonl"
    path.write_text("\n".join(json.dumps({"step_index": i, "action_parse": {"type": "python_code", "code": code}})
                              for i, code in enumerate(codes, start=1)))
    return path


def test_forbidden_actions_flags_adb_and_scrcpy(tmp_path):
    path = _trajectory(tmp_path, [
        "pyautogui.click(1460, 600)",
        "import subprocess\nsubprocess.run(['adb', 'pull', '/sdcard/x.csv'])",
        "pyautogui.write('scrcpy --help')",
        "pyautogui.write('Load balancing, adbook')",
    ])
    hits = composite.forbidden_actions(path, composite.DEFAULT_FORBIDDEN)
    assert [hit["step"] for hit in hits] == [2, 3]


class _Fixed(BaseEvaluator):
    status = EvalStatus.PASS

    def evaluate(self, context):
        return EvalResult(status=self.status, message=self.status.value)


class _Fail(_Fixed):
    status = EvalStatus.FAIL


@pytest.fixture
def phone_env(monkeypatch):
    monkeypatch.setenv("OS_OMNI_ANDROID_SERIAL", "emulator-5570")
    monkeypatch.setenv("OS_OMNI_ANDROID_FORWARD", "172.17.0.1:15571")
    monkeypatch.setattr(composite, "phone_controller", lambda settings: object())


def _evaluate(trajectory, android, linux):
    params = {"android": {"evaluator_id": android}, "linux": [{"evaluator_id": spec} for spec in linux]}
    return composite.LinuxAndroidCompositeEvaluator().evaluate({"params": params, "trajectory_path": trajectory})


def test_composite_needs_every_part(tmp_path, phone_env):
    clean = _trajectory(tmp_path, ["pyautogui.click(1, 1)"])
    assert _evaluate(clean, _Fixed, [_Fixed, _Fixed]).status == EvalStatus.PASS
    assert _evaluate(clean, _Fail, [_Fixed, _Fixed]).status == EvalStatus.FAIL
    assert _evaluate(clean, _Fixed, [_Fixed, _Fail]).status == EvalStatus.FAIL
    dirty = _trajectory(tmp_path, ["import os\nos.system('adb shell input text x')"])
    result = _evaluate(dirty, _Fixed, [_Fixed, _Fixed])
    assert result.status == EvalStatus.FAIL and "gui_only" in result.message


def test_scrcpy_script_targets_forwarded_adbd():
    settings = CompanionSettings("emulator-5570", "adb", 5037, "172.17.0.1", 15571, "osomni_cross_ready")
    assert settings.adbd_port == 5571
    script = scrcpy_script(settings, x=1240, y=60, height=990)
    assert "adb connect 172.17.0.1:15571" in script
    assert "--keyboard=uhid" in script and "SCRCPY_READY" in script


@pytest.mark.parametrize("path", TASKS, ids=[path.stem for path in TASKS])
def test_linux_android_tasks_are_single_screen(path):
    task = yaml.safe_load(path.read_text())
    assert task["platform"] == "linux"
    assert task["init"]["initializer_id"] == "initializers.linux.android_companion:LinuxAndroidCompanionInitializer"
    assert task["evaluation"]["evaluator_id"] == "evaluators.linux.android_companion:LinuxAndroidCompositeEvaluator"
    name = Path(task["evaluation"]["params"]["android"]["params"]["path"]).name
    assert f"~/Desktop/{name}" in task["instruction"]
    assert "Windows" not in task["instruction"] and "Notepad" not in task["instruction"]
    # The agent brings the file over itself: the initializer must not pre-place it.
    setup = task["init"]["params"]["linux"]["steps"][0]["script"]
    assert f"rm -f /home/user/Desktop/{name}" in setup


def test_min_type_interval_prelude(monkeypatch):
    source = (ROOT / "platforms/linux/runners/base_episode.py").read_text()
    assert "OS_OMNI_MIN_TYPE_INTERVAL" in source and "pyautogui.write = pyautogui.typewrite" in source
