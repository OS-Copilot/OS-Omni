import json
from pathlib import Path
import socket
import threading
from types import SimpleNamespace

import pytest

from scripts.run_linux_qemu_batch import classify_result, qmp_command, restore_snapshot
from core.init import InitStatus
from initializers.linux.openshop import OpenShopInitializer
from platforms.linux.agent.prompt_builder import LinuxPromptBuilder


@pytest.mark.parametrize("failure", [False, True])
def test_qmp_matches_responses_while_ignoring_events(tmp_path, failure):
    address = tmp_path / "qmp.sock"
    requests = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(address))
        server.listen(1)
        server.settimeout(5)

        def respond():
            connection, _ = server.accept()
            with connection, connection.makefile("rwb") as stream:
                stream.write(b'{"QMP": {}}\n')
                stream.flush()
                for _ in range(2):
                    request = json.loads(stream.readline())
                    requests.append(request)
                    stream.write(b'{"event": "STOP"}\n')
                    response = {"id": request["id"], "return": {"running": True}}
                    if failure and request["execute"] == "query-status":
                        response = {"id": request["id"], "error": {"desc": "VM unavailable"}}
                    stream.write(json.dumps(response).encode() + b"\n")
                    stream.flush()

        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        try:
            if failure:
                with pytest.raises(RuntimeError, match="VM unavailable"):
                    qmp_command(address, "query-status")
            else:
                assert qmp_command(address, "query-status") == {"running": True}
        finally:
            thread.join(timeout=5)
        assert not thread.is_alive()
    assert [request["execute"] for request in requests] == ["qmp_capabilities", "query-status"]


def test_failed_snapshot_restore_does_not_resume_vm(monkeypatch, tmp_path):
    commands = []

    def fail_restore(socket_path, command, arguments=None):
        commands.append(command)
        return "Error: Snapshot does not exist"

    monkeypatch.setattr("scripts.run_linux_qemu_batch.qmp_command", fail_restore)
    with pytest.raises(RuntimeError, match="Snapshot restore failed"):
        restore_snapshot(tmp_path / "qmp.sock", "baseline")
    assert commands == ["human-monitor-command"]


def test_initialization_errors_are_not_scored_as_model_failures():
    result = {"status": "ERROR", "initializer": {"status": "ERROR"}, "evaluation": None}
    assert classify_result(result) == "INITIALIZATION_ERROR"


def test_missing_evaluation_is_not_scored_as_model_success():
    result = {"status": "PASS", "initializer": {"status": "PASS"}, "evaluation": {"status": "ERROR"}}
    assert classify_result(result) == "EVALUATION_ERROR"


def test_missing_evaluator_command_is_not_a_model_failure():
    result = {"status": "FAIL", "initializer": {"status": "PASS"},
              "evaluation": {"status": "FAIL", "metadata": {"returncode": 127}}}
    assert classify_result(result) == "EVALUATION_ERROR"


class _OpenShopController:
    def __init__(self, *, entrypoint_exists=True):
        self.entrypoint_exists = entrypoint_exists
        self.scripts = []
        self.uploads = []

    def run_bash_script(self, script, timeout=30):
        self.scripts.append((script, timeout))
        return {
            "returncode": 0 if self.entrypoint_exists else 1,
            "output": "" if self.entrypoint_exists else "missing entrypoint",
        }

    def upload_file(self, local_path, remote_path):
        self.uploads.append(remote_path)
        return {"status": "success"}


def test_openshop_verify_only_checks_snapshot_entrypoint_without_executable_lookup():
    controller = _OpenShopController()
    result = OpenShopInitializer().initialize(
        {
            "controller": controller,
            "params": {
                "app_command": "openshop",
                "verify_only": True,
                "local_webpage_path": "/home/user/Desktop/webpage/OpenShop",
            },
        }
    )

    assert result.status is InitStatus.PASS
    assert result.metadata["verify_only"] is True
    assert controller.scripts == [
        ("test -e /home/user/Desktop/webpage/OpenShop", 10),
    ]


def test_openshop_verify_only_reports_the_missing_entrypoint_cause():
    controller = _OpenShopController(entrypoint_exists=False)
    result = OpenShopInitializer().initialize(
        {
            "controller": controller,
            "params": {
                "verify_only": True,
                "local_webpage_path": "/home/user/Desktop/webpage/OpenShop",
            },
        }
    )

    assert result.status is InitStatus.ERROR
    assert result.message == "Failed to prepare OpenShop app state: missing entrypoint"
    assert result.metadata["app_command"] == "openshop"


def test_openshop_current_source_does_not_require_a_guest_executable(monkeypatch):
    initializer = OpenShopInitializer()
    calls = []
    monkeypatch.setattr(
        initializer,
        "_resolve_app_command",
        lambda *_: pytest.fail("current-source setup must not resolve a guest executable"),
    )
    monkeypatch.setattr(initializer, "_stop_app", lambda *_: calls.append("stop"))
    monkeypatch.setattr(initializer, "_cleanup_paths", lambda *_: calls.append("cleanup"))
    monkeypatch.setattr(initializer, "_deploy_and_launch_current_app", lambda *_, **__: calls.append("deploy"))
    monkeypatch.setattr(initializer, "_seed_state", lambda *_, **__: calls.append("seed"))
    monkeypatch.setattr(initializer, "_write_seed_files", lambda *_: calls.append("write"))

    result = initializer.initialize(
        {
            "controller": _OpenShopController(),
            "params": {
                "app_command": "openshop",
                "require_benchmark_api": True,
                "final_wait_ms": 0,
            },
        }
    )

    assert result.status is InitStatus.PASS
    assert result.metadata["app_command"] == "openshop-current-source"
    assert calls == ["cleanup", "deploy", "seed", "write"]


def test_openshop_current_source_reuses_snapshot_assets_when_host_apps_are_absent(monkeypatch):
    controller = _OpenShopController()
    initializer = OpenShopInitializer()
    monkeypatch.setattr(Path, "is_dir", lambda _: False)

    initializer._deploy_and_launch_current_app(controller, port=4310)

    assert controller.uploads == [initializer.MODERN_GUEST_SERVER]
    # The deploy script runs first; the browser is opened by a separate script.
    script = next(item[0] for item in controller.scripts if "seed-data.js" in item[0])
    assert initializer.SNAPSHOT_GUEST_PUBLIC_DIR in script
    assert "seed-data.js" in script
    assert "tar -xzf" not in script


def test_headless_bash_includes_guest_user_tools(monkeypatch):
    from platforms.linux.runtime_env.controller import LinuxRuntimeController
    monkeypatch.setattr(LinuxRuntimeController, "_refresh_device_info", lambda self: None)
    controller = LinuxRuntimeController()
    captured = {}

    def request(method, path, payload, **kwargs):
        captured.update(payload)
        return {"status": "success"}

    monkeypatch.setattr(controller, "_request_json", request)
    controller.run_bash_script("node --version", timeout=30)
    assert captured["script"] == 'export PATH="$HOME/.local/bin:$PATH"\nnode --version'
    controller.run_bash_script("#!/bin/bash\nnode --version", timeout=30)
    assert captured["script"] == '#!/bin/bash\nexport PATH="$HOME/.local/bin:$PATH"\nnode --version'


def test_code_prompt_uses_current_screen_coordinate_bounds():
    builder = LinuxPromptBuilder(observation_mode="screenshot_only", tool_calling=False)
    prompt = builder.build_step_prompt(observation=SimpleNamespace(width=1920, height=1080))
    assert "1920×1080 pixels" in prompt
    assert "x ranges from 0 to 1919, y from 0 to 1079" in prompt
    resized = builder.build_step_prompt(observation=SimpleNamespace(width=1280, height=800))
    assert "x ranges from 0 to 1279, y from 0 to 799" in resized


def test_run_log_appends_one_record_per_run(tmp_path):
    from scripts.run_linux_qemu_batch import append_run_log

    path = tmp_path / "logs" / "runs.jsonl"
    rows = [{"task_id": "a", "status": "PASS", "classification": "PASS"},
            {"task_id": "b", "status": "FAIL", "classification": "FAIL"}]
    for _ in range(2):
        append_run_log(path, {"model": "m", "started_at": "t"}, rows, tmp_path / "out", tmp_path / "out/summary.json")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["score"] == "1/2" and records[0]["platform"] == "linux" and records[0]["task_ids"] == ["a", "b"]
    assert records[0]["counts"] == {"PASS": 1, "FAIL": 1}


def test_windows_end_state_skips_appdata_and_copies_open_files():
    from scripts.run_linux_qemu_batch import WINDOWS_END_STATE_SCRIPT

    # PowerShell receives a valid regex for the literal \AppData\ path segment.
    assert r"-notmatch '\\AppData\\'" in WINDOWS_END_STATE_SCRIPT
    # Open documents are copied with read/write sharing, then zipped from the staging folder.
    assert "'Read', 'ReadWrite'" in WINDOWS_END_STATE_SCRIPT and "CreateFromDirectory" in WINDOWS_END_STATE_SCRIPT
    assert "Compress-Archive -LiteralPath" not in WINDOWS_END_STATE_SCRIPT
