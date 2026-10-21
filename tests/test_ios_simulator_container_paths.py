from pathlib import Path
import subprocess

import pytest

from platforms.ios.runtime_env import simulator_manager


SOURCE_UDID = "11111111-1111-4111-8111-111111111111"
CLONE_UDID = "22222222-2222-4222-8222-222222222222"


def _devices_root(home: Path) -> Path:
    return home / "Library" / "Developer" / "CoreSimulator" / "Devices"


def test_remaps_clone_container_to_clone_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    relative = Path("data/Containers/Data/Application/APP-UUID")
    source = _devices_root(tmp_path) / SOURCE_UDID / relative
    clone = _devices_root(tmp_path) / CLONE_UDID / relative
    source.mkdir(parents=True)
    clone.mkdir(parents=True)

    resolved = simulator_manager.remap_simulator_container_path(source, CLONE_UDID)

    assert resolved == clone.resolve()
    assert resolved != source.resolve()


def test_keeps_path_when_simctl_reports_requested_simulator(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    container = _devices_root(tmp_path) / CLONE_UDID / "data/Containers/App"
    container.mkdir(parents=True)

    assert simulator_manager.remap_simulator_container_path(
        container, CLONE_UDID
    ) == container.resolve()


def test_fails_closed_when_clone_container_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    source = _devices_root(tmp_path) / SOURCE_UDID / "data/Containers/App"
    source.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="corresponding container is missing"):
        simulator_manager.remap_simulator_container_path(source, CLONE_UDID)


def test_get_app_container_path_rebases_simctl_result(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    relative = Path("data/Containers/Data/Application/APP-UUID")
    source = _devices_root(tmp_path) / SOURCE_UDID / relative
    clone = _devices_root(tmp_path) / CLONE_UDID / relative
    source.mkdir(parents=True)
    clone.mkdir(parents=True)
    monkeypatch.setattr(
        simulator_manager,
        "run_cmd",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, str(source) + "\n", ""
        ),
    )

    resolved = simulator_manager.get_app_container_path(
        CLONE_UDID, "example.bundle", "data"
    )

    assert resolved == clone.resolve()
