#!/usr/bin/env python3
"""
Benchmark runner for Linux guest-runtime experiments.
"""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from platforms.linux.runners.base_benchmark import BaseBenchmarkRunner

from platforms.linux.core.types import load_task_from_file

LINUX_PLATFORM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
LINUX_BENCHMARK_OUTPUT_ROOT = str(REPO_ROOT / "results" / "linux")
INTERNAL_BENCHMARK_TASK_COMMAND = "__benchmark_task"
LINUX_OUTPUT_DIR_ENV = "LINUX_OUTPUT_DIR"

logger = logging.getLogger(__name__)


class LinuxBenchmarkRunner(BaseBenchmarkRunner):
    def __init__(self) -> None:
        super().__init__(logger)

    @staticmethod
    def _make_run_record(
        *,
        run_index: int,
        model: str,
        task_id: str,
        task_file: str,
        args,
        success: bool = False,
        return_code: Optional[int] = None,
        duration_seconds: float = 0.0,
        reset_ok: bool = True,
        reset_error: Optional[str] = None,
        trajectory_path: Optional[str] = None,
        result_path: Optional[str] = None,
        artifact_dir: Optional[Path | str] = None,
        runner_log_path: Optional[Path] = None,
        runtime_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "run_index": run_index,
            "model": model,
            "task_id": task_id,
            "task_file": task_file,
            "success": success,
            "return_code": return_code,
            "duration_seconds": round(duration_seconds, 2) if duration_seconds else 0.0,
            "reset_ok": reset_ok,
            "reset_error": reset_error,
            "mode": args.action_mode,
            "trajectory_path": trajectory_path,
            "result_path": result_path,
            "artifact_dir": str(artifact_dir) if artifact_dir else None,
            "runner_log": str(runner_log_path) if runner_log_path else None,
            "stdout_log": str(runner_log_path) if runner_log_path else None,
            "stderr_log": None,
            "runtime_url": runtime_url,
        }

    def _validate_and_get_models(self, args: Any) -> List[str]:
        if str(args.action_mode).strip() != "code_adapter":
            raise ValueError("--action-mode must be code_adapter")
        if not str(args.vm_ip).strip():
            raise ValueError("--vm-ip must be a non-empty string")
        if int(args.runtime_port) <= 0:
            raise ValueError("--runtime-port must be a positive integer")
        if not str(args.runtime_token).strip():
            raise ValueError("--runtime-token must be a non-empty string")
        raw_models = self.parse_csv_list(args.models)
        if not raw_models:
            raise ValueError("--models cannot be empty")
        return list(dict.fromkeys(raw_models))

    def _load_task_descriptor(self, args: Any) -> Dict[str, Any]:
        task_file = str(args.task_file)
        task = load_task_from_file(task_file)
        if not task.source_file:
            raise ValueError(f"Task file has no source path: {task_file}")
        return {
            "task_id": task.id,
            "task_goal": task.goal,
            "task_file": str(Path(task.source_file).resolve()),
        }

    def _build_benchmark_jobs(
        self,
        task: Dict[str, Any],
        models: List[str],
        args: Any,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "run_index": run_index,
                "model": model,
                "task_id": task["task_id"],
                "task_goal": task["task_goal"],
                "task_file": task["task_file"],
            }
            for run_index, model in enumerate(models, start=1)
        ]

    def _resolve_benchmark_name(self, args: Any) -> str:
        return self.safe_name(getattr(args, "benchmark_name", None) or "linux_benchmark")

    def _prepare_benchmark_dirs(
        self,
        *,
        args: Any,
        benchmark_name: str,
        timestamp: str,
    ) -> Tuple[Path, Path, Path]:
        output_root = Path(str(getattr(args, "output_root", LINUX_BENCHMARK_OUTPUT_ROOT)))
        benchmark_dir = output_root / f"{benchmark_name}_{timestamp}"
        run_root = benchmark_dir
        runner_log_path = benchmark_dir / "runner.log"
        benchmark_dir.mkdir(parents=True, exist_ok=True)
        run_root.mkdir(parents=True, exist_ok=True)
        return benchmark_dir, run_root, runner_log_path

    @staticmethod
    def _resolve_run_output_dir(run_root: Path, *, model: str, model_count: int) -> Path:
        if int(model_count) > 1:
            return run_root / BaseBenchmarkRunner.safe_name(model)
        return run_root

    def _log_benchmark_start(
        self,
        *,
        args: Any,
        benchmark_name: str,
        benchmark_dir: Path,
        run_root: Path,
        runner_log_path: Path,
        task: Dict[str, Any],
        models: List[str],
        jobs: List[Dict[str, Any]],
    ) -> None:
        logger.info("Benchmark Dir: %s", benchmark_dir)
        logger.info("Task: %s, Models: %s", task["task_id"], models)
        logger.info("Runtime: %s:%d", args.vm_ip, int(args.runtime_port))
        self.append_runner_log(
            runner_log_path,
            (
                f"# Benchmark: {benchmark_name}\n"
                f"# Created: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
                f"# Task id: {task['task_id']}\n"
                f"# Task file: {task['task_file']}\n"
                f"# Models: {','.join(models)}\n"
                f"# Runtime: {args.vm_ip}:{int(args.runtime_port)}\n"
            ),
        )

    def _resolve_cli_entry_path(self) -> str:
        return str(LINUX_PLATFORM_DIR / "cli.py")

    def _execute_single_run(
        self,
        *,
        args: Any,
        job: Dict[str, Any],
        cli_entry_path: str,
        run_root: Path,
        runner_log_path: Path,
    ) -> Dict[str, Any]:
        run_index = int(job["run_index"])
        model = str(job["model"])
        task_id = str(job["task_id"])
        task_file = str(job["task_file"])
        runtime_url = f"http://{args.vm_ip}:{int(args.runtime_port)}"

        model_count = len(self.parse_csv_list(args.models))
        model_output_dir = self._resolve_run_output_dir(run_root, model=model, model_count=model_count)
        model_output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 72)
        logger.info("[Run %d] model=%s task=%s", run_index, model, task_id)
        logger.info("=" * 72)
        self.append_runner_log(
            runner_log_path,
            (
                f"\n[Run {run_index}] model={model} task={task_id}\n"
                f"[Run {run_index}] task_file={task_file}\n"
                f"[Run {run_index}] runtime_url={runtime_url}"
            ),
        )

        cmd = [
            sys.executable,
            cli_entry_path,
            INTERNAL_BENCHMARK_TASK_COMMAND,
            "--task-file",
            task_file,
            "--model",
            model,
            "--action-mode",
            args.action_mode,
            "--observation-mode",
            str(getattr(args, "observation_mode", "screenshot_and_a11y_tree")),
            "--history-window",
            str(int(getattr(args, "history_window", 5))),
            "--vm-ip",
            str(args.vm_ip),
            "--runtime-port",
            str(int(args.runtime_port)),
            "--runtime-token",
            str(args.runtime_token),
        ]
        if getattr(args, "vm_guest_password", None):
            cmd.extend(["--vm-guest-password", str(args.vm_guest_password)])
        if getattr(args, "execution_file", None):
            cmd.extend(["--execution-file", str(args.execution_file)])
        if args.max_steps is not None:
            cmd.extend(["--max-steps", str(args.max_steps)])
        if args.timeout is not None:
            cmd.extend(["--timeout", str(args.timeout)])

        child_env = os.environ.copy()
        child_env[LINUX_OUTPUT_DIR_ENV] = str(model_output_dir)

        run_start = time.time()
        return_code = self.run_command_streaming(
            cmd,
            runner_log_path,
            run_prefix=f"Run {run_index}",
            env=child_env,
            child_log_mode="logger",
        )
        duration_seconds = time.time() - run_start

        artifact_paths = self.resolve_run_artifact_paths(model_output_dir)
        trajectory_path = artifact_paths["trajectory_path"]
        result_path = artifact_paths["result_path"]
        artifact_dir = artifact_paths["run_dir"]
        success = return_code == 0
        status = "SUCCESS" if success else "FAILED"
        logger.info("[Run %d] %s (%.1fs)", run_index, status, duration_seconds)

        self.append_runner_log(
            runner_log_path,
            (
                f"[Run {run_index}] status={status} duration={duration_seconds:.2f}s "
                f"trajectory={trajectory_path or ''} result={result_path or ''}"
            ),
        )

        return self._make_run_record(
            run_index=run_index,
            model=model,
            task_id=task_id,
            task_file=task_file,
            args=args,
            success=success,
            return_code=return_code,
            duration_seconds=duration_seconds,
            trajectory_path=trajectory_path,
            result_path=result_path,
            artifact_dir=artifact_dir,
            runner_log_path=runner_log_path,
            runtime_url=runtime_url,
        )

    def _build_exception_record(
        self,
        *,
        args: Any,
        job: Dict[str, Any],
        error: Exception,
        runner_log_path: Path,
    ) -> Dict[str, Any]:
        run_index = int(job.get("run_index", 0))
        model = str(job.get("model", ""))
        task_id = str(job.get("task_id", ""))
        task_file = str(job.get("task_file", ""))
        err_text = self.format_uncaught_error(error)
        logger.error("[Run %d] UNCAUGHT ERROR: %s", run_index, error)
        self.append_runner_log(runner_log_path, f"[Run {run_index}] uncaught_error={err_text}")
        return self._make_run_record(
            run_index=run_index,
            model=model,
            task_id=task_id,
            task_file=task_file,
            args=args,
            success=False,
            reset_ok=False,
            reset_error=str(error),
            runner_log_path=runner_log_path,
            runtime_url=f"http://{args.vm_ip}:{int(args.runtime_port)}",
        )

    def _log_completion(
        self,
        *,
        args: Any,
        run_records: List[Dict[str, Any]],
        runner_log_path: Path,
    ) -> None:
        total_runs = len(run_records)
        total_success = sum(1 for r in run_records if r["success"])
        logger.info("=" * 72)
        logger.info("BENCHMARK COMPLETE")
        if total_runs > 0:
            logger.info("Runs: %d, Success: %d, Rate: %.1f%%", total_runs, total_success, (total_success / total_runs) * 100.0)
        else:
            logger.info("Runs: 0")
        logger.info("Runner Log: %s", runner_log_path)
        logger.info("=" * 72)


def run_benchmark_command(args) -> int:
    return LinuxBenchmarkRunner().run(args)


__all__ = [
    "LINUX_BENCHMARK_OUTPUT_ROOT",
    "run_benchmark_command",
]
