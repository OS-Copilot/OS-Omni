#!/usr/bin/env python3
"""Capture initializer-success / initial-FAIL evidence for macOS tasks.

Runs task initialization and its evaluator against the single, already-running
macOS guest. It never creates a model client or executes agent actions. The
result is suitable for the author_eval_queue initial-fail gate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platforms.macos.host.core.types import load_task_from_file
from platforms.macos.host.runners.episode import wait_for_runtime_ready
from platforms.macos.host.runners.evaluation import run_task_evaluation
from platforms.macos.host.runners.initialization import run_task_initialization
from platforms.macos.host.runtime_env.vm_runtime_controller import VMRuntimeController
from platforms.macos.runtime_config import MACOS_RUNTIME_CONFIG_PATH, load_macos_runtime_config
from scripts.author_eval_queue import (
    code_version_hash,
    load_manifest_tasks,
    manifest_hash,
    sha256_file,
    task_implementation_hash,
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_preflight(
    *,
    task_ids: list[str] | None,
    output_dir: Path,
    model_id: str = "deepseek_flash",
) -> dict[str, Any]:
    config = load_macos_runtime_config(MACOS_RUNTIME_CONFIG_PATH)
    vm_ip = os.environ.get("HELLOWORLD_MACOS_VM_IP", config.vm_ip)
    runtime_url = f"http://{vm_ip}:{config.runtime_port}"
    wait_for_runtime_ready(runtime_url, config.vm_token)
    controller = VMRuntimeController(runtime_url=runtime_url, token=config.vm_token, timeout=30)

    inventory = load_manifest_tasks(platform="macos")
    by_id = {entry["task_id"]: entry for entry in inventory}
    selected = task_ids or [entry["task_id"] for entry in inventory]
    unknown = sorted(set(selected) - set(by_id))
    if unknown:
        raise ValueError(f"unknown macOS task id(s): {unknown}")

    entries: dict[str, Any] = {}
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report_path = output_dir / "initial_fail_evidence.json"
    if report_path.exists():
        try:
            prior = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(prior, dict):
                entries.update(prior)
        except (OSError, json.JSONDecodeError):
            pass
    for task_id in selected:
        task_file = (ROOT / by_id[task_id]["task_path"]).resolve()
        task = load_task_from_file(str(task_file))
        task_dir = output_dir / task_id.replace(".", "_")
        screenshot_dir = task_dir / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        controller.update_screenshot_dir(str(screenshot_dir))

        try:
            init_result = run_task_initialization(
                task=task,
                build_context=lambda task=task, task_dir=task_dir: {
                    "task": task,
                    "params": dict(task.init.params) if task.init else {},
                    "controller": controller,
                    "run_dir": task_dir,
                },
                model_id=model_id,
                run_dir=task_dir,
            )
        except Exception as exc:
            failure = {
                "status": "ERROR",
                "phase": "initializer",
                "message": f"{type(exc).__name__}: {exc}",
                "task_sha256": sha256_file(task_file),
                "task_implementation_sha256": task_implementation_hash(task_file),
                "evidence": str(task_dir / "preflight.json"),
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
            _write_json(task_dir / "preflight.json", failure)
            entries[task_id] = failure
            _write_json(report_path, entries)
            print(f"[{len(entries)}/{len(inventory)}] {task_id}: ERROR (initializer exception)", flush=True)
            continue
        init_status = init_result.result.status.value if init_result else "PASS"
        if init_status != "PASS":
            failure = {
                "status": "ERROR",
                "phase": "initializer",
                "initializer": init_result.summary if init_result else None,
                "task_sha256": sha256_file(task_file),
                "task_implementation_sha256": task_implementation_hash(task_file),
                "evidence": str(task_dir / "preflight.json"),
            }
            _write_json(task_dir / "preflight.json", failure)
            entries[task_id] = failure
            _write_json(report_path, entries)
            print(f"[{len(entries)}/{len(inventory)}] {task_id}: ERROR (initializer)", flush=True)
            continue

        try:
            # Match the formal queue's screenshot-only observation mode. Large
            # Blender accessibility trees can stall AX while the screenshot
            # and state-backed evaluator remain healthy.
            observation = controller.observe(include_ui_tree=False, include_screenshot_data=False)
            evaluation_result = run_task_evaluation(
                task=task,
                build_context=lambda task=task, task_dir=task_dir, observation=observation: {
                    "task": task,
                    "params": dict(task.evaluation.params) if task.evaluation else {},
                    "controller": controller,
                    "final_observation": observation,
                    "run_dir": task_dir,
                },
                model_id=model_id,
                run_dir=task_dir,
            )
            if evaluation_result is None:
                status = "ERROR"
                evaluation_summary = None
            else:
                status = evaluation_result.result.status.value
                evaluation_summary = evaluation_result.summary
            shot = controller.save_screenshot("initial")
        except Exception as exc:
            status = "ERROR"
            evaluation_summary = {"exception": f"{type(exc).__name__}: {exc}"}
            shot = None
        record = {
            "status": status,
            "initializer_status": init_status,
            "initializer": init_result.summary if init_result else None,
            "evaluation": evaluation_summary,
            "task_sha256": sha256_file(task_file),
            "task_implementation_sha256": task_implementation_hash(task_file),
            "evidence": str(task_dir / "preflight.json"),
            "initial_screenshot": shot,
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _write_json(task_dir / "preflight.json", record)
        entries[task_id] = record
        _write_json(report_path, entries)
        print(f"[{len(entries)}/{len(inventory)}] {task_id}: {status}", flush=True)

    preflight = {
        "passed": len(entries) == len(selected)
        and all(item.get("status") == "FAIL" and item.get("initializer_status") == "PASS" for item in entries.values()),
        "platform": "macos",
        "checks": {
            "runtime_health": "HEALTHY",
            "runtime_url": runtime_url,
            "resolution": f"{controller.width}x{controller.height}",
            "task_count": len(entries),
            "expected_task_count": len(selected),
            "inventory_task_count": len(inventory),
            "manifest_sha256": manifest_hash(),
            "code_version": code_version_hash("macos"),
            "started_at": started_at,
        },
    }
    _write_json(output_dir / "preflight_report.json", preflight)
    return {"preflight": preflight, "initial_fail_evidence": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT.parent / "records" / "macos-author-preflight"),
    )
    args = parser.parse_args()
    result = run_preflight(task_ids=args.task_ids, output_dir=Path(args.output_dir))
    print(json.dumps(result["preflight"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
