#!/usr/bin/env python3
"""
macOS platform entrypoint.
Public input is execution + macOS runtime config.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Ensure repository root wins over the script directory when executed as a
# file path.  This avoids the platform-local `platforms/macos/host/core` package
# shadowing the repository-level `core` package in subprocess benchmark runs.
repo_root = Path(__file__).resolve().parents[3]
host_dir = Path(__file__).resolve().parent
sys.path[:] = [
    entry
    for entry in sys.path
    if not entry or Path(entry).resolve() != host_dir
]
if str(repo_root) in sys.path:
    sys.path.remove(str(repo_root))
sys.path.insert(0, str(repo_root))

from core.benchmark_policy import DEFAULT_PROMPT_PROFILE, normalize_prompt_profile  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv not installed, environment variables must be set directly

MACOS_RUNTIME_CONFIG_PATH = repo_root / "configs" / "macos.yaml"
INTERNAL_BENCHMARK_TASK_COMMAND = "__benchmark_task"

logger = logging.getLogger(__name__)


def _build_execution_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="macOS execution runner (execution-driven input).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m platforms.macos.host.cli --execution executions/macos/macos_test_1.yaml
        """,
    )
    parser.add_argument(
        "--execution",
        required=True,
        help="Path to execution YAML file.",
    )
    return parser


def _build_internal_benchmark_task_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal macOS benchmark task worker command.")
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
    parser.add_argument(
        "--prompt-profile",
        type=str,
        default=DEFAULT_PROMPT_PROFILE,
        choices=["benchmark", "debug"],
    )
    parser.add_argument("--history-window", type=int, default=3)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--vm-ip", required=True, type=str)
    parser.add_argument("--runtime-port", type=int, required=True)
    parser.add_argument("--vm-token", type=str, required=True)
    parser.add_argument("--base-vm-name", type=str, default=None)
    parser.add_argument("--vm-provider", type=str, default="tart")
    parser.add_argument("--tart-home", type=str, default=None)
    return parser


def _run_benchmark_task_command(args):
    from platforms.macos.host.runners.episode import run_benchmark_task_command

    return run_benchmark_task_command(args)


def _run_benchmark_command(args):
    from platforms.macos.host.runners.benchmark import run_benchmark_command

    return run_benchmark_command(args)


def _normalize_action_mode(action_mode_raw: str | None) -> str:
    if not action_mode_raw:
        return "code_adapter"
    normalized = action_mode_raw.strip().lower()
    if normalized != "code_adapter":
        raise ValueError(
            "execution.action_mode only supports code_adapter for macOS."
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
            "execution.observation_mode only supports screenshot_only/a11y_tree_only/screenshot_and_a11y_tree for macOS."
        )
    return observation_mode


def _normalize_history_window(history_window_raw: object) -> int:
    if history_window_raw is None:
        return 3
    if isinstance(history_window_raw, bool) or not isinstance(history_window_raw, int) or history_window_raw <= 0:
        raise ValueError("execution.history_window must be a positive integer for macOS.")
    return int(history_window_raw)


def _resolve_execution_base_name(execution_path: Path) -> str:
    return _safe_name(execution_path.stem)


def _resolve_model_results_root(model_id: str) -> Path:
    return repo_root / "results" / _safe_name(model_id) / "macos"


def _resolve_task_label(task_path: Path) -> str:
    with task_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"Task file is missing task_id: {task_path}")
    return task_id.strip()


def _run_execution_command(args: argparse.Namespace) -> int:
    from platforms.macos.runtime_config import load_execution_handoff, load_macos_runtime_config

    execution = load_execution_handoff(args.execution)
    runtime_config = load_macos_runtime_config(MACOS_RUNTIME_CONFIG_PATH)
    action_mode = _normalize_action_mode(execution.get("action_mode"))
    observation_mode = _normalize_observation_mode(execution.get("observation_mode"))
    history_window = _normalize_history_window(execution.get("history_window"))
    prompt_profile = normalize_prompt_profile(
        (execution.get("metadata") or {}).get("prompt_profile", DEFAULT_PROMPT_PROFILE)
    )
    model_ids = list(dict.fromkeys(execution.get("models", [])))
    if not model_ids:
        raise ValueError("execution.models cannot be empty for macOS.")
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
    logger.info("Prompt Profile: %s", prompt_profile)
    logger.info("Config: %s", MACOS_RUNTIME_CONFIG_PATH)
    logger.info("Runtime: %s:%d", runtime_config.vm_ip, runtime_config.runtime_port)

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
        for task_path in task_paths:
            task_label = _resolve_task_label(task_path)
            dedupe_counter[task_label] = dedupe_counter.get(task_label, 0) + 1
            suffix = dedupe_counter[task_label]
            benchmark_name = task_label if suffix == 1 else f"{task_label}_{suffix}"
            bench_args = argparse.Namespace(
                task_file=str(task_path),
                execution_file=str(execution["source_path"]),
                models=model_id,
                benchmark_name=benchmark_name,
                output_root=str(execution_run_dir),
                action_mode=action_mode,
                observation_mode=observation_mode,
                history_window=history_window,
                prompt_profile=prompt_profile,
                max_steps=None,
                timeout=None,
                vm_ip=runtime_config.vm_ip,
                runtime_port=runtime_config.runtime_port,
                vm_token=runtime_config.vm_token,
                base_vm_name=runtime_config.base_vm_name,
                vm_provider=runtime_config.vm_provider,
                tart_home=runtime_config.tart_home,
            )
            logger.info("Running task benchmark for model %s: %s", model_id, task_path)
            exit_code = _run_benchmark_command(bench_args)
            if exit_code != 0:
                failed_tasks.append(f"{model_id}:{task_path}")

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
