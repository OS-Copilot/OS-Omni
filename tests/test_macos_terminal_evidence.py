"""Focused pure-mocked tests for macOS benchmark terminal/final-state evidence.

Covers the opt-in ``OS_OMNI_CAPTURE_MACOS_FINAL_STATE=1`` archive in
``platforms/macos/host/runners/benchmark.py``: task-bound path resolution,
credential/cache exclusion, malicious-path rejection without guest calls,
argv-form (shell-free) guest access, per-file/total/count limits, SHA256 and
missing-state reporting, token hygiene, capture-before-cleanup ordering that
also preserves failed/crashed child terminal output, and verdict
preservation. All guest layers are faked in-process; no VM, GUI, network,
model, or credential use.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from platforms.macos.host.runners import benchmark as macos_benchmark


def test_macos_final_state_stat_probe_is_valid_python_and_reports_file_state(tmp_path, monkeypatch):
    probe = compile(macos_benchmark._MACOS_FINAL_STATE_STAT_CODE, "<final-state-stat>", "exec")
    target = tmp_path / "task output.txt"
    target.write_text("evidence", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["stat-probe", str(target)])
    # The probe prints one JSON object, which the host collector consumes.
    import contextlib
    import io
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(probe, {})
    observed = json.loads(output.getvalue())
    assert observed == {
        "exists": True,
        "is_file": True,
        "is_symlink": False,
        "size": len("evidence"),
    }


TEXTEDIT_TASK_YAML = """\
task_id: macos.textedit.append_ops_note
platform: macos
instruction: "Append a line."
init:
  initializer_id: initializers.macos.setup:DesktopSetupInitializer
  params:
    open_file: /Users/bench/Downloads/ops_note.txt
evaluation:
  evaluator_id: evaluators.macos.textedit:TextEditEvaluator
  params:
    actual_path: /Users/bench/Downloads/ops_note.txt
    secret_path: /Users/bench/Downloads/token_backup.txt
    env_path: /Users/bench/Downloads/.env
limits:
  max_steps: 5
"""

DRAWIO_TASK_YAML = """\
task_id: macos.drawio.launch_matrix_sync
platform: macos
instruction: "Relabel."
init:
  initializer_id: x
  params:
    open_file: /Users/bench/Downloads/launch_matrix_sync.drawio
evaluation:
  evaluator_id: evaluators.macos.drawio:DrawIODiagramEvaluator
  params:
    actual_path: /Users/bench/Downloads/launch_matrix_sync.drawio
limits:
  max_steps: 5
"""

MALICIOUS_TASK_YAML = """\
task_id: macos.drawio.launch_matrix_sync
platform: macos
instruction: "Relabel."
init:
  initializer_id: x
  params:
    open_file: /Users/bench
evaluation:
  evaluator_id: evaluators.macos.drawio:DrawIODiagramEvaluator
  params:
    actual_path: /etc/passwd
    traversal_path: /Users/bench/Downloads/../../etc/passwd
    keychain_path: ~/Library/Keychains/login.keychain-db
    cache_path: /Users/bench/Downloads/Caches/blob.bin
    home_path: /Users/bench/.ssh/id_rsa
limits:
  max_steps: 5
"""

PHOTOS_TASK_YAML = """\
task_id: macos.photos.favorite_receipts_hard
platform: macos
instruction: "Favorite receipts."
init:
  initializer_id: x
  params:
    mode: open
evaluation:
  evaluator_id: evaluators.macos.photos:PhotosStateEvaluator
  params: {}
limits:
  max_steps: 5
metadata:
  app_bundle_id: com.apple.Photos
"""

THUNDERBIRD_TASK_YAML = """\
task_id: macos.thunderbird.calendar.create_event
platform: macos
instruction: "Create an event."
init:
  initializer_id: x
  params:
    open_calendar: true
evaluation:
  evaluator_id: evaluators.macos.thunderbird_calendar:ThunderbirdCalendarEvaluator
  params: {}
limits:
  max_steps: 5
"""

PHOTOS_DB = "/Users/bench/Pictures/Photos Library.photoslibrary/database/Photos.sqlite"
TB_DB = "/Users/bench/Library/Thunderbird/Profiles/abc123.default/calendar-data/local.sqlite"


def _write_task(tmp_path: Path, text: str, name: str = "task.yaml") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class FakeController:
    """In-process stand-in for VMRuntimeController's guest-access surface."""

    def __init__(
        self,
        *,
        files: Optional[Dict[str, bytes]] = None,
        symlinks: tuple[str, ...] = (),
        dirs: tuple[str, ...] = (),
        health: Any = None,
        version: Any = None,
        device_info: Any = None,
        screenshot: bytes = b"fake-jpg-bytes",
        discovery_dbs: Optional[List[str]] = None,
        health_error: Optional[Exception] = None,
    ) -> None:
        self.files = dict(files or {})
        self.symlinks = set(symlinks)
        self.dirs = set(dirs)
        self._health = {"status": "HEALTHY"} if health is None else health
        self._version = {"name": "macui-runtime", "api": 2} if version is None else version
        self._device_info = {"screen_width": 1920} if device_info is None else device_info
        self._screenshot = screenshot
        self._discovery_dbs = list(discovery_dbs or [])
        self._health_error = health_error
        self.calls: List[tuple[str, Any]] = []

    def health(self) -> Dict[str, Any]:
        self.calls.append(("health", None))
        if self._health_error is not None:
            raise self._health_error
        return dict(self._health)

    def _request_json(
        self, method: str, path: str, payload: Any = None, *, timeout: Any = None
    ) -> Dict[str, Any]:
        self.calls.append(("_request_json", f"{method} {path}"))
        assert path == "/version", f"unexpected guest path: {path}"
        return dict(self._version)

    def get_device_info(self) -> Dict[str, Any]:
        self.calls.append(("get_device_info", None))
        return dict(self._device_info)

    def _request_binary(self, method: str, path: str) -> bytes:
        self.calls.append(("_request_binary", f"{method} {path}"))
        assert path == "/screenshot", f"unexpected guest path: {path}"
        return bytes(self._screenshot)

    def execute_command(
        self, command: Any, *, shell: bool = False, timeout: int = 30
    ) -> Dict[str, Any]:
        assert shell is False, "guest commands must use argv form, never shell"
        assert isinstance(command, list), "guest commands must be argv lists"
        self.calls.append(("execute_command", list(command)))
        assert command[2] == macos_benchmark._MACOS_FINAL_STATE_STAT_CODE
        guest_path = command[-1]
        assert guest_path not in command[2], "untrusted path interpolated into probe code"
        if guest_path in self.symlinks:
            probe = {"exists": True, "is_file": False, "is_symlink": True, "size": 0}
        elif guest_path in self.files:
            probe = {
                "exists": True,
                "is_file": True,
                "is_symlink": False,
                "size": len(self.files[guest_path]),
            }
        elif guest_path in self.dirs:
            probe = {"exists": True, "is_file": False, "is_symlink": False, "size": 0}
        else:
            probe = {"exists": False}
        return {"status": "success", "output": json.dumps(probe), "error": "", "returncode": 0}

    def run_python_script(
        self, code: str, *, timeout: int = 30, working_dir: Any = None
    ) -> Dict[str, Any]:
        self.calls.append(("run_python_script", "discovery"))
        assert code == macos_benchmark._MACOS_FINAL_STATE_THUNDERBIRD_DISCOVERY_CODE
        return {
            "status": "success",
            "output": json.dumps({"dbs": self._discovery_dbs}),
            "error": "",
            "returncode": 0,
        }

    def get_file(self, file_path: str) -> bytes:
        self.calls.append(("get_file", file_path))
        if file_path in self.files:
            return bytes(self.files[file_path])
        raise RuntimeError(f"HTTP 404 POST /file: file not found: {file_path}")

    def guest_paths_touched(self) -> List[str]:
        touched: List[str] = []
        for kind, arg in self.calls:
            if kind == "get_file":
                touched.append(str(arg))
            elif kind == "execute_command":
                touched.append(str(arg[-1]))
        return touched


def _capture_kwargs(
    tmp_path: Path, task_text: str = TEXTEDIT_TASK_YAML, **overrides: Any
) -> Dict[str, Any]:
    out_dir = tmp_path / "run"
    out_dir.mkdir(exist_ok=True)
    kwargs: Dict[str, Any] = {
        "runtime_url": "http://10.0.0.5:5000",
        "token": "unit-test-token",
        "task_id": "macos.textedit.append_ops_note",
        "task_file": _write_task(tmp_path, task_text),
        "model_output_dir": out_dir,
        "run_index": 1,
    }
    kwargs.update(overrides)
    return kwargs


# --- disabled default --------------------------------------------------------


def test_capture_disabled_by_default_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, raising=False)
    fake = FakeController(files={"/Users/bench/Downloads/ops_note.txt": b"hi"})

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("guest layer must not be called while disabled")

    monkeypatch.setattr(fake, "health", _forbidden)
    monkeypatch.setattr(fake, "get_file", _forbidden)
    runner = macos_benchmark.MacOSBenchmarkRunner()
    assert (
        runner._maybe_capture_macos_final_state(
            runtime_url="http://10.0.0.5:5000",
            token="unit-test-token",
            task_id="macos.textedit.append_ops_note",
            task_file=_write_task(tmp_path, TEXTEDIT_TASK_YAML),
            model_output_dir=tmp_path / "run",
            run_index=1,
            controller=fake,
        )
        is None
    )
    assert not (tmp_path / "run" / macos_benchmark.MACOS_FINAL_STATE_DIRNAME).exists()


def test_capture_without_runtime_url_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    fake = FakeController()
    runner = macos_benchmark.MacOSBenchmarkRunner()
    assert (
        runner._maybe_capture_macos_final_state(
            runtime_url="",
            token="unit-test-token",
            task_id="macos.textedit.append_ops_note",
            task_file=_write_task(tmp_path, TEXTEDIT_TASK_YAML),
            model_output_dir=tmp_path / "run",
            run_index=1,
            controller=fake,
        )
        is None
    )
    assert fake.calls == []


# --- happy path: hashes, archive, tagging -------------------------------------


def test_capture_archives_task_file_with_hashes_and_admin_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    note = b"ops note contents"
    fake = FakeController(files={"/Users/bench/Downloads/ops_note.txt": note})
    kwargs = _capture_kwargs(tmp_path)
    manifest = macos_benchmark.capture_macos_final_state(
        **kwargs, controller=fake, model="mock-model", success=False, return_code=1
    )

    assert manifest["evidence_kind"] == "administrative-final-state"
    assert manifest["for_decision_system"] is False
    assert manifest["child_success"] is False
    assert manifest["child_return_code"] == 1
    assert manifest["health"] == {"status": "HEALTHY"}
    assert manifest["version"] == {"name": "macui-runtime", "api": 2}
    assert "unit-test-token" not in json.dumps(manifest)

    out_dir = Path(kwargs["model_output_dir"])
    final_dir = out_dir / macos_benchmark.MACOS_FINAL_STATE_DIRNAME
    archive = final_dir / macos_benchmark.MACOS_FINAL_STATE_ARCHIVE_NAME
    assert archive.is_file()
    with tarfile.open(archive, "r:gz") as tar:
        members = sorted(tar.getnames())
    assert "task_files/HOME/Downloads/ops_note.txt" in members
    assert manifest["archive_members"] == members
    assert manifest["archive_sha256"] == _sha256_bytes(archive.read_bytes())

    by_path = {entry["path"]: entry for entry in manifest["files"]}
    note_entry = by_path["task_files/HOME/Downloads/ops_note.txt"]
    assert note_entry["sha256"] == _sha256_bytes(note)
    assert note_entry["size"] == len(note)

    assert (final_dir / macos_benchmark.MACOS_FINAL_STATE_SCREENSHOT_NAME).is_file()
    assert manifest["screenshot"]["sha256"] == _sha256_bytes(b"fake-jpg-bytes")

    # Credential-looking task params never enter the archive.
    assert not any("token_backup" in name for name in members)
    assert not any(name.endswith(".env") for name in members)
    assert any(
        entry["path"] == "/Users/bench/Downloads/token_backup.txt"
        and entry["reason"] == "credential-name-excluded"
        for entry in manifest["skipped"]
    )
    assert any(
        entry["path"] == "/Users/bench/Downloads/.env"
        and entry["reason"] == "credential-name-excluded"
        for entry in manifest["skipped"]
    )
    assert manifest["errors"] == []

    on_disk = json.loads(
        (final_dir / macos_benchmark.MACOS_FINAL_STATE_MANIFEST_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert on_disk == manifest


def test_token_never_logged_or_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    fake = FakeController(files={"/Users/bench/Downloads/ops_note.txt": b"hi"})
    out_dir = tmp_path / "run"
    out_dir.mkdir(exist_ok=True)
    runner_log = tmp_path / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    runner = macos_benchmark.MacOSBenchmarkRunner()
    manifest = runner._maybe_capture_macos_final_state(
        runtime_url="http://10.0.0.5:5000",
        token="SECRET-TOKEN-xyz-123",
        task_id="macos.textedit.append_ops_note",
        task_file=_write_task(tmp_path, TEXTEDIT_TASK_YAML),
        model_output_dir=out_dir,
        run_index=1,
        controller=fake,
        runner_log_path=runner_log,
    )
    assert manifest is not None
    assert "SECRET-TOKEN-xyz-123" not in json.dumps(manifest)
    assert "SECRET-TOKEN-xyz-123" not in runner_log.read_text(encoding="utf-8")


# --- malicious paths: rejected before any guest call --------------------------


def test_malicious_paths_rejected_without_guest_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    fake = FakeController()
    kwargs = _capture_kwargs(tmp_path, MALICIOUS_TASK_YAML)
    manifest = macos_benchmark.capture_macos_final_state(**kwargs, controller=fake)

    assert manifest["files"] == []
    reasons = {entry["path"]: entry["reason"] for entry in manifest["skipped"]}
    assert reasons["/etc/passwd"] == "path-not-allowed"
    assert reasons["/Users/etc/passwd"] == "path-not-allowed"
    assert reasons["/Users/bench"] == "path-not-allowed"
    assert reasons["/Users/bench/Library/Keychains/login.keychain-db"] == (
        "credential-name-excluded"
    )
    assert reasons["/Users/bench/Downloads/Caches/blob.bin"] == "cache-or-system-excluded"
    assert reasons["/Users/bench/.ssh/id_rsa"] == "credential-name-excluded"
    # Nothing disallowed ever reached the guest: only health/version/device/
    # screenshot calls are allowed, never stat/download of rejected paths.
    assert fake.guest_paths_touched() == []


def test_special_chars_travel_as_argv_not_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    nasty = "/Users/bench/Downloads/weird;rm -rf ~ $(id).txt"
    task = TEXTEDIT_TASK_YAML.replace(
        "/Users/bench/Downloads/ops_note.txt", nasty
    ).replace("macos.textedit.append_ops_note", "macos.textedit.nasty")
    fake = FakeController(files={nasty: b"nasty-contents"})
    kwargs = _capture_kwargs(tmp_path, task, task_id="macos.textedit.nasty")
    manifest = macos_benchmark.capture_macos_final_state(**kwargs, controller=fake)
    assert len(manifest["files"]) == 1
    stat_calls = [arg for kind, arg in fake.calls if kind == "execute_command"]
    assert stat_calls, "stat probe must run over argv"
    for argv in stat_calls:
        assert argv[0] == "/usr/bin/python3"
        assert argv[-1] == nasty


def test_symlink_excluded_before_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    link = "/Users/bench/Downloads/ops_note.txt"
    fake = FakeController(symlinks=(link,))
    kwargs = _capture_kwargs(tmp_path)
    manifest = macos_benchmark.capture_macos_final_state(**kwargs, controller=fake)
    assert manifest["files"] == []
    assert any(
        entry["reason"] == "symlink-excluded" for entry in manifest["skipped"]
    )
    assert [arg for kind, arg in fake.calls if kind == "get_file"] == []


# --- limits --------------------------------------------------------------------


def test_oversized_files_are_skipped_not_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    monkeypatch.setattr(macos_benchmark, "MACOS_FINAL_STATE_MAX_FILE_BYTES", 4)
    fake = FakeController(
        files={
            "/Users/bench/Downloads/launch_matrix_sync.drawio": b"0123456789",
            "/Users/bench/Downloads/ops_note.txt": b"ok",
        }
    )
    task = DRAWIO_TASK_YAML.replace(
        "actual_path: /Users/bench/Downloads/launch_matrix_sync.drawio",
        "actual_path: /Users/bench/Downloads/launch_matrix_sync.drawio\n"
        "    extra_path: /Users/bench/Downloads/ops_note.txt",
    )
    kwargs = _capture_kwargs(tmp_path, task, task_id="macos.drawio.launch_matrix_sync")
    manifest = macos_benchmark.capture_macos_final_state(**kwargs, controller=fake)
    assert "task_files/HOME/Downloads/ops_note.txt" in manifest["archive_members"]
    assert not any("launch_matrix_sync" in name for name in manifest["archive_members"])
    assert any(
        entry["reason"] == "file-size-exceeded" for entry in manifest["skipped"]
    )


def test_file_count_budget_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    monkeypatch.setattr(macos_benchmark, "MACOS_FINAL_STATE_MAX_FILES", 1)
    fake = FakeController(
        files={
            "/Users/bench/Downloads/launch_matrix_sync.drawio": b"a",
            "/Users/bench/Downloads/ops_note.txt": b"b",
        }
    )
    task = DRAWIO_TASK_YAML.replace(
        "actual_path: /Users/bench/Downloads/launch_matrix_sync.drawio",
        "actual_path: /Users/bench/Downloads/launch_matrix_sync.drawio\n"
        "    extra_path: /Users/bench/Downloads/ops_note.txt",
    )
    kwargs = _capture_kwargs(tmp_path, task, task_id="macos.drawio.launch_matrix_sync")
    manifest = macos_benchmark.capture_macos_final_state(**kwargs, controller=fake)
    assert len(manifest["files"]) == 1
    assert any(
        entry["reason"] == "file-count-exceeded" for entry in manifest["skipped"]
    )


# --- native stores: task-bound only, WAL/SHM preserved, missing reported -------


def test_photos_db_captured_with_wal_and_missing_shm_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    fake = FakeController(
        files={PHOTOS_DB: b"photos-db", PHOTOS_DB + "-wal": b"photos-wal"}
    )
    kwargs = _capture_kwargs(
        tmp_path, PHOTOS_TASK_YAML, task_id="macos.photos.favorite_receipts_hard"
    )
    manifest = macos_benchmark.capture_macos_final_state(**kwargs, controller=fake)
    assert "native/photos/Photos.sqlite" in manifest["archive_members"]
    assert "native/photos/Photos.sqlite-wal" in manifest["archive_members"]
    assert any(
        entry["path"] == "native/photos/Photos.sqlite-shm"
        and entry["reason"] == "missing"
        for entry in manifest["skipped"]
    )
    # Originals are never collected: no Masters/DCIM-style members.
    assert not any("Masters" in name or "DCIM" in name for name in manifest["archive_members"])
    assert manifest["errors"] == []


def test_unrelated_task_collects_no_native_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    fake = FakeController(files={"/Users/bench/Downloads/ops_note.txt": b"hi"})
    kwargs = _capture_kwargs(tmp_path)
    manifest = macos_benchmark.capture_macos_final_state(**kwargs, controller=fake)
    assert not any(name.startswith("native/") for name in manifest["archive_members"])


def test_thunderbird_calendar_discovery_is_static_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    fake = FakeController(
        files={TB_DB: b"cal-db", TB_DB + "-wal": b"cal-wal"},
        discovery_dbs=[TB_DB, "/etc/passwd"],
    )
    kwargs = _capture_kwargs(
        tmp_path, THUNDERBIRD_TASK_YAML, task_id="macos.thunderbird.calendar.create_event"
    )
    manifest = macos_benchmark.capture_macos_final_state(**kwargs, controller=fake)
    assert "native/thunderbird_calendar/local.sqlite" in manifest["archive_members"]
    assert "native/thunderbird_calendar/local.sqlite-wal" in manifest["archive_members"]
    assert not any("etc/passwd" in name for name in manifest["archive_members"])
    assert manifest["errors"] == []


# --- errors recorded, verdict untouched -----------------------------------------


def test_guest_failures_recorded_without_changing_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    fake = FakeController(
        files={"/Users/bench/Downloads/ops_note.txt": b"hi"},
        health_error=RuntimeError("guest down"),
        screenshot=b"",
    )
    kwargs = _capture_kwargs(tmp_path)
    manifest = macos_benchmark.capture_macos_final_state(
        **kwargs, controller=fake, success=True, return_code=0
    )
    assert any("health" in err for err in manifest["errors"])
    assert any("screenshot" in err for err in manifest["errors"])
    assert manifest["child_success"] is True
    assert manifest["child_return_code"] == 0
    assert "task_files/HOME/Downloads/ops_note.txt" in manifest["archive_members"]
    assert (
        Path(kwargs["model_output_dir"])
        / macos_benchmark.MACOS_FINAL_STATE_DIRNAME
        / macos_benchmark.MACOS_FINAL_STATE_MANIFEST_NAME
    ).is_file()


def test_maybe_capture_wraps_unexpected_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    monkeypatch.setattr(
        macos_benchmark,
        "capture_macos_final_state",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("capture exploded")),
    )
    runner = macos_benchmark.MacOSBenchmarkRunner()
    manifest = runner._maybe_capture_macos_final_state(
        runtime_url="http://10.0.0.5:5000",
        token="t",
        task_id="macos.textedit.append_ops_note",
        task_file=_write_task(tmp_path, TEXTEDIT_TASK_YAML),
        model_output_dir=tmp_path / "run",
        run_index=1,
    )
    assert manifest is not None
    assert manifest["for_decision_system"] is False
    assert any("capture exploded" in err for err in manifest["errors"])


# --- ordering: before cleanup, crash path, failed-child evidence -----------------


def _make_args(**overrides: Any) -> SimpleNamespace:
    base: Dict[str, Any] = {
        "models": "mock-model",
        "action_mode": "code_adapter",
        "observation_mode": "screenshot_and_a11y_tree",
        "prompt_profile": "benchmark",
        "history_window": 5,
        "vm_ip": "10.0.0.9",
        "runtime_port": 5000,
        "vm_token": "unit-test-token",
        "base_vm_name": "base-vm",
        "execution_file": None,
        "max_steps": None,
        "timeout": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_job(task_file: str, **overrides: Any) -> Dict[str, Any]:
    job: Dict[str, Any] = {
        "run_index": 1,
        "model": "mock-model",
        "task_id": "macos.textedit.append_ops_note",
        "task_file": task_file,
        "base_vm_name": "base-vm",
    }
    job.update(overrides)
    return job


def _drive_single_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    child_returncode: int = 1,
    child_raises: bool = False,
    capture_side_effect: Any = None,
) -> Dict[str, Any]:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    task_file = _write_task(tmp_path, TEXTEDIT_TASK_YAML)
    run_root = tmp_path / "bench"
    run_root.mkdir(exist_ok=True)
    runner_log = run_root / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    calls: List[str] = []

    runner = macos_benchmark.MacOSBenchmarkRunner()
    runner._manager = object()
    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner,
        "_prepare_vm_for_run",
        staticmethod(
            lambda args, context, manager: (
                True,
                None,
                "clone-0001",
                "10.0.0.5",
                "http://10.0.0.5:5000",
            )
        ),
    )

    def _fake_child(self: Any, cmd: Any, log_path: Any, **kwargs: Any) -> int:
        child_line = "CHILD-TERMINAL-LINE child ran to completion\n"
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with Path(log_path).open("a", encoding="utf-8") as handle:
            handle.write(child_line)
        if child_raises:
            raise RuntimeError("child blew up")
        return child_returncode

    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner, "run_command_streaming", _fake_child
    )

    def _capture_spy(self: Any, **kwargs: Any) -> Any:
        calls.append("capture")
        if capture_side_effect == "boom":
            raise RuntimeError("capture exploded")
        if capture_side_effect is not None:
            return capture_side_effect
        return {"archive": None, "errors": []}

    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner, "_maybe_capture_macos_final_state", _capture_spy
    )

    def _fake_cleanup(manager: Any, clone_name: str) -> Any:
        calls.append("cleanup")
        assert clone_name == "clone-0001"
        return True, None

    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner,
        "_cleanup_ephemeral_vm",
        staticmethod(_fake_cleanup),
    )

    out: Dict[str, Any] = {"calls": calls, "runner_log": runner_log}
    out["result"] = runner._execute_single_run(
        args=_make_args(),
        job=_make_job(task_file),
        cli_entry_path="/nonexistent/cli.py",
        run_root=run_root,
        runner_log_path=runner_log,
    )
    return out


def test_capture_runs_before_cleanup_and_failed_child_evidence_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = macos_benchmark.MacOSBenchmarkRunner()
    calls: List[str] = []
    task_file = _write_task(tmp_path, TEXTEDIT_TASK_YAML)
    run_root = tmp_path / "bench"
    run_root.mkdir(exist_ok=True)
    runner_log = run_root / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    runner._manager = object()
    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner,
        "_prepare_vm_for_run",
        staticmethod(
            lambda args, context, manager: (
                True,
                None,
                "clone-0001",
                "10.0.0.5",
                "http://10.0.0.5:5000",
            )
        ),
    )

    def _failing_child(self: Any, cmd: Any, log_path: Any, **kwargs: Any) -> int:
        with Path(log_path).open("a", encoding="utf-8") as handle:
            handle.write("CHILD-TERMINAL-LINE agent failed at step 3\n")
        return 1

    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner, "run_command_streaming", _failing_child
    )

    def _recording_capture(self: Any, **kwargs: Any) -> Any:
        calls.append("capture")
        assert kwargs["success"] is False
        assert kwargs["return_code"] == 1
        assert kwargs["runtime_url"] == "http://10.0.0.5:5000"
        assert "vm_token" not in json.dumps(kwargs, default=str)
        return {"archive": macos_benchmark.MACOS_FINAL_STATE_ARCHIVE_NAME, "errors": []}

    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner,
        "_maybe_capture_macos_final_state",
        _recording_capture,
    )

    def _recording_cleanup(manager: Any, clone_name: str) -> Any:
        calls.append("cleanup")
        assert clone_name == "clone-0001"
        return True, None

    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner,
        "_cleanup_ephemeral_vm",
        staticmethod(_recording_cleanup),
    )

    record = runner._execute_single_run(
        args=_make_args(),
        job=_make_job(task_file),
        cli_entry_path="/nonexistent/cli.py",
        run_root=run_root,
        runner_log_path=runner_log,
    )

    assert calls == ["capture", "cleanup"]
    assert record["success"] is False
    assert record["return_code"] == 1
    assert record["final_state"] == {
        "archive": macos_benchmark.MACOS_FINAL_STATE_ARCHIVE_NAME,
        "errors": [],
    }
    log_text = runner_log.read_text(encoding="utf-8")
    assert "CHILD-TERMINAL-LINE agent failed at step 3" in log_text
    assert "status=FAILED" in log_text


def test_failed_child_with_capture_error_stays_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _drive_single_run(
        tmp_path, monkeypatch, child_returncode=1, capture_side_effect="boom"
    )
    assert out["calls"] == ["capture", "cleanup"]
    assert out["result"]["success"] is False
    assert out["result"]["return_code"] == 1
    log_text = out["runner_log"].read_text(encoding="utf-8")
    assert "CHILD-TERMINAL-LINE child ran to completion" in log_text
    assert "status=FAILED" in log_text


def test_passing_child_with_capture_error_stays_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _drive_single_run(
        tmp_path, monkeypatch, child_returncode=0, capture_side_effect="boom"
    )
    assert out["result"]["success"] is True
    assert out["result"]["return_code"] == 0


def test_child_exception_still_captures_before_cleanup_and_keeps_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(macos_benchmark.OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "1")
    task_file = _write_task(tmp_path, TEXTEDIT_TASK_YAML)
    run_root = tmp_path / "bench"
    run_root.mkdir(exist_ok=True)
    runner_log = run_root / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    calls: List[str] = []
    runner = macos_benchmark.MacOSBenchmarkRunner()
    runner._manager = object()
    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner,
        "_prepare_vm_for_run",
        staticmethod(
            lambda args, context, manager: (
                True,
                None,
                "clone-0001",
                "10.0.0.5",
                "http://10.0.0.5:5000",
            )
        ),
    )

    def _exploding_child(self: Any, cmd: Any, log_path: Any, **kwargs: Any) -> int:
        with Path(log_path).open("a", encoding="utf-8") as handle:
            handle.write("CHILD-TERMINAL-LINE partial output before crash\n")
        raise RuntimeError("child blew up")

    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner, "run_command_streaming", _exploding_child
    )

    def _recording_capture(self: Any, **kwargs: Any) -> Any:
        calls.append("capture")
        assert kwargs["success"] is None
        assert kwargs["return_code"] is None
        return {"archive": None, "errors": []}

    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner,
        "_maybe_capture_macos_final_state",
        _recording_capture,
    )

    def _recording_cleanup(manager: Any, clone_name: str) -> Any:
        calls.append("cleanup")
        return True, None

    monkeypatch.setattr(
        macos_benchmark.MacOSBenchmarkRunner,
        "_cleanup_ephemeral_vm",
        staticmethod(_recording_cleanup),
    )

    with pytest.raises(RuntimeError, match="child blew up"):
        runner._execute_single_run(
            args=_make_args(),
            job=_make_job(task_file),
            cli_entry_path="/nonexistent/cli.py",
            run_root=run_root,
            runner_log_path=runner_log,
        )
    assert calls == ["capture", "cleanup"]
    assert "CHILD-TERMINAL-LINE partial output before crash" in runner_log.read_text(
        encoding="utf-8"
    )
