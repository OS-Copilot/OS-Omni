#!/usr/bin/env python3
"""
Linux platform entrypoint.
Public input is execution + Linux runtime config.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from platforms.linux.core.types import load_task_from_file  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

LINUX_RUNTIME_CONFIG_PATH = repo_root / "configs" / "linux.yaml"
INTERNAL_BENCHMARK_TASK_COMMAND = "__benchmark_task"

logger = logging.getLogger(__name__)


def _build_execution_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Linux execution runner (execution-driven input).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--execution", required=True, help="Path to execution YAML file.")
    return parser


def _build_internal_benchmark_task_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal Linux benchmark task worker command.")
    parser.add_argument("--task-file", required=True, type=str)
    parser.add_argument("--execution-file", type=str, default=None)
    parser.add_argument("--model", required=True, type=str)
    parser.add_argument(
        "--action-mode",
        type=str,
        default="code_adapter",
        choices=["code_adapter"],
    )
    parser.add_argument("--observation-mode", type=str, default="screenshot_only")
    parser.add_argument("--history-window", type=int, default=3)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--vm-ip", required=True, type=str)
    parser.add_argument("--runtime-port", required=True, type=int)
    parser.add_argument("--runtime-token", required=True, type=str)
    parser.add_argument("--vm-guest-password", type=str, default=None)
    return parser


def _run_benchmark_task_command(args):
    from platforms.linux.runners.episode import run_benchmark_task_command

    return run_benchmark_task_command(args)


def _run_benchmark_command(args):
    from platforms.linux.runners.benchmark import run_benchmark_command

    return run_benchmark_command(args)


def _normalize_action_mode(action_mode_raw: str | None) -> str:
    if not action_mode_raw:
        return "code_adapter"
    normalized = action_mode_raw.strip().lower()
    if normalized != "code_adapter":
        raise ValueError(
            "execution.action_mode only supports code_adapter for Linux."
        )
    return normalized


def _safe_name(raw: str) -> str:
    text = (raw or "").strip() or "unnamed"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text)


def _normalize_observation_mode(observation_mode_raw: str | None) -> str:
    if not observation_mode_raw:
        return "screenshot_only"
    normalized = observation_mode_raw.strip().lower()
    mapping = {
        "screenshot_only": "screenshot_only",
        "a11y_tree_only": "a11y_tree_only",
        "screenshot_and_a11y_tree": "screenshot_and_a11y_tree",
    }
    observation_mode = mapping.get(normalized)
    if not observation_mode:
        raise ValueError(
            "execution.observation_mode only supports screenshot_only/a11y_tree_only/screenshot_and_a11y_tree for Linux."
        )
    return observation_mode


def _normalize_history_window(history_window_raw: object) -> int:
    if history_window_raw is None:
        return 3
    if isinstance(history_window_raw, bool) or not isinstance(history_window_raw, int) or history_window_raw <= 0:
        raise ValueError("execution.history_window must be a positive integer for Linux.")
    return int(history_window_raw)


def _normalize_optional_positive_int(value_raw: object, *, field_name: str) -> int | None:
    if value_raw is None:
        return None
    if isinstance(value_raw, bool) or not isinstance(value_raw, int) or value_raw <= 0:
        raise ValueError(f"execution.{field_name} must be a positive integer for Linux when provided.")
    return int(value_raw)


def _resolve_execution_base_name(execution_path: Path) -> str:
    return _safe_name(execution_path.stem)


def _resolve_model_results_root(model_id: str) -> Path:
    return repo_root / "results" / _safe_name(model_id) / "linux"


def _resolve_task_label(task_path: Path) -> str:
    with task_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"Task file is missing task_id: {task_path}")
    return task_id.strip()


def _validate_reused_vm_tasks(task_paths: list[Path]) -> None:
    missing_initializer: list[str] = []
    for task_path in task_paths:
        task = load_task_from_file(str(task_path))
        if task.init is None:
            missing_initializer.append(task.id)
    if missing_initializer:
        joined = ", ".join(missing_initializer)
        raise ValueError(
            "execution.reuse_vm_session requires every task to define an initializer so task state can be rebuilt "
            f"without a VM reboot. Missing init for: {joined}"
        )


def _close_vm_session(vm_session, *, task_path: Path | None = None) -> list[str]:
    failed_tasks: list[str] = []
    if vm_session is None:
        return failed_tasks
    try:
        vm_session.close()
    except Exception as exc:
        label = str(task_path) if task_path is not None else "execution"
        logger.error("Failed to close Linux VM session for %s: %s", label, exc)
        failed_tasks.append(f"{label}:vm_cleanup")
    return failed_tasks


def _run_execution_command(args: argparse.Namespace) -> int:
    from platforms.linux.runtime_config import load_execution_handoff, load_linux_runtime_config
    from platforms.linux.runtime_env.vm_manager import start_linux_vm_session

    execution = load_execution_handoff(args.execution)
    runtime_config = load_linux_runtime_config(LINUX_RUNTIME_CONFIG_PATH)
    action_mode = _normalize_action_mode(execution.get("action_mode"))
    observation_mode = _normalize_observation_mode(execution.get("observation_mode"))
    history_window = _normalize_history_window(execution.get("history_window"))
    max_steps = _normalize_optional_positive_int(execution.get("max_steps"), field_name="max_steps")
    timeout = _normalize_optional_positive_int(execution.get("timeout"), field_name="timeout")
    model_ids = list(dict.fromkeys(execution.get("models", [])))
    if not model_ids:
        raise ValueError("execution.models cannot be empty for Linux.")
    execution_base_name = _resolve_execution_base_name(execution["source_path"])
    task_paths = execution.get("task_paths", [])
    reuse_vm_session = bool(execution.get("reuse_vm_session", False))
    execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if reuse_vm_session:
        _validate_reused_vm_tasks(task_paths)

    logger.info("Execution: %s", execution["source_path"])
    logger.info("Tasks: %d, Models: %d", len(task_paths), len(model_ids))
    logger.info("Config: %s", LINUX_RUNTIME_CONFIG_PATH)
    logger.info("Runtime: %s:%d", runtime_config.vm_ip, runtime_config.runtime_port)
    if runtime_config.vm_guest_password:
        logger.info("Guest password: configured")
    logger.info(
        "VM Session Mode: %s",
        "reuse_per_execution" if reuse_vm_session else "fresh_session_per_task",
    )

    failed_tasks: list[str] = []
    for model_id in model_ids:
        execution_run_dir = _resolve_model_results_root(model_id) / f"{execution_base_name}_{execution_timestamp}"
        execution_run_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Execution output dir for model %s: %s", model_id, execution_run_dir)

        shared_vm_session = None
        shared_runtime_host = runtime_config.vm_ip
        if reuse_vm_session:
            shared_vm_session = start_linux_vm_session(runtime_config, logger_obj=logger)
            if shared_vm_session is not None:
                shared_runtime_host = shared_vm_session.runtime_host

        dedupe_counter: dict[str, int] = {}
        try:
            for task_path in task_paths:
                task_label = _resolve_task_label(task_path)
                dedupe_counter[task_label] = dedupe_counter.get(task_label, 0) + 1
                suffix = dedupe_counter[task_label]
                benchmark_name = task_label if suffix == 1 else f"{task_label}_{suffix}"
                vm_session = shared_vm_session
                runtime_host = shared_runtime_host
                if not reuse_vm_session:
                    vm_session = start_linux_vm_session(runtime_config, logger_obj=logger)
                    runtime_host = vm_session.runtime_host if vm_session is not None else runtime_config.vm_ip
                try:
                    bench_args = argparse.Namespace(
                        task_file=str(task_path),
                        execution_file=str(execution["source_path"]),
                        models=model_id,
                        benchmark_name=benchmark_name,
                        output_root=str(execution_run_dir),
                        action_mode=action_mode,
                        observation_mode=observation_mode,
                        history_window=history_window,
                        max_steps=max_steps,
                        timeout=timeout,
                        vm_ip=runtime_host,
                        runtime_port=runtime_config.runtime_port,
                        runtime_token=runtime_config.runtime_token,
                        vm_guest_password=runtime_config.vm_guest_password,
                    )
                    logger.info("Running task benchmark for model %s: %s", model_id, task_path)
                    exit_code = _run_benchmark_command(bench_args)
                    if exit_code != 0:
                        failed_tasks.append(f"{model_id}:{task_path}")
                finally:
                    if not reuse_vm_session:
                        failed_tasks.extend(
                            f"{model_id}:{suffix}"
                            for suffix in _close_vm_session(vm_session, task_path=task_path)
                        )
        finally:
            if reuse_vm_session:
                failed_tasks.extend(
                    f"{model_id}:{suffix}"
                    for suffix in _close_vm_session(shared_vm_session)
                )

    if failed_tasks:
        logger.error("Execution finished with failed task benchmarks: %s", ", ".join(failed_tasks))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == INTERNAL_BENCHMARK_TASK_COMMAND:
        args = _build_internal_benchmark_task_parser().parse_args(argv[1:])
        return _run_benchmark_task_command(args)

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
