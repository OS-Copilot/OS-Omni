import os
from pathlib import Path

import pytest

from platforms.ios.runners.benchmark import _child_pythonpath


def test_child_pythonpath_uses_repo_root_and_discards_relative_entries(tmp_path):
    absolute_extra = str((tmp_path / "extra").resolve())
    result = _child_pythonpath(tmp_path, os.pathsep.join([".", "", absolute_extra]))
    assert result.split(os.pathsep) == [str(tmp_path.resolve()), absolute_extra]


def test_direct_cli_child_imports_repository_core_before_platform_shadow():
    import subprocess
    import sys
    # The child imports the iOS runtime (Appium/Selenium) before it reads the
    # task file, so without them it can never reach the FileNotFoundError.
    pytest.importorskip("appium")
    pytest.importorskip("selenium")
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = _child_pythonpath(repo_root, ".")
    result = subprocess.run(
        [sys.executable, str(repo_root / "platforms/ios/cli.py"),
         "__benchmark_job", "--task-file", "/tmp/os-omni-import-probe-nonexistent.yaml",
         "--model", "deepseek_flash", "--udid", "UNUSED"],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "FileNotFoundError" in result.stderr
    assert "core.artifacts" not in result.stderr
