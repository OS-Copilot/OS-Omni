#!/usr/bin/env python3
"""Export latest PASS screenshots into a tracked directory for PR attachment."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = REPO_ROOT / "results"


def _safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_").lower()


def _load_execution_task_ids(execution_path: Path) -> list[str]:
    payload = yaml.safe_load(execution_path.read_text(encoding="utf-8")) or {}
    task_items = payload.get("tasks") or []
    task_ids: list[str] = []
    for item in task_items:
        task_path = Path(item)
        if not task_path.is_absolute():
            task_path = (REPO_ROOT / task_path).resolve()
        task_payload = yaml.safe_load(task_path.read_text(encoding="utf-8")) or {}
        task_id = str(task_payload.get("task_id") or "").strip()
        if not task_id:
            raise ValueError(f"task_id missing in {task_path}")
        task_ids.append(task_id)
    return task_ids


def _iter_target_task_ids(executions: Iterable[Path], explicit_task_ids: Iterable[str]) -> list[str]:
    task_ids = list(dict.fromkeys(str(task_id).strip() for task_id in explicit_task_ids if str(task_id).strip()))
    for execution_path in executions:
        for task_id in _load_execution_task_ids(execution_path):
            if task_id not in task_ids:
                task_ids.append(task_id)
    if not task_ids:
        raise ValueError("no target task ids resolved; pass --execution and/or --task-id")
    return task_ids


def _pick_latest_pass_results(task_ids: set[str]) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for result_path in RESULTS_ROOT.rglob("result.json"):
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        task_id = str(payload.get("task_id") or "").strip()
        status = str(payload.get("status") or "").strip().upper()
        if task_id not in task_ids or status != "PASS":
            continue
        screenshot_rel = payload.get("final_observation", {}).get("screenshot_path") or "screenshots/final.jpg"
        screenshot_path = _resolve_screenshot_path(result_path=result_path, screenshot_value=screenshot_rel)
        if not screenshot_path.exists():
            continue
        ended_at = str(payload.get("ended_at") or payload.get("started_at") or "")
        candidate = {
            "task_id": task_id,
            "result_path": str(result_path.resolve()),
            "screenshot_path": str(screenshot_path),
            "ended_at": ended_at,
            "status": status,
            "steps_taken": payload.get("steps_taken"),
        }
        existing = best.get(task_id)
        if existing is None or candidate["ended_at"] > existing["ended_at"]:
            best[task_id] = candidate
    return best


def _resolve_screenshot_path(*, result_path: Path, screenshot_value: str) -> Path:
    screenshot_path = Path(str(screenshot_value))
    if screenshot_path.is_absolute():
        return screenshot_path

    repo_candidate = (REPO_ROOT / screenshot_path).resolve()
    if repo_candidate.exists():
        return repo_candidate

    run_candidate = (result_path.parent / screenshot_path).resolve()
    if run_candidate.exists():
        return run_candidate

    suffix = screenshot_path.suffix.lower()
    if suffix == ".jpg":
        alt_repo = (REPO_ROOT / screenshot_path.with_suffix(".png")).resolve()
        if alt_repo.exists():
            return alt_repo
        alt_run = (result_path.parent / screenshot_path.with_suffix(".png")).resolve()
        if alt_run.exists():
            return alt_run
    elif suffix == ".png":
        alt_repo = (REPO_ROOT / screenshot_path.with_suffix(".jpg")).resolve()
        if alt_repo.exists():
            return alt_repo
        alt_run = (result_path.parent / screenshot_path.with_suffix(".jpg")).resolve()
        if alt_run.exists():
            return alt_run

    return run_candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execution",
        action="append",
        default=[],
        help="Execution YAML to source task ids from. Repeatable.",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        default=[],
        help="Explicit task id to export. Repeatable.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Tracked directory to receive exported PNG files and manifest.json.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    execution_paths = []
    for raw in args.execution:
        path = Path(raw)
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"execution file not found: {path}")
        execution_paths.append(path)

    task_ids = _iter_target_task_ids(execution_paths, args.task_id)
    latest = _pick_latest_pass_results(set(task_ids))

    missing = [task_id for task_id in task_ids if task_id not in latest]
    if missing:
        print(json.dumps({"status": "error", "missing_task_ids": missing}, ensure_ascii=False, indent=2))
        return 1

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (REPO_ROOT / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries = []
    for task_id in task_ids:
        item = latest[task_id]
        source_suffix = Path(item["screenshot_path"]).suffix or ".jpg"
        filename = f"{_safe_slug(task_id)}{source_suffix}"
        target = output_dir / filename
        shutil.copy2(item["screenshot_path"], target)
        manifest_entries.append(
            {
                "task_id": task_id,
                "exported_png": str(target.relative_to(REPO_ROOT)),
                "source_result": str(Path(item["result_path"]).relative_to(REPO_ROOT)),
                "source_screenshot": str(Path(item["screenshot_path"]).relative_to(REPO_ROOT)),
                "ended_at": item["ended_at"],
                "steps_taken": item["steps_taken"],
            }
        )

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"status": "ok", "exports": manifest_entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "ok", "output_dir": str(output_dir), "count": len(manifest_entries)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
