#!/usr/bin/env python3
"""
iOS platform entrypoint.
Public input is execution + iOS runtime config.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Ensure repository root is importable when executed as a script.
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv not installed, environment variables must be set directly

IOS_DEFAULT_RUNTIME_CONFIG = repo_root / "configs" / "ios.yaml"
IOS_RESULTS_ROOT = repo_root / "results"
INTERNAL_BENCHMARK_JOB_COMMAND = "__benchmark_job"

logger = logging.getLogger(__name__)


def _build_execution_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="iOS execution runner (execution-driven input).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m platforms.ios.cli --execution executions/ios/ios_test_1.yaml
        """,
    )
    parser.add_argument(
        "--execution",
        required=True,
        help="Path to execution YAML file.",
    )
    return parser


def _build_internal_job_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal iOS benchmark job command.")
    parser.add_argument("--task-file", required=True, type=str)
    parser.add_argument("--execution-file", type=str, default=None)
    parser.add_argument("--model", required=True, type=str)
    parser.add_argument(
        "--action-mode",
        type=str,
        default="code_adapter",
        choices=["code_adapter"],
    )
    parser.add_argument("--observation-mode", type=str, default="screenshot_and_a11y_tree")
    parser.add_argument("--history-window", type=int, default=3)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--udid", required=True, type=str)
    parser.add_argument("--appium-host", type=str, default="127.0.0.1")
    parser.add_argument("--appium-port", type=int, default=4723)
    return parser


def _run_job_command(args):
    from platforms.ios.runners.episode import run_benchmark_job_command

    return run_benchmark_job_command(args)


def _run_benchmark_command(args):
    from platforms.ios.runners.benchmark import run_benchmark_command

    return run_benchmark_command(args)


def _normalize_action_mode(action_mode_raw: str | None) -> str:
    if not action_mode_raw:
        return "code_adapter"
    normalized = action_mode_raw.strip().lower()
    if normalized != "code_adapter":
        raise ValueError(
            "execution.action_mode only supports code_adapter for iOS."
        )
    return normalized


def _safe_name(raw: str) -> str:
    text = (raw or "").strip() or "unnamed"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text)


def _normalize_observation_mode(observation_mode_raw: str | None) -> str:
    if not observation_mode_raw:
        return "screenshot_and_a11y_tree"
    normalized = observation_mode_raw.strip().lower()
    mapping = {
        "screenshot_only": "screenshot_only",
        "a11y_tree_only": "a11y_tree_only",
        "screenshot_and_a11y_tree": "screenshot_and_a11y_tree",
    }
    observation_mode = mapping.get(normalized)
    if not observation_mode:
        raise ValueError(
            "execution.observation_mode only supports screenshot_only/a11y_tree_only/screenshot_and_a11y_tree for iOS."
        )
    return observation_mode


def _normalize_history_window(history_window_raw: object) -> int:
    if history_window_raw is None:
        return 3
    if isinstance(history_window_raw, bool) or not isinstance(history_window_raw, int) or history_window_raw <= 0:
        raise ValueError("execution.history_window must be a positive integer for iOS.")
    return int(history_window_raw)


def _resolve_execution_base_name(execution_path: Path) -> str:
    return _safe_name(execution_path.stem)


def _resolve_model_results_root(model_id: str) -> Path:
    return IOS_RESULTS_ROOT / _safe_name(model_id) / "ios"


def _resolve_task_benchmark_label(task_path: Path) -> str:
    with task_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"Task file is missing task_id: {task_path}")
    return task_id.strip()


def _run_execution_command(args: argparse.Namespace) -> int:
    from platforms.ios.runtime_config import load_execution_handoff, load_ios_runtime_config

    execution = load_execution_handoff(args.execution)
    runtime_config = load_ios_runtime_config()
    clone_source_udid = runtime_config.source_simulator_udid

    action_mode = _normalize_action_mode(execution.get("action_mode"))
    observation_mode = _normalize_observation_mode(execution.get("observation_mode"))
    history_window = _normalize_history_window(execution.get("history_window"))
    model_ids = list(dict.fromkeys(execution.get("models", [])))
    if not model_ids:
        raise ValueError("execution.models cannot be empty for iOS.")
    execution_base_name = _resolve_execution_base_name(execution["source_path"])
    task_paths = execution.get("task_paths", [])
    execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    task_count = len(task_paths)
    logger.info("Execution: %s", execution["source_path"])
    logger.info(
        "Tasks: %d, Models: %d",
        task_count,
        len(model_ids),
    )
    logger.info("Config: %s", IOS_DEFAULT_RUNTIME_CONFIG)
    logger.info("Appium: %s:%d", runtime_config.appium_host, runtime_config.appium_port)
    logger.info("Result Root: %s", IOS_RESULTS_ROOT)

    failed_tasks: list[str] = []
    for model_index, model_id in enumerate(model_ids, start=1):
        execution_run_dir = _resolve_model_results_root(model_id) / (
            f"{execution_base_name}_{execution_timestamp}"
        )
        execution_run_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Execution output dir %d/%d for model %s: %s",
            model_index,
            len(model_ids),
            model_id,
            execution_run_dir,
        )

        dedupe_counter: dict[str, int] = {}
        for task_index, task_path in enumerate(task_paths, start=1):
            base_name = _resolve_task_benchmark_label(task_path)
            dedupe_counter[base_name] = dedupe_counter.get(base_name, 0) + 1
            suffix = dedupe_counter[base_name]
            benchmark_name = base_name if suffix == 1 else f"{base_name}_{suffix}"
            bench_args = argparse.Namespace(
                task_file=str(task_path),
                execution_file=str(execution["source_path"]),
                models=model_id,
                benchmark_name=benchmark_name,
                output_root=str(execution_run_dir),
                action_mode=action_mode,
                observation_mode=observation_mode,
                history_window=history_window,
                max_steps=None,
                timeout=None,
                clone_source_udid=clone_source_udid,
                appium_host=runtime_config.appium_host,
                appium_port=runtime_config.appium_port,
            )
            logger.info(
                "Benchmark job %d/%d for model %s: %s",
                task_index,
                task_count,
                model_id,
                task_path,
            )
            exit_code = _run_benchmark_command(bench_args)
            if exit_code != 0:
                failed_tasks.append(f"{model_id}:{task_path}")
                logger.error(
                    "Task benchmark failed for model %s: %s",
                    model_id,
                    task_path,
                )
    if failed_tasks:
        logger.error(
            "Execution finished with failed task benchmarks: %s",
            ", ".join(failed_tasks),
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == INTERNAL_BENCHMARK_JOB_COMMAND:
        args = _build_internal_job_parser().parse_args(argv[1:])
        return _run_job_command(args)

    args = _build_execution_parser().parse_args(argv)
    try:
        return _run_execution_command(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
