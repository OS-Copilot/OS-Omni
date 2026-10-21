from collections import Counter
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_consolidated_records_preserve_scored_and_untested_results():
    runs = json.loads((ROOT / "records/consolidated-20261021/runs.json").read_text(encoding="utf-8"))
    tasks = json.loads((ROOT / "tasks/v1/manifest.json").read_text(encoding="utf-8"))["tasks"]
    assert len(runs) == 259
    assert Counter(run["result"] for run in runs) == {"PASS": 64, "FAIL": 179, "": 16}
    assert all(run["task_id"] in {task["task_id"] for task in tasks} for run in runs)
    assert len({(run["task_id"], run["model"]) for run in runs}) == len(runs)
    assert all(run["result"] == "" for run in runs if run["raw_status"] == "ERROR")
    assert all("unspecified" not in run["model"] for run in runs)
    assert all(run["archives"] for run in runs)
    android = [run for run in runs if run["model"] == "deepseek-flash-1017(high)"]
    assert len(android) == 48
    assert Counter(run["result"] for run in android) == {"PASS": 20, "FAIL": 28}
    assert all(run["source_reasoning"] == {"reasoning_effort": "high"} for run in android)


def test_release_inventory_covers_every_run_and_stays_below_asset_limit():
    directory = ROOT / "records/consolidated-20261021"
    manifest = json.loads((directory / "release-manifest.json").read_text(encoding="utf-8"))
    runs = json.loads((directory / "runs.json").read_text(encoding="utf-8"))
    archives = {asset["name"]: asset for asset in manifest["archives"]}
    assert len(archives) == len(manifest["archives"]) == 41
    assert set(archives) == {archive for run in runs for archive in run["archives"]}
    assert all(0 < asset["size"] < 2 * 1024**3 for asset in archives.values())
    assert all(len(asset["sha256"]) == 64 for asset in archives.values())
    assert manifest["records"] == len(runs)
    assert manifest["excluded_hf_runs"] == 91
    assert manifest["source_bundle"]["name"] == "touchstone-all-branches.bundle"
