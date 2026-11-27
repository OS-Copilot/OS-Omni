from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from dotenv import load_dotenv

    load_dotenv(repo_root / ".env")
except ImportError:
    pass

from platforms.android.controller import AdbController
from platforms.android.core.types import load_task_from_file
from platforms.android.device_stability import wait_for_device_stable
from platforms.android.runtime_config import load_android_runtime_config, load_execution_handoff
from platforms.android.runners.initialization import run_task_initialization


DEFAULT_EXECUTION = "executions/v1/android.yaml"
DEFAULT_MODEL_ID = "gpt5_4"


def _safe_name(raw: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(raw or "unnamed"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_initializers(*, execution_path: str, model_id: str, adb_device: str | None) -> int:
    execution = load_execution_handoff(execution_path)
    config = load_android_runtime_config()
    device = adb_device or config.adb_device

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    execution_name = _safe_name(execution["source_path"].stem)
    run_root = (
        repo_root
        / "results"
        / _safe_name(model_id)
        / "android"
        / f"{execution_name}_init_only_{timestamp}"
    )
    run_root.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("android_init_only")
    controller = AdbController(adb_device=device)
    controller.disable_touch_debug_overlays()

    rows: list[dict[str, Any]] = []
    task_paths = list(execution.get("task_paths") or [])
    for index, task_path in enumerate(task_paths, start=1):
        task = load_task_from_file(str(task_path))
        task_id = str(getattr(task, "id", "") or Path(task_path).stem)
        task_run_dir = run_root / _safe_name(task_id)
        task_run_dir.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now().astimezone().isoformat()
        print(f"[{index}/{len(task_paths)}] init {task_id}", flush=True)

        status = "ERROR"
        message = ""
        initializer_summary: dict[str, Any] | None = None
        stability: dict[str, Any] = {}
        start = time.time()
        try:
            stability = wait_for_device_stable(controller)
            init_run = run_task_initialization(
                task=task,
                controller=controller,
                model_id=model_id,
                run_dir=task_run_dir,
                logger_obj=logger,
            )
            if init_run is None:
                status = "SKIP"
                message = "Task has no initializer"
            else:
                initializer_summary = init_run.summary
                status = str(initializer_summary.get("status") or "ERROR")
                message = str(initializer_summary.get("message") or "")
        except Exception as exc:
            status = "ERROR"
            message = f"{type(exc).__name__}: {exc}"

        ended_at = datetime.now().astimezone().isoformat()
        latency_ms = (time.time() - start) * 1000.0
        payload = {
            "task_id": task_id,
            "platform": "android",
            "model_id": model_id,
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "latency_ms": latency_ms,
            "task_path": str(task_path),
            "device_stability": stability,
            "initializer": initializer_summary
            or {
                "status": status,
                "message": message,
                "metadata": {},
            },
        }
        _write_json(task_run_dir / "result.json", payload)
        rows.append(
            {
                "task_id": task_id,
                "status": status,
                "message": message,
                "latency_ms": latency_ms,
            }
        )
        print(f"    -> {status}: {message[:180]}", flush=True)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = {
        "execution": str(execution["source_path"]),
        "model_id": model_id,
        "adb_device": device,
        "run_root": str(run_root),
        "started_task_count": len(rows),
        "status_counts": counts,
        "tasks": rows,
    }
    _write_json(run_root / "summary.json", summary)
    print(f"[done] {run_root}", flush=True)
    print(f"[summary] {counts}", flush=True)
    return 0 if counts.get("ERROR", 0) == 0 and counts.get("FAIL", 0) == 0 else 1


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Run Android task initializers only.")
    parser.add_argument("--execution", default=DEFAULT_EXECUTION)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--adb-device", default=None)
    args = parser.parse_args()
    return run_initializers(
        execution_path=args.execution,
        model_id=args.model_id,
        adb_device=args.adb_device,
    )


if __name__ == "__main__":
    raise SystemExit(main())
