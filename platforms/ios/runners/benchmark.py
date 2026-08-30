#!/usr/bin/env python3
"""
Benchmark runner for serial clone -> run -> delete experiments.
"""

import logging
import os
import sys
import time
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from platforms.ios.runners.base_benchmark import BaseBenchmarkRunner

from platforms.ios.runtime_env.simulator_manager import (
    boot_simulator,
    clone_simulator,
    delete_simulator,
    find_simulator_udid_by_name,
    shutdown_simulator,
    shutdown_simulator_and_wait,
    simctl_udid_exists,
)

IOS_PLATFORM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
IOS_DEFAULT_BENCHMARK_DIR = str(REPO_ROOT / "results" / "ios")
INTERNAL_BENCHMARK_JOB_COMMAND = "__benchmark_job"
BENCHMARK_POST_RESET_WAIT_SECONDS = 1.5
BENCHMARK_CLONE_MAX_ATTEMPTS = 2
BENCHMARK_CLONE_RETRY_WAIT_SECONDS = 2.0
BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS = 30.0

logger = logging.getLogger(__name__)


class IOSBenchmarkRunner(BaseBenchmarkRunner):
    def __init__(self) -> None:
        super().__init__(logger)

    @staticmethod
    def _build_clone_name(run_index: int, model: str, task_id: str) -> str:
        timestamp_ms = int(time.time() * 1000)
        safe_model = BaseBenchmarkRunner.safe_name(model)
        safe_task = BaseBenchmarkRunner.safe_name(task_id)
        return f"{run_index:04d}_{safe_model}_{safe_task}_{timestamp_ms}"

    @staticmethod
    def _make_run_record(
        *,
        run_index,
        model,
        task_id,
        task_file,
        args,
        success=False,
        return_code=None,
        duration_seconds=0.0,
        reset_ok=True,
        reset_error=None,
        trajectory_path=None,
        result_path=None,
        artifact_dir=None,
        runner_log_path=None,
        run_udid=None,
        clone_udid=None,
        clone_kept=False,
        cleanup_error=None,
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
            "run_udid": run_udid,
            "clone_udid": clone_udid,
            "clone_kept": clone_kept,
            "cleanup_error": cleanup_error,
        }

    @staticmethod
    def _run_reset(
        args,
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Reset environment before one benchmark run.

        Returns:
            (ok, error, run_udid, ephemeral_udid)
            - run_udid: udid for the child run
            - ephemeral_udid: temporary cloned simulator udid, caller should cleanup
        """
        run_index = context.get("run_index", "?")
        reset_label = f"[Run {run_index}][reset]"
        reset_start = time.time()

        clone_source_udid = context.get("clone_source_udid") or args.clone_source_udid
        if not clone_source_udid:
            return False, "--clone-source-udid is required", None, None
        if not simctl_udid_exists(clone_source_udid):
            return False, f"Clone source UDID not found: {clone_source_udid}", None, None

        source_shutdown_start = time.time()
        logger.info(
            "%s source shutdown wait start (timeout=%.1fs, source=%s)",
            reset_label,
            BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS,
            clone_source_udid,
        )
        if not shutdown_simulator_and_wait(
            clone_source_udid,
            timeout_seconds=BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS,
        ):
            return (
                False,
                (
                    f"Source simulator did not reach Shutdown state before clone "
                    f"(udid={clone_source_udid})"
                ),
                None,
                None,
            )
        logger.info(
            "%s source shutdown wait done (%.1fs)",
            reset_label,
            time.time() - source_shutdown_start,
        )

        clone_name = context.get("clone_name") or f"{run_index:04d}_{int(time.time() * 1000)}"
        clone_udid: Optional[str] = None
        last_error: Optional[Exception] = None
        for attempt in range(1, BENCHMARK_CLONE_MAX_ATTEMPTS + 1):
            attempt_start = time.time()
            logger.info(
                "%s clone attempt %d/%d start (name=%s)",
                reset_label,
                attempt,
                BENCHMARK_CLONE_MAX_ATTEMPTS,
                clone_name,
            )
            try:
                clone_create_start = time.time()
                clone_udid = clone_simulator(clone_source_udid, clone_name)
                logger.info(
                    "%s clone created (udid=%s, %.1fs)",
                    reset_label,
                    clone_udid,
                    time.time() - clone_create_start,
                )

                clone_shutdown_start = time.time()
                logger.info(
                    "%s clone shutdown wait start (udid=%s, timeout=10.0s)",
                    reset_label,
                    clone_udid,
                )
                shutdown_simulator_and_wait(clone_udid, timeout_seconds=10.0)
                logger.info(
                    "%s clone shutdown wait done (%.1fs)",
                    reset_label,
                    time.time() - clone_shutdown_start,
                )

                boot_start = time.time()
                logger.info("%s boot start (udid=%s)", reset_label, clone_udid)
                boot_simulator(clone_udid)
                logger.info(
                    "%s boot ready (%.1fs)",
                    reset_label,
                    time.time() - boot_start,
                )
                logger.info(
                    "%s clone attempt %d/%d done (%.1fs)",
                    reset_label,
                    attempt,
                    BENCHMARK_CLONE_MAX_ATTEMPTS,
                    time.time() - attempt_start,
                )
                last_error = None
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    "[Run %s] clone/reset attempt %d/%d failed: %s",
                    run_index,
                    attempt,
                    BENCHMARK_CLONE_MAX_ATTEMPTS,
                    e,
                )

                orphan_udid = clone_udid or find_simulator_udid_by_name(clone_name)
                if orphan_udid:
                    try:
                        shutdown_simulator(orphan_udid)
                    except Exception:
                        pass
                    try:
                        delete_simulator(orphan_udid)
                    except Exception:
                        pass
                    clone_udid = None

                if attempt < BENCHMARK_CLONE_MAX_ATTEMPTS:
                    logger.info(
                        "%s retrying after %.1fs",
                        reset_label,
                        BENCHMARK_CLONE_RETRY_WAIT_SECONDS,
                    )
                    time.sleep(BENCHMARK_CLONE_RETRY_WAIT_SECONDS)
                    logger.info(
                        "%s source shutdown wait before retry (timeout=%.1fs, source=%s)",
                        reset_label,
                        BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS,
                        clone_source_udid,
                    )
                    shutdown_simulator_and_wait(
                        clone_source_udid,
                        timeout_seconds=BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS,
                    )

        if last_error is not None:
            return (
                False,
                (
                    f"simctl clone/reset failed after {BENCHMARK_CLONE_MAX_ATTEMPTS} attempts "
                    f"(source={clone_source_udid}, name={clone_name}): {last_error}"
                ),
                clone_udid,
                clone_udid,
            )

        if BENCHMARK_POST_RESET_WAIT_SECONDS > 0:
            logger.info(
                "%s settle wait start (%.1fs)",
                reset_label,
                BENCHMARK_POST_RESET_WAIT_SECONDS,
            )
            time.sleep(BENCHMARK_POST_RESET_WAIT_SECONDS)
            logger.info("%s settle wait done", reset_label)

        logger.info("%s completed (%.1fs)", reset_label, time.time() - reset_start)

        return True, None, clone_udid, clone_udid

    @staticmethod
    def _cleanup_ephemeral_simulator(udid: str) -> Tuple[bool, Optional[str]]:
        if not udid:
            return True, None

        try:
            shutdown_simulator(udid)
        except Exception:
            pass

        try:
            delete_simulator(udid)
            return True, None
        except Exception as e:
            return False, f"simctl delete failed for {udid}: {e}"

    def _validate_and_get_models(self, args: Any) -> List[str]:
        if str(args.action_mode).strip() != "code_adapter":
            raise ValueError("--action-mode must be code_adapter")
        if not args.clone_source_udid:
            raise ValueError("--clone-source-udid is required")
        if not str(args.appium_host).strip():
            raise ValueError("--appium-host must be a non-empty string")
        if int(args.appium_port) <= 0:
            raise ValueError("--appium-port must be a positive integer")

        raw_models = self.parse_csv_list(args.models)
        if not raw_models:
            raise ValueError("--models cannot be empty")
        return list(dict.fromkeys(raw_models))

    def _load_task_descriptor(self, args: Any) -> Dict[str, Any]:
        from platforms.ios.core.types import load_task_from_file

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
        jobs: List[Dict[str, Any]] = []
        for run_index, model in enumerate(models, start=1):
            jobs.append(
                {
                    "run_index": run_index,
                    "model": model,
                    "task_id": task["task_id"],
                    "task_goal": task["task_goal"],
                    "task_file": task["task_file"],
                }
            )
        return jobs

    def _resolve_benchmark_name(self, args: Any) -> str:
        return self.safe_name(getattr(args, "benchmark_name", None) or "benchmark")

    def _prepare_benchmark_dirs(
        self,
        *,
        args: Any,
        benchmark_name: str,
        timestamp: str,
    ) -> Tuple[Path, Path, Path]:
        benchmark_dir = Path(args.output_root) / f"{benchmark_name}_{timestamp}"
        run_root = benchmark_dir
        runner_log_path = benchmark_dir / "runner.log"
        benchmark_dir.mkdir(parents=True, exist_ok=True)
        run_root.mkdir(parents=True, exist_ok=True)
        return benchmark_dir, run_root, runner_log_path

    @staticmethod
    def _resolve_run_output_dir(
        run_root: Path,
        *,
        model: str,
        model_count: int,
    ) -> Path:
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
        logger.info("Clone Source UDID: %s", args.clone_source_udid)
        logger.info("Appium Host: %s", str(args.appium_host).strip())
        logger.info("Appium Port: %d", int(args.appium_port))
        self.append_runner_log(
            runner_log_path,
            (
                f"# Benchmark: {benchmark_name}\n"
                f"# Created: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
                f"# Task count: 1\n"
                f"# Task id: {task['task_id']}\n"
                f"# Models: {','.join(models)}\n"
                f"# Clone source udid: {args.clone_source_udid}\n"
                f"# Appium host: {str(args.appium_host).strip()}\n"
                f"# Appium port: {int(args.appium_port)}\n"
            ),
        )

    def _resolve_cli_entry_path(self) -> str:
        return str(IOS_PLATFORM_DIR / "cli.py")

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
        model_count = len(self.parse_csv_list(args.models))
        model_output_dir = self._resolve_run_output_dir(
            run_root,
            model=model,
            model_count=model_count,
        )
        model_output_dir.mkdir(parents=True, exist_ok=True)

        clone_name = self._build_clone_name(run_index, model, task_id)
        context = {
            "model": model,
            "task_id": task_id,
            "task_file": task_file,
            "run_index": run_index,
            "clone_source_udid": args.clone_source_udid,
            "clone_name": clone_name,
        }

        print("\n" + "=" * 72)
        logger.info("[Run %d] model=%s task=%s", run_index, model, task_id)
        print("=" * 72)
        self.append_runner_log(
            runner_log_path,
            (
                f"\n[Run {run_index}] model={model} task={task_id}\n"
                f"[Run {run_index}] task_file={task_file}"
            ),
        )

        ephemeral_udid: Optional[str] = None
        cleanup_error: Optional[str] = None
        record: Optional[Dict[str, Any]] = None
        try:
            reset_ok, reset_error, run_udid, ephemeral_udid = self._run_reset(args, context)
            if not reset_ok:
                logger.error("[Run %d] reset failed: %s", run_index, reset_error)
                self.append_runner_log(
                    runner_log_path,
                    f"[Run {run_index}] reset_failed={reset_error}",
                )
                record = self._make_run_record(
                    run_index=run_index,
                    model=model,
                    task_id=task_id,
                    task_file=task_file,
                    args=args,
                    success=False,
                    reset_ok=False,
                    reset_error=reset_error,
                    runner_log_path=runner_log_path,
                    artifact_dir=model_output_dir,
                    run_udid=run_udid,
                    clone_udid=ephemeral_udid,
                )
                return record

            cmd = [
                sys.executable,
                cli_entry_path,
                INTERNAL_BENCHMARK_JOB_COMMAND,
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
                "--appium-host",
                str(args.appium_host).strip(),
                "--appium-port",
                str(args.appium_port),
            ]
            if getattr(args, "execution_file", None):
                cmd.extend(["--execution-file", str(args.execution_file)])
            if args.max_steps is not None:
                cmd.extend(["--max-steps", str(args.max_steps)])
            if args.timeout is not None:
                cmd.extend(["--timeout", str(args.timeout)])
            if run_udid:
                cmd.extend(["--udid", str(run_udid)])
            child_env = os.environ.copy()
            child_env["IOSWORLD_OUTPUT_DIR"] = str(model_output_dir)

            logger.info("[Run %d] device=%s", run_index, run_udid or "default")
            self.append_runner_log(
                runner_log_path,
                f"[Run {run_index}] device={run_udid or 'default'}",
            )
            run_start = time.time()
            return_code = self.run_command_streaming(
                cmd,
                runner_log_path,
                run_prefix=f"Run {run_index}",
                env=child_env,
                child_log_mode="print",
            )
            duration_seconds = time.time() - run_start

            artifact_paths = self.resolve_run_artifact_paths(model_output_dir)
            trajectory_path = artifact_paths["trajectory_path"]
            result_path = artifact_paths["result_path"]
            artifact_dir = artifact_paths["run_dir"]
            success = return_code == 0
            status = "SUCCESS" if success else "FAILED"
            logger.info("[Run %d] %s (%.1fs)", run_index, status, duration_seconds)
            if trajectory_path:
                logger.info("[Run %d] Trajectory: %s", run_index, trajectory_path)
            if result_path:
                logger.info("[Run %d] Result: %s", run_index, result_path)

            self.append_runner_log(
                runner_log_path,
                (
                    f"[Run {run_index}] status={status} duration={duration_seconds:.2f}s "
                    f"trajectory={trajectory_path or ''} result={result_path or ''}"
                ),
            )

            record = self._make_run_record(
                run_index=run_index,
                model=model,
                task_id=task_id,
                task_file=task_file,
                args=args,
                success=success,
                return_code=return_code,
                duration_seconds=duration_seconds,
                reset_ok=True,
                trajectory_path=trajectory_path,
                result_path=result_path,
                artifact_dir=artifact_dir,
                runner_log_path=runner_log_path,
                run_udid=run_udid,
                clone_udid=ephemeral_udid,
            )
            return record
        finally:
            if ephemeral_udid:
                _, cleanup_error = self._cleanup_ephemeral_simulator(ephemeral_udid)
                if cleanup_error:
                    logger.warning("[Run %d] clone cleanup warning: %s", run_index, cleanup_error)
                self.append_runner_log(
                    runner_log_path,
                    f"[Run {run_index}] cleanup_error={cleanup_error or ''}",
                )
            if record is not None:
                record["cleanup_error"] = cleanup_error

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
        self.append_runner_log(
            runner_log_path,
            f"[Run {run_index}] uncaught_error={err_text}",
        )
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
        print("\n" + "=" * 72)
        print("BENCHMARK COMPLETE")
        if total_runs > 0:
            print(f"Runs: {total_runs}, Success: {total_success}, Rate: {total_success / total_runs:.1%}")
        else:
            print("Runs: 0")
        print(f"Runner Log: {runner_log_path}")
        print("=" * 72)


def run_benchmark_command(args) -> int:
    if not hasattr(args, "appium_host"):
        args = Namespace(**vars(args), appium_host="127.0.0.1")
    if not hasattr(args, "output_root"):
        args = Namespace(**vars(args), output_root=IOS_DEFAULT_BENCHMARK_DIR)
    return IOSBenchmarkRunner().run(args)


__all__ = [
    "IOS_DEFAULT_BENCHMARK_DIR",
    "run_benchmark_command",
]
