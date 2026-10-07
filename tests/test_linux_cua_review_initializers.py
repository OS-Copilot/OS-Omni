"""Contracts for Linux initializers reconstructed from CUA-Tasks-Review."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

from core.init import InitStatus


RECOVERED_MODULES = {
    "initializers.linux.openbank_ubuntu1_0",
    "initializers.linux.openblender",
    "initializers.linux.opencode",
    "initializers.linux.opendoc",
    "initializers.linux.openfood",
    "initializers.linux.openmail",
    "initializers.linux.opennote",
    "initializers.linux.openphoto_edit",
    "initializers.linux.openphotoedit",
    "initializers.linux.openphotoedit1_community",
    "initializers.linux.opensheet",
    "initializers.linux.opensheet_aster_review",
    "initializers.linux.opensheet_monthly_budget",
    "initializers.linux.openslide",
    "initializers.linux.opentrip",
    "initializers.linux.opentwitter",
    "initializers.linux.openwireshark",
    "initializers.linux.openzotero",
    "initializers.linux.openzotero_snapshot2",
}


class _GuestController:
    def __init__(self, *, returncode: int = 0):
        self.returncode = returncode
        self.scripts = []
        self.files = {}

    def run_bash_script(self, script, timeout=30):
        self.scripts.append((script, timeout))
        return {"returncode": self.returncode, "output": "guest failure" if self.returncode else "ok"}

    def write_file(self, path, content):
        self.files[path] = content
        return {"status": "success"}


def _linux_vm_task_paths(root):
    """Linux desktop and Web tracks both run on the Linux VM."""
    for track in ("linux", "web"):
        yield from sorted((root / "tasks" / "v1" / track).glob("*.yaml"))


def _recovered_task_specs():
    root = Path(__file__).resolve().parents[1]
    for path in _linux_vm_task_paths(root):
        task = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        init = task.get("init") or {}
        initializer_id = init.get("initializer_id")
        if initializer_id and initializer_id.partition(":")[0] in RECOVERED_MODULES:
            yield path.name, initializer_id, dict(init.get("params") or {})


def test_all_linux_v1_initializer_specs_are_importable():
    root = Path(__file__).resolve().parents[1]
    missing = []
    for path in _linux_vm_task_paths(root):
        task = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        initializer_id = (task.get("init") or {}).get("initializer_id")
        if not initializer_id:
            continue
        module_name, _, class_name = initializer_id.partition(":")
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - assertion includes the cause
            missing.append(f"{path.name}: {initializer_id}: {exc}")
            continue
        if not hasattr(module, class_name):
            missing.append(f"{path.name}: {initializer_id}: class missing")
    assert missing == []


@pytest.mark.parametrize("task_name,initializer_id,params", list(_recovered_task_specs()))
def test_recovered_initializers_execute_their_guest_contracts(
    monkeypatch, task_name, initializer_id, params
):
    monkeypatch.setattr("initializers.linux.cua_review.time.sleep", lambda _: None)
    module_name, _, class_name = initializer_id.partition(":")
    initializer = getattr(importlib.import_module(module_name), class_name)()
    controller = _GuestController()

    result = initializer.initialize({"controller": controller, "params": params})

    assert result.status is InitStatus.PASS, task_name
    assert controller.scripts or controller.files, task_name


def test_snapshot_open_app_reports_guest_launch_failure():
    from initializers.linux.openfood import OpenFoodInitializer

    result = OpenFoodInitializer().initialize(
        {"controller": _GuestController(returncode=1), "params": {"wait_ms": 0}}
    )

    assert result.status is InitStatus.ERROR
    assert "guest failure" in (result.message or "")


class _MissingCommandController(_GuestController):
    """Guest where ``command -v`` fails for every bare command name."""

    def run_bash_script(self, script, timeout=30):
        self.scripts.append((script, timeout))
        if script.startswith("command -v "):
            return {"returncode": 1, "output": ""}
        return {"returncode": 0, "output": "ok"}


def test_snapshot_open_app_falls_back_to_openapps_launcher(monkeypatch):
    from initializers.linux import opennote

    monkeypatch.setattr("initializers.linux.cua_review.time.sleep", lambda _seconds: None)
    controller = _MissingCommandController()
    result = opennote.OpenNoteInitializer().initialize(
        {"controller": controller, "params": {"app_command": "opennote", "wait_ms": 0}}
    )
    assert result.status == InitStatus.PASS
    assert result.metadata["app_command"] == "/home/user/OpenApps/bin/launch-openrednote"


def test_snapshot_open_app_uses_absolute_app_name_as_command(monkeypatch):
    from initializers.linux import opennote

    monkeypatch.setattr("initializers.linux.cua_review.time.sleep", lambda _seconds: None)
    controller = _GuestController()
    result = opennote.OpenNoteInitializer().initialize(
        {"controller": controller, "params": {"app_name": "/home/user/OpenApps/bin/launch-openrednote", "wait_ms": 0}}
    )
    assert result.status == InitStatus.PASS
    assert result.metadata["app_command"] == "/home/user/OpenApps/bin/launch-openrednote"


def test_openbank_falls_back_to_webpage_shortcut(monkeypatch):
    from initializers.linux import openbank_ubuntu1_0

    class _Controller(_GuestController):
        def run_bash_script(self, script, timeout=30):
            self.scripts.append((script, timeout))
            missing = "test -e /home/user/Desktop/OpenBank" in script.splitlines()
            return {"returncode": 1 if missing else 0, "output": ""}

    monkeypatch.setattr("initializers.linux.cua_review.time.sleep", lambda _seconds: None)
    result = openbank_ubuntu1_0.OpenBankUbuntu10Initializer().initialize(
        {"controller": _Controller(), "params": {"shortcut": "/home/user/Desktop/OpenBank", "wait_ms": 0}}
    )
    assert result.status == InitStatus.PASS
    assert result.metadata["shortcut"] == "/home/user/Desktop/webpage/OpenBank"


def test_desktop_setup_fails_on_nonzero_guest_exit_code():
    from initializers.linux.setup import DesktopSetupInitializer

    class _Controller(_GuestController):
        def run_bash_script(self, script, timeout=30, working_dir=None):
            return super().run_bash_script(script, timeout)

    controller = _Controller(returncode=1)
    params = {"steps": [{"type": "run_bash", "script": "test -f /missing"}]}
    result = DesktopSetupInitializer().initialize({"controller": controller, "params": params})
    assert result.status == InitStatus.ERROR
    assert "exit code 1" in result.message

    params = {"steps": [{"type": "run_bash", "script": "test -f /missing", "optional": True}]}
    assert DesktopSetupInitializer().initialize({"controller": controller, "params": params}).status == InitStatus.PASS


def test_openshop_server_accepts_snapshot_password_hash():
    from initializers.linux.openshop import OpenShopInitializer

    source = OpenShopInitializer._current_server_source()
    namespace = {}
    exec(source[source.index("def hash_password"):source.index('@app.get("/api/session")')], namespace)
    account = {"phone": "13800000000", "passwordHash": "fnv1a-900f7aee"}
    assert namespace["password_matches"]("spring2026", account)
    assert not namespace["password_matches"]("spring2025", account)
    assert namespace["password_matches"]("plain", {"password": "plain"})


def test_openphoto_seeds_bundled_attachments_only_when_missing():
    from initializers.linux.cua_review import BUNDLED_ATTACHMENTS_DIR, seed_bundled_attachments

    class _Controller(_GuestController):
        def __init__(self, present):
            super().__init__()
            self.present, self.uploads = set(present), []

        def run_bash_script(self, script, timeout=30):
            self.scripts.append((script, timeout))
            if script.startswith("test -e "):
                path = script.split(" ", 2)[2].strip("'")
                return {"returncode": 0 if path in self.present else 1, "output": ""}
            return {"returncode": 0, "output": ""}

        def upload_file(self, local_path, remote_path):
            self.uploads.append((local_path, remote_path))

    wanted = ["/home/user/Desktop/attachment/station_platform_wide.jpg",
              "/home/user/Desktop/attachment/station_train_arrival.jpg",
              "/home/user/Desktop/attachment/not_bundled.jpg"]
    controller = _Controller(present={wanted[1]})
    assert seed_bundled_attachments(controller, wanted) == [wanted[0]]
    assert controller.uploads == [(str(BUNDLED_ATTACHMENTS_DIR / "station_platform_wide.jpg"), wanted[0])]


def test_desktop_setup_serves_openshop_and_opens_browser_after_seeding(monkeypatch):
    from initializers.linux import openshop
    from initializers.linux.setup import DesktopSetupInitializer

    calls = []
    monkeypatch.setattr(
        openshop.OpenShopInitializer,
        "_deploy_and_launch_current_app",
        lambda self, controller, *, port, launch_browser=True: calls.append(("deploy", port, launch_browser)),
    )
    monkeypatch.setattr(
        openshop.OpenShopInitializer,
        "_open_current_app_browser",
        lambda self, controller, *, port: calls.append(("browser", port)),
    )
    params = {"steps": [
        {"type": "openshop_current_app", "port": 4310, "launch_browser": False},
        {"type": "openshop_open_browser", "port": 4310},
    ]}
    result = DesktopSetupInitializer().initialize({"controller": _GuestController(), "params": params})
    assert result.status == InitStatus.PASS
    assert calls == [("deploy", 4310, False), ("browser", 4310)]
