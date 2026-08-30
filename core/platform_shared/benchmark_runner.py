"""Shared benchmark runner utilities used by multiple platform runners."""

from __future__ import annotations

import logging
import re
import subprocess
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class BaseBenchmarkRunner(ABC):
    """Base class with reusable benchmark orchestration helpers."""

    def __init__(self, logger_obj: Optional[logging.Logger] = None) -> None:
        self.logger = logger_obj or logging.getLogger(self.__class__.__module__)

    @staticmethod
    def parse_csv_list(raw: str) -> List[str]:
        return [item.strip() for item in (raw or "").split(",") if item.strip()]

    @staticmethod
    def safe_name(raw: str) -> str:
        text = (raw or "").strip() or "unnamed"
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text)

    @classmethod
    def resolve_run_artifact_paths(
        cls,
        run_dir: str | Path,
    ) -> Dict[str, Optional[str]]:
        artifact_dir = Path(run_dir).resolve()

        trajectory_path = artifact_dir / "trajectory.jsonl"
        result_path = artifact_dir / "result.json"

        resolved_trajectory = str(trajectory_path) if trajectory_path.is_file() else None
        resolved_result = str(result_path) if result_path.is_file() else None

        return {
            "run_dir": str(artifact_dir),
            "trajectory_path": resolved_trajectory,
            "result_path": resolved_result,
        }

    @staticmethod
    def append_runner_log(log_path: Path, text: str) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")

    def run_command_streaming(
        self,
        cmd: List[str],
        log_path: Path,
        *,
        run_prefix: str,
        env: Optional[Dict[str, str]] = None,
        child_log_mode: str = "logger",
    ) -> int:
        timestamp = datetime.now().isoformat(timespec="seconds")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        assert proc.stdout is not None
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(
                    "\n"
                    + "=" * 88
                    + f"\n[{timestamp}] {run_prefix}\n"
                    + f"CMD: {' '.join(cmd)}\n"
                    + "=" * 88
                    + "\n"
                )
                for line in proc.stdout:
                    if child_log_mode == "print":
                        print(line, end="", flush=True)
                    else:
                        self.logger.info("[Child %s] %s", run_prefix, line.rstrip("\n"))
                    log_file.write(line)
                log_file.write(f"[{run_prefix}] EXIT_CODE={proc.wait()}\n")
        except BaseException:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                    proc.wait()
            raise

        return proc.returncode or 0

    def format_uncaught_error(self, error: Exception) -> str:
        return "".join(traceback.format_exception(type(error), error, error.__traceback__)).strip()

    def _execute_jobs(
        self,
        args: Any,
        jobs: List[Dict[str, Any]],
        cli_entry_path: str,
        run_root: Path,
        runner_log_path: Path,
    ) -> List[Dict[str, Any]]:
        run_records: List[Dict[str, Any]] = []
        for job in jobs:
            try:
                record = self._execute_single_run(
                    args=args,
                    job=job,
                    cli_entry_path=cli_entry_path,
                    run_root=run_root,
                    runner_log_path=runner_log_path,
                )
            except Exception as e:
                record = self._build_exception_record(
                    args=args,
                    job=job,
                    error=e,
                    runner_log_path=runner_log_path,
                )
            run_records.append(record)
        run_records.sort(key=lambda item: item.get("run_index", 0))
        return run_records

    def _before_runs(
        self,
        args: Any,
        task: Dict[str, Any],
        models: List[str],
        benchmark_dir: Path,
        run_root: Path,
        runner_log_path: Path,
    ) -> None:
        """Optional setup hook before executing run jobs."""

    def _after_runs(
        self,
        args: Any,
        task: Dict[str, Any],
        models: List[str],
        benchmark_dir: Path,
        run_root: Path,
        runner_log_path: Path,
        run_records: List[Dict[str, Any]],
    ) -> None:
        """Optional teardown hook after executing run jobs."""

    def _success_exit_code(self, run_records: List[Dict[str, Any]]) -> int:
        total_runs = len(run_records)
        total_success = sum(1 for r in run_records if r.get("success"))
        return 0 if (total_runs > 0 and total_success == total_runs) else 1

    def run(self, args: Any) -> int:
        models = self._validate_and_get_models(args)
        task = self._load_task_descriptor(args)
        jobs = self._build_benchmark_jobs(task, models, args)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        benchmark_name = self._resolve_benchmark_name(args)
        benchmark_dir, run_root, runner_log_path = self._prepare_benchmark_dirs(
            args=args,
            benchmark_name=benchmark_name,
            timestamp=timestamp,
        )

        self._log_benchmark_start(
            args=args,
            benchmark_name=benchmark_name,
            benchmark_dir=benchmark_dir,
            run_root=run_root,
            runner_log_path=runner_log_path,
            task=task,
            models=models,
            jobs=jobs,
        )

        cli_entry_path = self._resolve_cli_entry_path()

        self._before_runs(args, task, models, benchmark_dir, run_root, runner_log_path)
        try:
            run_records = self._execute_jobs(
                args=args,
                jobs=jobs,
                cli_entry_path=cli_entry_path,
                run_root=run_root,
                runner_log_path=runner_log_path,
            )
        finally:
            self._after_runs(
                args,
                task,
                models,
                benchmark_dir,
                run_root,
                runner_log_path,
                locals().get("run_records", []),
            )

        self._log_completion(
            args=args,
            run_records=run_records,
            runner_log_path=runner_log_path,
        )

        return self._success_exit_code(run_records)

    @abstractmethod
    def _validate_and_get_models(self, args: Any) -> List[str]:
        """Validate CLI args and return normalized model list."""

    @abstractmethod
    def _load_task_descriptor(self, args: Any) -> Dict[str, Any]:
        """Load one benchmark task descriptor dictionary."""

    @abstractmethod
    def _build_benchmark_jobs(
        self,
        task: Dict[str, Any],
        models: List[str],
        args: Any,
    ) -> List[Dict[str, Any]]:
        """Build run jobs for benchmark execution."""

    @abstractmethod
    def _resolve_benchmark_name(self, args: Any) -> str:
        """Return benchmark display/name prefix."""

    @abstractmethod
    def _prepare_benchmark_dirs(
        self,
        *,
        args: Any,
        benchmark_name: str,
        timestamp: str,
    ) -> Tuple[Path, Path, Path]:
        """Create and return (benchmark_dir, run_root, runner_log_path)."""

    @abstractmethod
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
        """Emit start logs and benchmark preamble file content."""

    @abstractmethod
    def _resolve_cli_entry_path(self) -> str:
        """Return path to CLI entry file used for child runs."""

    @abstractmethod
    def _execute_single_run(
        self,
        *,
        args: Any,
        job: Dict[str, Any],
        cli_entry_path: str,
        run_root: Path,
        runner_log_path: Path,
    ) -> Dict[str, Any]:
        """Execute one run and return run record."""

    @abstractmethod
    def _build_exception_record(
        self,
        *,
        args: Any,
        job: Dict[str, Any],
        error: Exception,
        runner_log_path: Path,
    ) -> Dict[str, Any]:
        """Build run record for uncaught run exceptions."""

    @abstractmethod
    def _log_completion(
        self,
        *,
        args: Any,
        run_records: List[Dict[str, Any]],
        runner_log_path: Path,
    ) -> None:
        """Emit completion logs after benchmark execution finishes."""
