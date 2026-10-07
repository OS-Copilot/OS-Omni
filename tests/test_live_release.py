from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

from core.specs.loader import load_execution_spec, load_task_spec
from platforms.cross_vm.types import load_cross_vm_task
from tools.import_cua_tasks_review import _walk_strings


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = REPO_ROOT / "tasks" / "v1"
MANIFEST = json.loads((RELEASE_ROOT / "manifest.json").read_text())


TRACKS = ("android", "ios", "linux", "macos", "web", "windows")
ALL_TRACKS = (*TRACKS, "cross_vm")


def test_v1_has_300_unique_tasks_in_balanced_tracks_plus_cross_vm() -> None:
    entries = MANIFEST["tasks"]
    assert MANIFEST["release"] == "v1"
    assert MANIFEST["task_count"] == len(entries) == 300
    assert len({entry["task_id"] for entry in entries}) == 300
    assert Counter(entry["track"] for entry in entries) == MANIFEST["track_counts"] == {
        **{track: 48 for track in TRACKS}, "cross_vm": 12,
    }
    assert Counter(entry["platform"] for entry in entries) == MANIFEST["platform_counts"] == {
        "android": 48, "ios": 48, "linux": 96, "macos": 48, "windows": 48, "cross_vm": 12,
    }
    assert all(
        entry["track"] == entry["platform"]
        or (entry["track"] == "web" and entry["platform"] == "linux")
        for entry in entries
    )
    assert Counter(entry["category"] for entry in entries) == MANIFEST["category_counts"]
    assert {REPO_ROOT / entry["task_path"] for entry in entries} == {
        path for track in ALL_TRACKS for path in (RELEASE_ROOT / track).glob("*.yaml")
    }
    for entry in entries:
        path = REPO_ROOT / entry["task_path"]
        assert path.parent.name == entry["track"]
        if entry["platform"] == "cross_vm":
            assert load_cross_vm_task(path).task_id == entry["task_id"]
            continue
        spec = load_task_spec(path)
        assert spec.task_id == entry["task_id"]
        assert spec.platform == entry["platform"]


def test_retired_tasks_are_gone_and_two_per_track() -> None:
    retired = MANIFEST["retired"]
    assert Counter(entry["track"] for entry in retired) == {track: 2 for track in TRACKS}
    listed = {entry["task_id"] for entry in MANIFEST["tasks"]}
    for entry in retired:
        assert entry["task_id"] not in listed
        assert not (REPO_ROOT / entry["task_path"]).exists()


def test_cross_vm_workflows_are_complete() -> None:
    support = {REPO_ROOT / path for path in MANIFEST["supporting"]["cross_vm_stages"]}
    assert support == set((RELEASE_ROOT / "cross_vm" / "stages").rglob("*.yaml"))
    supporting = set((RELEASE_ROOT / "cross_vm" / "stages").glob("*/*.yaml"))
    assert len(supporting) == 24
    reserved = support | set((RELEASE_ROOT / "cross_vm" / "oracle").glob("*.yaml"))
    routes = Counter()
    referenced_stages = set()
    for path in sorted((RELEASE_ROOT / "cross_vm").glob("*.yaml")):
        task = load_cross_vm_task(path)
        routes[(task.source_platform, task.target_platform)] += 1
        assert task.metadata["difficulty"] == "hard"
        assert task.metadata["human_steps"] >= 100
        assert sum(task.metadata["human_steps_by_stage"].values()) == task.metadata["human_steps"]
        for stage_path, platform in (
            (task.source_task_path, task.source_platform),
            (task.target_task_path, task.target_platform),
        ):
            assert stage_path in supporting
            assert load_task_spec(stage_path).platform == platform
            referenced_stages.add(stage_path)
        oracle = load_cross_vm_task(path.parent / "oracle" / f"{path.stem}_oracle.yaml")
        assert oracle.source_platform == task.source_platform
        assert oracle.target_platform == task.target_platform
        for stage_path in (oracle.source_task_path, oracle.target_task_path):
            assert stage_path in reserved
            load_task_spec(stage_path)
    assert routes == {("android", "windows"): 6, ("windows", "linux"): 6}
    assert referenced_stages == supporting


def test_no_unlisted_tasks_or_missing_runtime_assets() -> None:
    listed = {entry["task_path"] for entry in MANIFEST["tasks"]}
    support = set(MANIFEST["supporting"]["cross_vm_stages"])
    oracles = set(MANIFEST["oracle_tasks"])
    assert not (listed & support or listed & oracles or support & oracles)
    assert listed | support | oracles == {
        path.relative_to(REPO_ROOT).as_posix() for path in RELEASE_ROOT.rglob("*.yaml")
    }
    for relative in listed | support | oracles:
        path = REPO_ROOT / relative
        raw = yaml.safe_load(path.read_text())
        if raw["platform"] != "cross_vm":
            load_task_spec(path)
        for value in _walk_strings({"init": raw.get("init"), "evaluation": raw.get("evaluation")}):
            if value.startswith("tasks/"):
                assert (REPO_ROOT / value).exists(), (relative, value)
            elif value.startswith(("files/", "../files/")):
                assert (path.parent / value).exists(), (relative, value)


def test_execution_configs_reference_retained_tasks_and_cover_v1() -> None:
    known = {entry["task_path"] for entry in MANIFEST["tasks"]}
    known.update(MANIFEST["supporting"]["cross_vm_stages"])
    known.update(MANIFEST["oracle_tasks"])
    for path in (REPO_ROOT / "executions").rglob("*.yaml"):
        spec = load_execution_spec(path)
        assert all(task.relative_to(REPO_ROOT).as_posix() in known for task in spec.task_paths), path
    for track in ALL_TRACKS:
        spec = load_execution_spec(REPO_ROOT / "executions" / "v1" / f"{track}.yaml")
        assert {path.relative_to(REPO_ROOT).as_posix() for path in spec.task_paths} == {
            entry["task_path"] for entry in MANIFEST["tasks"] if entry["track"] == track
        }


def test_oracle_discovery_finds_versioned_tasks_and_cross_vm_stages() -> None:
    from core.llm.providers.windows_oracle_adapter import WindowsOracleAdapter
    from platforms.linux.core.oracle_specs import find_task_path
    from platforms.macos.host.core.oracle_specs import find_oracle_spec

    windows = WindowsOracleAdapter()._task_instruction_index()
    assert "windows.cross_vm.calc_budget_review_hard" in windows
    assert "windows.notepad.append_text" in windows
    assert find_task_path("linux.cross_vm.calc_budget_review_hard").is_file()
    assert find_oracle_spec(task_id="macos.vscodium.incident_handoff_refresh") is not None


def test_setup_scripts_are_not_spliced_download_blocks() -> None:
    # An upstream bulk edit once spliced heredoc download blocks into every
    # run_bash step ("PY|"), which silently broke task initialization.
    for entry in MANIFEST["tasks"]:
        text = (REPO_ROOT / entry["task_path"]).read_text(encoding="utf-8")
        assert "PY|" not in text, entry["task_path"]
