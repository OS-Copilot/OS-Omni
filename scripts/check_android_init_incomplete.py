"""Run Android task initializers and verify raw init is not already complete."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.evaluation import EvalStatus
from core.init import InitStatus
from platforms.android.controller import AdbController
from platforms.android.core.types import load_task_from_file
from platforms.android.device_stability import wait_for_device_stable
from platforms.android.runners.evaluation import run_task_evaluation
from platforms.android.runners.initialization import run_task_initialization


def _load_task_paths(execution_path: Path) -> list[str]:
    payload = yaml.safe_load(execution_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list):
        raise ValueError(f"Execution file has no task list: {execution_path}")
    return [str(task) for task in tasks]


def _safe_summary(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    return dict(result.summary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execution",
        default="executions/android/android_changed_28_oracle_agent.yaml",
        help="Execution YAML containing Android task paths.",
    )
    parser.add_argument("--adb-device", default="emulator-5554")
    parser.add_argument("--model-id", default="init_incomplete_check")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    repo_root = Path.cwd()
    execution_path = (repo_root / args.execution).resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else repo_root / "results" / "init_check" / "android" / f"init_only_{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(output_dir / "run.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger("android_init_incomplete_check")

    controller = AdbController(adb_device=args.adb_device)
    stability = wait_for_device_stable(controller)
    health = controller.health()
    logger.info("Device stability: %s", stability)
    logger.info("Device health: %s", health)
    controller.disable_touch_debug_overlays()

    task_paths = _load_task_paths(execution_path)
    records: list[dict[str, Any]] = []
    problem_count = 0

    for index, task_rel in enumerate(task_paths, start=1):
        task_path = (repo_root / task_rel).resolve()
        task_run_dir = output_dir / f"{index:02d}_{task_path.stem}"
        task_run_dir.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "index": index,
            "task_file": task_rel,
            "task_run_dir": str(task_run_dir),
            "problems": [],
        }
        logger.info("[%d/%d] %s", index, len(task_paths), task_rel)

        try:
            task = load_task_from_file(str(task_path))
            record["task_id"] = task.id
            record["initializer_id"] = task.init.initializer_id if task.init else None
            record["evaluator_id"] = task.evaluation.evaluator_id if task.evaluation else None
        except Exception as exc:
            record["load_error"] = f"{type(exc).__name__}: {exc}"
            record["problems"].append("load_error")
            records.append(record)
            problem_count += 1
            logger.exception("Failed to load task: %s", task_rel)
            continue

        init_result = run_task_initialization(
            task=task,
            controller=controller,
            model_id=args.model_id,
            run_dir=task_run_dir,
            logger_obj=logger,
        )
        record["init"] = _safe_summary(init_result)
        if init_result is None:
            record["problems"].append("missing_initializer")
        elif init_result.result.status != InitStatus.PASS:
            record["problems"].append("init_not_pass")

        eval_result = run_task_evaluation(
            task=task,
            controller=controller,
            final_observation=None,
            model_id=args.model_id,
            run_dir=task_run_dir,
            logger_obj=logger,
        )
        record["post_init_evaluation"] = _safe_summary(eval_result)
        if eval_result is None:
            record["problems"].append("missing_evaluator")
        elif eval_result.result.status == EvalStatus.PASS:
            record["problems"].append("post_init_eval_pass")
        elif eval_result.result.status == EvalStatus.ERROR:
            record["problems"].append("post_init_eval_error")

        if record["problems"]:
            problem_count += 1
        records.append(record)

        (task_run_dir / "init_check_record.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    summary = {
        "execution": str(execution_path),
        "adb_device": args.adb_device,
        "model_id": args.model_id,
        "output_dir": str(output_dir),
        "task_count": len(records),
        "problem_count": problem_count,
        "records": records,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Summary saved to %s", output_dir / "summary.json")
    logger.info("Problems: %d/%d", problem_count, len(records))
    return 1 if problem_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
