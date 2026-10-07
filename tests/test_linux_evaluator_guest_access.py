"""Linux evaluators read the guest, not the host that runs them."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

from core.evaluation import EvalResult, EvalStatus
from platforms.linux.runners.evaluation import (
    EvaluatorControllerView,
    build_evaluator_context,
    normalize_script_result,
    run_task_evaluation,
)


class _LinuxRuntime:
    """Answers like the Linux guest runtime: /run_python uses ``return_code``."""

    def __init__(self, python_output: str = "", bash_output: str = "") -> None:
        self.python_output = python_output
        self.bash_output = bash_output
        self.scripts: list[str] = []

    def run_python_script(self, code, *, timeout=30):
        self.scripts.append(code)
        return {"output": self.python_output, "error": "", "return_code": 0, "status": "success"}

    def run_bash_script(self, script, *, timeout=30, working_dir=None):
        self.scripts.append(script)
        return {"output": self.bash_output, "error": "", "returncode": 0, "status": "success"}

    def observe(self):
        return SimpleNamespace(ui_nodes=[])


def test_script_results_expose_every_key_evaluators_read() -> None:
    python = normalize_script_result({"output": "x\n", "error": "w", "return_code": 0, "status": "success"})
    assert python["returncode"] == 0 and python["return_code"] == 0
    assert python["stdout"] == "x\n" and python["output"] == "x\n"
    assert python["stderr"] == "w" and python["error"] == "w"

    failed = normalize_script_result({"output": "", "error": "boom", "returncode": 2, "status": "error"})
    assert failed["returncode"] == 2 and failed["stderr"] == "boom"

    # Keys the runtime already returned are kept as they are.
    kept = normalize_script_result({"returncode": 3, "stdout": "a", "output": "b"})
    assert (kept["returncode"], kept["stdout"], kept["output"]) == (3, "a", "b")
    assert normalize_script_result({"status": "success"})["returncode"] == 0
    assert normalize_script_result(None) is None


def test_evaluator_context_wraps_only_the_script_methods() -> None:
    runtime = _LinuxRuntime(python_output="1\n")
    context = build_evaluator_context(params={}, controller=runtime, final_observation=None)
    view = context["controller"]
    assert isinstance(view, EvaluatorControllerView)
    assert view.run_python_script("print(1)")["returncode"] == 0
    assert view.observe().ui_nodes == []
    assert view.wrapped_controller is runtime
    assert not hasattr(view, "run_powershell_script")
    assert build_evaluator_context(params={}, controller=None, final_observation=None)["controller"] is None


def test_runner_hands_evaluators_the_normalized_controller(monkeypatch) -> None:
    seen = {}

    class _Probe:
        def evaluate(self, context):
            seen["result"] = context["controller"].run_python_script("print(1)")
            return EvalResult(status=EvalStatus.PASS)

    monkeypatch.setattr("platforms.linux.runners.evaluation.load_evaluator", lambda _id: _Probe())
    monkeypatch.setattr("platforms.linux.runners.evaluation.with_task_binding", lambda context, task: context)
    task = SimpleNamespace(evaluation=SimpleNamespace(evaluator_id="x:Y", params={}))
    run = run_task_evaluation(
        task=task, controller=_LinuxRuntime("ok\n"), final_observation=None, model_id="m", run_dir=Path(".")
    )
    assert run.result.status == EvalStatus.PASS
    assert seen["result"]["returncode"] == 0 and seen["result"]["stdout"] == "ok\n"


def test_thunderbird_readers_accept_the_linux_run_python_result() -> None:
    from evaluators.cua_review.evaluators.linux import thunderbird, thunderbird_calendar

    payload = {"files": [], "rules": [], "errors": []}
    view = EvaluatorControllerView(_LinuxRuntime(python_output=json.dumps(payload) + "\n"))
    assert thunderbird._run_program(view, "print(1)", 10) == payload

    state = {"thunderbird_calendar": {"profile_root": "/home/user/.thunderbird"}}
    view = EvaluatorControllerView(_LinuxRuntime(python_output=json.dumps(state) + "\n"))
    evidence = thunderbird_calendar.read_calendar_evidence(view, {})
    assert evidence["profile_root"] == "/home/user/.thunderbird"


def test_guest_paths_use_the_guest_home() -> None:
    from evaluators.cua_review.evaluators.linux.blender import OpenBlenderStateEvaluator
    from evaluators.cua_review.evaluators.linux.openwireshark import OpenWiresharkWorkflowEvaluator
    from evaluators.cua_review.platforms.linux.local_storage import GUEST_HOME, guest_path

    assert guest_path("$HOME/a") == f"{GUEST_HOME}/a"
    assert guest_path("${HOME}/a") == f"{GUEST_HOME}/a"
    assert guest_path("~/a") == f"{GUEST_HOME}/a"
    assert guest_path("$HOMEDIR/a") == "$HOMEDIR/a"
    assert guest_path("/abs/a") == "/abs/a"
    host_home = os.path.expanduser("~")
    for dirs in (OpenBlenderStateEvaluator._storage_dirs({}), OpenWiresharkWorkflowEvaluator._storage_dirs({})):
        assert dirs and all(item.startswith(GUEST_HOME + "/") for item in dirs)
        if host_home != GUEST_HOME:
            assert not any(item.startswith(host_home + "/") for item in dirs)


def test_openmail_reads_the_guest_profile_path() -> None:
    from evaluators.cua_review.evaluators.linux import openmail
    from evaluators.cua_review.platforms.linux.local_storage import GUEST_HOME

    runtime = _LinuxRuntime(python_output='{"mailboxes": []}\n')
    state, directory = openmail.read_state_document({"controller": EvaluatorControllerView(runtime)}, {})
    assert state == {"mailboxes": []}
    assert directory.startswith(GUEST_HOME + "/.config/")


def test_local_storage_guest_reader_expands_home_variable(tmp_path, monkeypatch) -> None:
    from evaluators.cua_review.platforms.linux import local_storage

    store = tmp_path / "leveldb"
    store.mkdir()
    (store / "000001.log").write_bytes(b"")
    namespace: dict = {}
    exec(compile(local_storage.LOCAL_STORAGE_SOURCE, "<reader>", "exec"), namespace)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert [path.name for path in namespace["_store_files"]("$HOME/leveldb")] == ["000001.log"]


def test_openzotero_scan_reads_storage_before_caches(tmp_path) -> None:
    from evaluators.cua_review.evaluators.linux import openzotero

    profile = tmp_path / "google-chrome"
    for index in range(30):
        cache = profile / "GrShaderCache" / f"data_{index}"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("shader")
        crash = profile / "Crash Reports" / f"report_{index}"
        crash.parent.mkdir(parents=True, exist_ok=True)
        crash.write_text("crash")
    noise = profile / "Default" / "Preferences"
    noise.parent.mkdir(parents=True, exist_ok=True)
    noise.write_text("{}")
    storage = profile / "Default" / "Local Storage" / "leveldb" / "000003.log"
    storage.parent.mkdir(parents=True, exist_ok=True)
    storage.write_text("Agent Reliability Review")

    params = {"scan_roots": [str(profile)], "max_files": 1, "required_global_text": ["Agent Reliability Review"]}
    program = openzotero._scan_program(params, [])
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(compile(program, "<scan>", "exec"), {"__name__": "__scan__"})
    result = json.loads(buffer.getvalue())
    assert any(str(storage) == source for source in result.get("sources") or []), result.get("sources")


def test_openzotero_document_dirs_are_guest_paths() -> None:
    from evaluators.cua_review.evaluators.linux import openzotero
    from evaluators.cua_review.platforms.linux.local_storage import GUEST_HOME

    directories = openzotero._storage_directories({})
    assert directories and all(item.startswith(GUEST_HOME + "/") for item in directories)


class _OpenTripGuest:
    """Holds an OpenTrip document per Local Storage directory, with store mtimes."""

    def __init__(self, documents: dict[str, dict], mtimes: dict[str, float]) -> None:
        self.documents = documents
        self.mtimes = mtimes

    def run_python_script(self, script, *, timeout=30):
        for directory, mtime in self.mtimes.items():
            if "getmtime" in script and json.dumps(directory) in script:
                return {"output": json.dumps(mtime) + "\n", "return_code": 0, "status": "success"}
        for directory, document in self.documents.items():
            if json.dumps(directory) in script:
                return {"output": json.dumps(document) + "\n", "return_code": 0, "status": "success"}
        return {"output": "null\n", "return_code": 0, "status": "success"}


def test_opentrip_reads_the_desktop_launcher_profile() -> None:
    from evaluators.cua_review.platforms.linux import opentrip_support as support

    launcher = support.LAUNCHER_LEVELDB_PATH
    assert "osomni-openapps/launch-opentrip" in launcher
    only_launcher = _OpenTripGuest({launcher: {"bookings": [1]}}, {launcher: 5.0})
    payload = support.read_opentrip_local_state(EvaluatorControllerView(only_launcher))
    assert payload["state"] == {"bookings": [1]} and payload["source_file"] == launcher

    both = _OpenTripGuest(
        {support.DEFAULT_LEVELDB_PATH: {"bookings": ["stale"]}, launcher: {"bookings": ["fresh"]}},
        {support.DEFAULT_LEVELDB_PATH: 1.0, launcher: 9.0},
    )
    assert support.read_opentrip_local_state(both)["state"] == {"bookings": ["fresh"]}

    default_newer = _OpenTripGuest(
        {support.DEFAULT_LEVELDB_PATH: {"bookings": ["default"]}, launcher: {"bookings": ["old"]}},
        {support.DEFAULT_LEVELDB_PATH: 9.0, launcher: 1.0},
    )
    assert support.read_opentrip_local_state(default_newer)["state"] == {"bookings": ["default"]}


def test_command_check_keeps_a_zero_exit_code_and_never_runs_on_the_host() -> None:
    from evaluators.cua_review.evaluators.linux import command_check

    class _PythonOnly:
        def run_python_script(self, code, *, timeout=30):
            return {"output": json.dumps({"returncode": 0, "stdout": "OK", "stderr": ""}), "return_code": 0}

    assert command_check.run_command(_PythonOnly(), "true", 5)["returncode"] == 0

    class _Unreachable:
        def run_bash_script(self, script, *, timeout=30):
            raise OSError("guest down")

    assert command_check.run_command(_Unreachable(), "true", 5) is None


def test_opennavigation_route_review_reads_the_browser_page() -> None:
    from evaluators.cua_review.evaluators.linux.opennavigation import OpenNavigationRouteReviewEvaluator

    page = {"pages": [{"url": "http://127.0.0.1:4321/", "title": "OpenNavigation", "text": "Route Walk Bike"}],
            "errors": []}
    runtime = _LinuxRuntime(python_output=json.dumps(page) + "\n")
    context = {
        "controller": EvaluatorControllerView(runtime),
        "params": {"required_terms": ["Route", "Walk", "Bike"], "forbidden_terms": ["Hotels Option"],
                   "profile_dir": "/nonexistent", "service_url": "http://127.0.0.1:9"},
        "final_observation": SimpleNamespace(ui_nodes=[]),
    }
    result = OpenNavigationRouteReviewEvaluator().evaluate(context)
    assert result.status == EvalStatus.PASS, result.message
    assert result.metadata["browser_pages"][0]["text_length"] == len("Route Walk Bike")
    assert any("Runtime.evaluate" in script for script in runtime.scripts)


def test_marble_evaluator_closes_marble_before_reading_its_settings() -> None:
    from evaluators.linux.marble import MarbleBookmarkEvaluator

    class _Guest:
        def __init__(self):
            self.scripts = []

        def run_bash_script(self, script, *, timeout=30):
            self.scripts.append(script)
            if "wmctrl" in script:
                return {"output": '{"was_running": true, "exited": true}\n', "returncode": 0}
            payload = {"bookmarks_exists": True, "config_exists": True, "folders": [], "placemarks": [],
                       "map_theme": "earth/openstreetmap/openstreetmap.dgml"}
            return {"output": json.dumps(payload), "returncode": 0}

    guest = _Guest()
    result = MarbleBookmarkEvaluator().evaluate(
        {"controller": guest, "params": {"map_theme": "earth/openstreetmap/openstreetmap.dgml"}}
    )
    assert result.status == EvalStatus.PASS, result.message
    assert "wmctrl -ic" in guest.scripts[0] and "pkill" not in guest.scripts[0]
    assert result.metadata["app_close"] == {"was_running": True, "exited": True}


def test_openslide_qa70_rehearsal_is_matched_by_action_not_annotator_phrases(tmp_path):
    import json

    from evaluators.linux.openslide_qa70_review_199367 import _collect_trajectory_process

    def row(index, response, code):
        return {"step_index": index, "llm_response": response,
                "action_parse": {"action": {"code": code}}, "action_execution": {"status": "SUCCESS"}}

    rows = [
        row(1, "Click Rehearse in the Slide Show tab.", "pyautogui.click(1, 1)"),
        row(2, "Advance one slide.", "pyautogui.press('right')"),
        row(3, "Click Next.", "pyautogui.click(2, 2)"),
        row(4, "Leave the show.", "pyautogui.press('esc')"),
    ]
    (tmp_path / "trajectory.jsonl").write_text("\n".join(json.dumps(item) for item in rows))
    evidence = _collect_trajectory_process({"run_dir": str(tmp_path)})
    assert [check["check_id"] for check in evidence["checks"]] == ["slideshow.rehearse_navigation"]
    assert evidence["checks"][0]["passed"]

    (tmp_path / "trajectory.jsonl").write_text("\n".join(json.dumps(item) for item in rows[:3]))
    assert not _collect_trajectory_process({"run_dir": str(tmp_path)})["checks"][0]["passed"]
