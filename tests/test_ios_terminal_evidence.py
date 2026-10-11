"""Focused pure-mocked tests for iOS benchmark terminal/final-state evidence.

Covers the opt-in ``OS_OMNI_CAPTURE_IOS_FINAL_STATE=1`` archive in
``platforms/ios/runners/benchmark.py``: bundle-ID resolution priority,
archive path selection (app container + relevant native SQLite, Photos
metadata only), error recording without touching PASS/FAIL or prior
evidence, and capture-before-cleanup ordering that also preserves failed
child terminal output. All simctl/filesystem layers are mocked or rooted
at ``tmp_path``; no simulator, model, GUI, or network use.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from platforms.ios.runners import benchmark as ios_benchmark
from platforms.ios.runtime_env import simulator_manager


CONTACTS_TASK_YAML = """\
task_id: ios.contacts.add_contact_card
platform: ios
instruction: "Create a contact."
init:
  initializer_id: initializers.ios.contacts_seed_open_app:ContactsSeedOpenAppInitializer
  params:
    bundle_id: com.apple.MobileAddressBook
evaluation:
  evaluator_id: evaluators.ios.contacts_state:ContactsStateEvaluator
  params: {}
limits:
  max_steps: 5
metadata:
  app_bundle_id: com.apple.MobileAddressBook
"""

MISMATCH_TASK_YAML = """\
task_id: ios.contacts.mismatch
platform: ios
instruction: "Metadata wins over init params."
init:
  initializer_id: x
  params:
    bundle_id: com.apple.mobilecal
evaluation:
  evaluator_id: y
  params: {}
limits:
  max_steps: 5
metadata:
  app_bundle_id: com.apple.MobileAddressBook
"""

INIT_ONLY_TASK_YAML = """\
task_id: ios.maily.send_email
platform: ios
instruction: "Send an email."
init:
  initializer_id: x
  params:
    bundle_id: de.enough.maily
evaluation:
  evaluator_id: y
  params: {}
limits:
  max_steps: 5
metadata:
  app: Maily
"""


def _write_task(tmp_path: Path, text: str, name: str = "task.yaml") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _make_args(**overrides: Any) -> SimpleNamespace:
    base: Dict[str, Any] = {
        "models": "mock-model",
        "action_mode": "code_adapter",
        "observation_mode": "screenshot_and_a11y_tree",
        "history_window": 5,
        "appium_host": "127.0.0.1",
        "appium_port": 4723,
        "execution_file": None,
        "max_steps": None,
        "timeout": None,
        "clone_source_udid": "SOURCE-UDID",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_job(task_file: str, **overrides: Any) -> Dict[str, Any]:
    job: Dict[str, Any] = {
        "run_index": 1,
        "model": "mock-model",
        "task_id": "ios.contacts.add_contact_card",
        "task_file": task_file,
    }
    job.update(overrides)
    return job


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# --- bundle-ID resolution ---------------------------------------------------


def test_bundle_id_prefers_metadata_then_init_params(tmp_path: Path) -> None:
    assert (
        ios_benchmark.resolve_ios_task_bundle_id(
            _write_task(tmp_path, CONTACTS_TASK_YAML)
        )
        == "com.apple.MobileAddressBook"
    )
    # metadata.app_bundle_id wins over init.params.bundle_id.
    assert (
        ios_benchmark.resolve_ios_task_bundle_id(
            _write_task(tmp_path, MISMATCH_TASK_YAML, name="mismatch.yaml")
        )
        == "com.apple.MobileAddressBook"
    )
    # Falls back to init.params.bundle_id when metadata has none.
    assert (
        ios_benchmark.resolve_ios_task_bundle_id(
            _write_task(tmp_path, INIT_ONLY_TASK_YAML, name="init_only.yaml")
        )
        == "de.enough.maily"
    )
    assert (
        ios_benchmark.resolve_ios_task_bundle_id(str(tmp_path / "missing.yaml")) is None
    )


# --- capture disabled -------------------------------------------------------


def test_capture_disabled_by_default_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ios_benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, raising=False)

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("simctl layer must not be called while disabled")

    monkeypatch.setattr(simulator_manager, "get_app_data_container_path", _forbidden)
    monkeypatch.setattr(simulator_manager, "take_screenshot", _forbidden)

    runner = ios_benchmark.IOSBenchmarkRunner()
    assert (
        runner._maybe_capture_ios_final_state(
            udid="UDID-X",
            task_id="ios.contacts.add_contact_card",
            task_file=_write_task(tmp_path, CONTACTS_TASK_YAML),
            model_output_dir=tmp_path / "run",
            run_index=1,
        )
        is None
    )
    assert not (tmp_path / "run" / ios_benchmark.IOS_FINAL_STATE_DIRNAME).exists()


# --- archive paths ----------------------------------------------------------


def _seed_fake_device(
    device_data: Path,
    *,
    contacts: bool = True,
    calendar: bool = True,
    photos: bool = False,
) -> None:
    if contacts:
        addr = device_data / "Library" / "AddressBook"
        addr.mkdir(parents=True, exist_ok=True)
        (addr / "AddressBook.sqlitedb").write_bytes(b"contacts-db")
        (addr / "AddressBook.sqlitedb-wal").write_bytes(b"contacts-wal")
    if calendar:
        cal = device_data / "Library" / "Calendar"
        cal.mkdir(parents=True, exist_ok=True)
        (cal / "Calendar.sqlitedb").write_bytes(b"calendar-db")
    if photos:
        photo_data = device_data / "Media" / "PhotoData"
        photo_data.mkdir(parents=True, exist_ok=True)
        (photo_data / "Photos.sqlite").write_bytes(b"photos-metadata")
        dcim = device_data / "Media" / "DCIM" / "100APPLE"
        dcim.mkdir(parents=True, exist_ok=True)
        (dcim / "IMG_0001.JPG").write_bytes(b"raw-photo-bytes")


def _mock_sim_layer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    container: Path,
    screenshot_payload: bytes = b"fake-png",
) -> None:
    monkeypatch.setattr(
        simulator_manager,
        "get_app_data_container_path",
        lambda udid, bundle_id: str(container),
    )

    def _shot(udid: str, output_path: Path) -> None:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(screenshot_payload)

    monkeypatch.setattr(simulator_manager, "take_screenshot", _shot)


def test_capture_archives_app_container_and_relevant_native_dbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ios_benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "1")
    container = tmp_path / "container"
    (container / "Library" / "Application Support").mkdir(parents=True, exist_ok=True)
    (container / "Library" / "Application Support" / "store.sqlite").write_bytes(
        b"app-db"
    )
    (container / "Documents" / "note.txt").parent.mkdir(parents=True, exist_ok=True)
    (container / "Documents" / "note.txt").write_bytes(b"hello")
    # Credential-looking files must never enter the archive.
    (container / "Library" / "keychain-backup.db").write_bytes(b"nope")
    device_data = tmp_path / "device-data"
    _seed_fake_device(device_data)
    monkeypatch.setattr(ios_benchmark, "_ios_device_data_dir", lambda udid: device_data)
    _mock_sim_layer(monkeypatch, container=container)

    task_file = _write_task(tmp_path, CONTACTS_TASK_YAML)
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    manifest = ios_benchmark.capture_ios_final_state(
        udid="UDID-1",
        task_id="ios.contacts.add_contact_card",
        task_file=task_file,
        model_output_dir=out_dir,
        run_index=1,
        model="mock-model",
        success=False,
        return_code=1,
    )

    final_dir = out_dir / ios_benchmark.IOS_FINAL_STATE_DIRNAME
    archive = final_dir / ios_benchmark.IOS_FINAL_STATE_ARCHIVE_NAME
    assert archive.is_file()
    with tarfile.open(archive, "r:gz") as tar:
        members = sorted(tar.getnames())
    assert "app_container/Library/Application Support/store.sqlite" in members
    assert "app_container/Documents/note.txt" in members
    assert "native/Library/AddressBook/AddressBook.sqlitedb" in members
    assert "native/Library/AddressBook/AddressBook.sqlitedb-wal" in members
    # Gated by relevance: a Contacts task pulls neither Calendar nor Photos.
    assert not any("Calendar" in name for name in members)
    assert not any("PhotoData" in name for name in members)
    assert not any("keychain" in name for name in members)
    assert not any(name.startswith("Devices/") for name in members)

    written = json.loads(
        (final_dir / ios_benchmark.IOS_FINAL_STATE_MANIFEST_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert written["task_id"] == "ios.contacts.add_contact_card"
    assert written["task_file"] == task_file
    assert written["udid"] == "UDID-1"
    assert written["bundle_id"] == "com.apple.MobileAddressBook"
    assert written["child_success"] is False
    assert written["child_return_code"] == 1
    assert written["archive_sha256"] == _sha256_bytes(archive.read_bytes())
    assert set(written["archive_members"]) == set(members)
    by_path = {entry["path"]: entry for entry in written["files"]}
    assert by_path["app_container/Documents/note.txt"]["sha256"] == _sha256_bytes(
        b"hello"
    )
    assert any(
        entry["path"] == "app_container/Library/keychain-backup.db"
        and entry["reason"] == "credential-name-excluded"
        for entry in written["skipped"]
    )
    assert (final_dir / ios_benchmark.IOS_FINAL_STATE_SCREENSHOT_NAME).is_file()
    assert written["screenshot"]["sha256"] == _sha256_bytes(b"fake-png")
    assert written["errors"] == []
    assert manifest == written


CALENDAR_TASK_YAML = """\
task_id: ios.calendar.create_today_event
platform: ios
instruction: "Create an event."
init:
  initializer_id: x
  params:
    bundle_id: com.apple.mobilecal
evaluation:
  evaluator_id: y
  params: {}
limits:
  max_steps: 5
metadata:
  app_bundle_id: com.apple.mobilecal
"""


def test_calendar_task_captures_calendar_db_not_contacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ios_benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "1")
    container = tmp_path / "container"
    container.mkdir()
    device_data = tmp_path / "device-data"
    _seed_fake_device(device_data)
    monkeypatch.setattr(ios_benchmark, "_ios_device_data_dir", lambda udid: device_data)
    _mock_sim_layer(monkeypatch, container=container)

    out_dir = tmp_path / "run"
    out_dir.mkdir()
    manifest = ios_benchmark.capture_ios_final_state(
        udid="UDID-C",
        task_id="ios.calendar.create_today_event",
        task_file=_write_task(tmp_path, CALENDAR_TASK_YAML, name="cal_task.yaml"),
        model_output_dir=out_dir,
        run_index=1,
    )
    assert "native/Library/Calendar/Calendar.sqlitedb" in manifest["archive_members"]
    assert not any("AddressBook" in name for name in manifest["archive_members"])
    assert manifest["errors"] == []


def test_photos_capture_keeps_metadata_not_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ios_benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "1")
    container = tmp_path / "container"
    container.mkdir()
    device_data = tmp_path / "device-data"
    _seed_fake_device(device_data, contacts=False, calendar=False, photos=True)
    monkeypatch.setattr(ios_benchmark, "_ios_device_data_dir", lambda udid: device_data)
    _mock_sim_layer(monkeypatch, container=container)
    task_file = _write_task(
        tmp_path,
        CONTACTS_TASK_YAML.replace(
            "ios.contacts.add_contact_card", "ios.photos.add_favorite"
        ).replace("com.apple.MobileAddressBook", "com.apple.mobileslideshow"),
        name="photo_task.yaml",
    )

    out_dir = tmp_path / "run"
    out_dir.mkdir()
    manifest = ios_benchmark.capture_ios_final_state(
        udid="UDID-P",
        task_id="ios.photos.add_favorite",
        task_file=task_file,
        model_output_dir=out_dir,
        run_index=2,
    )

    assert "native/Media/PhotoData/Photos.sqlite" in manifest["archive_members"]
    assert not any("DCIM" in name for name in manifest["archive_members"])
    assert not any("IMG_0001" in name for name in manifest["archive_members"])
    assert manifest["photo_library_listing"] == [
        {"path": "100APPLE/IMG_0001.JPG", "size": len(b"raw-photo-bytes")}
    ]
    assert manifest["errors"] == []


# --- errors, outcome preservation -------------------------------------------


def test_capture_failure_records_errors_and_keeps_prior_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ios_benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "1")
    device_data = tmp_path / "device-data"
    _seed_fake_device(device_data)
    monkeypatch.setattr(ios_benchmark, "_ios_device_data_dir", lambda udid: device_data)

    def _boom_container(udid: str, bundle_id: str) -> str:
        raise RuntimeError("simctl get_app_container failed")

    def _boom_shot(udid: str, output_path: Path) -> None:
        raise RuntimeError("simctl io screenshot failed")

    monkeypatch.setattr(
        simulator_manager, "get_app_data_container_path", _boom_container
    )
    monkeypatch.setattr(simulator_manager, "take_screenshot", _boom_shot)

    out_dir = tmp_path / "run"
    out_dir.mkdir()
    trajectory = out_dir / "trajectory.jsonl"
    result = out_dir / "result.json"
    trajectory.write_text('{"step": 1}\n', encoding="utf-8")
    result.write_text('{"status": "fail"}\n', encoding="utf-8")

    manifest = ios_benchmark.capture_ios_final_state(
        udid="UDID-E",
        task_id="ios.contacts.add_contact_card",
        task_file=_write_task(tmp_path, CONTACTS_TASK_YAML),
        model_output_dir=out_dir,
        run_index=1,
        success=False,
        return_code=1,
    )

    assert any("app_container" in err for err in manifest["errors"])
    assert any("screenshot" in err for err in manifest["errors"])
    # Capture must not report PASS/FAIL itself: child outcome passes through.
    assert manifest["child_success"] is False
    assert manifest["child_return_code"] == 1
    # Prior evidence is untouched and the manifest still lands on disk.
    assert trajectory.read_text(encoding="utf-8") == '{"step": 1}\n'
    assert result.read_text(encoding="utf-8") == '{"status": "fail"}\n'
    assert (
        out_dir
        / ios_benchmark.IOS_FINAL_STATE_DIRNAME
        / ios_benchmark.IOS_FINAL_STATE_MANIFEST_NAME
    ).is_file()


# --- ordering + failed-child terminal evidence -------------------------------


def _run_single_with_mocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    child_returncode: int = 1,
    capture_side_effect: Any = None,
) -> Dict[str, Any]:
    """Drive _execute_single_run with reset/child/cleanup/capture mocked."""
    monkeypatch.setenv(ios_benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "1")
    task_file = _write_task(tmp_path, CONTACTS_TASK_YAML)
    run_root = tmp_path / "bench"
    run_root.mkdir(exist_ok=True)
    runner_log = run_root / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    calls: List[str] = []

    runner = ios_benchmark.IOSBenchmarkRunner()
    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner,
        "_run_reset",
        staticmethod(lambda args, context: (True, None, "UDID-RUN", "UDID-RUN")),
    )

    def _fake_child(self: Any, cmd: Any, log_path: Any, **kwargs: Any) -> int:
        child_line = "CHILD-TERMINAL-LINE child ran to completion\n"
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with Path(log_path).open("a", encoding="utf-8") as handle:
            handle.write(child_line)
        return child_returncode

    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner, "run_command_streaming", _fake_child
    )

    def _capture_spy(self: Any, **kwargs: Any) -> Any:
        calls.append("capture")
        if capture_side_effect == "boom":
            raise RuntimeError("capture exploded")
        if capture_side_effect is not None:
            return capture_side_effect
        return {"archive": None, "errors": []}

    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner, "_maybe_capture_ios_final_state", _capture_spy
    )

    def _fake_cleanup(udid: str) -> Any:
        calls.append("cleanup")
        return True, None

    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner,
        "_cleanup_ephemeral_simulator",
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
    # Fully mocked sim boundary: the stub manifest stands in for the real
    # archive while ordering and failed-child evidence are exercised.
    monkeypatch.setenv(ios_benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "1")
    task_file = _write_task(tmp_path, CONTACTS_TASK_YAML)
    run_root = tmp_path / "bench"
    run_root.mkdir(exist_ok=True)
    runner_log = run_root / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    calls: List[str] = []
    runner = ios_benchmark.IOSBenchmarkRunner()
    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner,
        "_run_reset",
        staticmethod(lambda args, context: (True, None, "UDID-RUN", "UDID-RUN")),
    )

    def _failing_child(self: Any, cmd: Any, log_path: Any, **kwargs: Any) -> int:
        with Path(log_path).open("a", encoding="utf-8") as handle:
            handle.write("CHILD-TERMINAL-LINE agent failed at step 3\n")
        return 1

    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner, "run_command_streaming", _failing_child
    )

    def _recording_capture(self: Any, **kwargs: Any) -> Any:
        calls.append("capture")
        assert kwargs["udid"] == "UDID-RUN"
        return {"archive": ios_benchmark.IOS_FINAL_STATE_ARCHIVE_NAME, "errors": []}

    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner,
        "_maybe_capture_ios_final_state",
        _recording_capture,
    )

    def _recording_cleanup(udid: str) -> Any:
        calls.append("cleanup")
        assert udid == "UDID-RUN"
        return True, None

    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner,
        "_cleanup_ephemeral_simulator",
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
    log_text = runner_log.read_text(encoding="utf-8")
    assert "CHILD-TERMINAL-LINE agent failed at step 3" in log_text
    assert "status=FAILED" in log_text


def test_failed_child_with_capture_error_stays_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run_single_with_mocks(
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
    out = _run_single_with_mocks(
        tmp_path, monkeypatch, child_returncode=0, capture_side_effect="boom"
    )
    assert out["result"]["success"] is True
    assert out["result"]["return_code"] == 0


def test_child_exception_still_captures_before_cleanup_and_keeps_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ios_benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "1")
    task_file = _write_task(tmp_path, CONTACTS_TASK_YAML)
    run_root = tmp_path / "bench"
    run_root.mkdir(exist_ok=True)
    runner_log = run_root / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    calls: List[str] = []
    runner = ios_benchmark.IOSBenchmarkRunner()
    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner,
        "_run_reset",
        staticmethod(lambda args, context: (True, None, "UDID-RUN", "UDID-RUN")),
    )

    def _exploding_child(self: Any, cmd: Any, log_path: Any, **kwargs: Any) -> int:
        with Path(log_path).open("a", encoding="utf-8") as handle:
            handle.write("CHILD-TERMINAL-LINE partial output before crash\n")
        raise RuntimeError("child blew up")

    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner, "run_command_streaming", _exploding_child
    )

    def _recording_capture(self: Any, **kwargs: Any) -> Any:
        calls.append("capture")
        return {"archive": None, "errors": []}

    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner,
        "_maybe_capture_ios_final_state",
        _recording_capture,
    )

    def _recording_cleanup(udid: str) -> Any:
        calls.append("cleanup")
        return True, None

    monkeypatch.setattr(
        ios_benchmark.IOSBenchmarkRunner,
        "_cleanup_ephemeral_simulator",
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


def test_oversized_files_are_skipped_not_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ios_benchmark.OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "1")
    monkeypatch.setattr(ios_benchmark, "IOS_FINAL_STATE_MAX_FILE_BYTES", 4)
    container = tmp_path / "container"
    container.mkdir()
    (container / "big.bin").write_bytes(b"0123456789")
    (container / "small.bin").write_bytes(b"ok")
    device_data = tmp_path / "device-data"
    device_data.mkdir()
    monkeypatch.setattr(ios_benchmark, "_ios_device_data_dir", lambda udid: device_data)
    _mock_sim_layer(monkeypatch, container=container)

    out_dir = tmp_path / "run"
    out_dir.mkdir()
    manifest = ios_benchmark.capture_ios_final_state(
        udid="UDID-S",
        task_id="ios.maily.send_email",
        task_file=_write_task(tmp_path, INIT_ONLY_TASK_YAML, name="maily.yaml"),
        model_output_dir=out_dir,
        run_index=1,
    )
    assert "app_container/small.bin" in manifest["archive_members"]
    assert "app_container/big.bin" not in manifest["archive_members"]
    assert any(
        entry["path"] == "app_container/big.bin"
        and entry["reason"] == "file-size-exceeded"
        for entry in manifest["skipped"]
    )


@pytest.fixture(autouse=True)
def mock_shared_group_query(monkeypatch):
    monkeypatch.setattr(ios_benchmark, "_ios_shared_group_paths", lambda *args: [])
