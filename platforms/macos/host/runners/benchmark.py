#!/usr/bin/env python3
"""
Benchmark runner for serial clone -> run -> delete macOS experiments.
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from platforms.macos.host.runners.base_benchmark import BaseBenchmarkRunner

from platforms.macos.host.core.types import load_task_from_file
from platforms.macos.host.runtime_env.vm_manager import MacOSVMManager, create_macos_vm_manager

MACOS_PLATFORM_DIR = Path(__file__).resolve().parents[2]
V2_BASE_DIR = Path(__file__).resolve().parents[4]
MACOS_BENCHMARK_OUTPUT_ROOT = str(V2_BASE_DIR / "results" / "macos")
INTERNAL_BENCHMARK_TASK_COMMAND = "__benchmark_task"
MACOS_OUTPUT_DIR_ENV = "MACOS_OUTPUT_DIR"
MACOS_SKIP_VM_CLONE_ENV = "MACOS_SKIP_VM_CLONE"
MACOS_SKIP_GUEST_RUNTIME_SYNC_ENV = "MACOS_SKIP_GUEST_RUNTIME_SYNC"
MACOS_ENABLE_GUEST_RUNTIME_SYNC_ENV = "MACOS_ENABLE_GUEST_RUNTIME_SYNC"
MACOS_GUEST_SSH_IDENTITY_FILE_ENV = "HELLOWORLD_MACOS_GUEST_SSH_IDENTITY_FILE"
MACOS_DEFAULT_GUEST_SSH_IDENTITY_BASENAME = "helloworld_macos_bench"
CLONE_POST_BOOT_SETTLE_SECONDS = 1.0
GUEST_RUNTIME_INSTALL_PATH = "/Applications/MacUIBenchRuntime/runtime/runtime_server.py"
GUEST_REQUIREMENTS_INSTALL_PATH = "/Applications/MacUIBenchRuntime/runtime/requirements.txt"
GUEST_RUNTIME_VENV_PYTHON = "/Applications/MacUIBenchRuntime/runtime/.venv/bin/python"
GUEST_RUNTIME_VENV_PIP = "/Applications/MacUIBenchRuntime/runtime/.venv/bin/pip"
GUEST_RUNTIME_LABEL = "com.yourlab.macui.runtime"
GUEST_RUNTIME_SYNC_RETRIES = 20
GUEST_RUNTIME_SYNC_INTERVAL_SECONDS = 2.0

logger = logging.getLogger(__name__)


class MacOSBenchmarkRunner(BaseBenchmarkRunner):
    def __init__(self) -> None:
        super().__init__(logger)
        self._manager: Optional[MacOSVMManager] = None

    @staticmethod
    def _skip_vm_clone_enabled() -> bool:
        return os.environ.get(MACOS_SKIP_VM_CLONE_ENV, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _env_truthy(name: str) -> bool:
        return os.environ.get(name, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _guest_runtime_sync_enabled() -> bool:
        if MacOSBenchmarkRunner._env_truthy(MACOS_SKIP_GUEST_RUNTIME_SYNC_ENV):
            return False
        return MacOSBenchmarkRunner._env_truthy(MACOS_ENABLE_GUEST_RUNTIME_SYNC_ENV)

    @staticmethod
    def _resolve_guest_ssh_identity_file() -> Optional[Path]:
        identity_file = os.environ.get(MACOS_GUEST_SSH_IDENTITY_FILE_ENV, "").strip()
        if identity_file:
            return Path(identity_file).expanduser()

        default_identity_file = Path.home() / ".ssh" / MACOS_DEFAULT_GUEST_SSH_IDENTITY_BASENAME
        if default_identity_file.exists():
            return default_identity_file
        return None

    @staticmethod
    def _guest_ssh_options() -> List[str]:
        options = [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "PreferredAuthentications=publickey",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "IdentityAgent=none",
        ]
        identity_file = MacOSBenchmarkRunner._resolve_guest_ssh_identity_file()
        if identity_file:
            options.extend(["-i", str(identity_file)])
        return options

    @staticmethod
    def _build_clone_name(run_index: int, model: str, task_id: str) -> str:
        timestamp_ms = int(time.time() * 1000)
        safe_model = BaseBenchmarkRunner.safe_name(model)
        safe_task = BaseBenchmarkRunner.safe_name(task_id)
        return f"{run_index:04d}_{safe_model}_{safe_task}_{timestamp_ms}"

    @staticmethod
    def _resolve_task_base_vm_name(task_file: str) -> Optional[str]:
        source_path = Path(task_file).resolve()
        try:
            payload = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.exception("Failed to resolve task-specific base_vm_name from %s", source_path)
            return None

        if not isinstance(payload, dict):
            return None

        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            candidate = metadata.get("base_vm_name")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        init = payload.get("init")
        if isinstance(init, dict):
            params = init.get("params")
            if isinstance(params, dict):
                candidate = params.get("base_vm_name")
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()

        return None

    @staticmethod
    def _resolve_execution_base_vm_name(execution_file: str | None) -> Optional[str]:
        if not execution_file:
            return None
        source_path = Path(execution_file).resolve()
        try:
            payload = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.exception("Failed to resolve execution-specific base_vm_name from %s", source_path)
            return None

        if not isinstance(payload, dict):
            return None

        candidate = payload.get("base_vm_name")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            candidate = metadata.get("base_vm_name")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        return None

    @staticmethod
    def _sync_guest_runtime(vm_ip: str) -> Tuple[bool, Optional[str]]:
        source_path = MACOS_PLATFORM_DIR / "guest" / "runtime_server.py"
        requirements_path = MACOS_PLATFORM_DIR / "guest" / "requirements.txt"
        if not source_path.exists():
            return False, f"runtime source not found: {source_path}"
        if not requirements_path.exists():
            return False, f"runtime requirements not found: {requirements_path}"

        ssh_options = MacOSBenchmarkRunner._guest_ssh_options()
        ssh_base = ["ssh", *ssh_options, f"bench@{vm_ip}"]
        scp_base = [
            "scp",
            *ssh_options,
            str(source_path),
            str(requirements_path),
            f"bench@{vm_ip}:/tmp/",
        ]

        remote_cmd = (
            "sudo cp /tmp/runtime_server.py "
            f"{GUEST_RUNTIME_INSTALL_PATH} && "
            "sudo cp /tmp/requirements.txt "
            f"{GUEST_REQUIREMENTS_INSTALL_PATH} && "
            f"{GUEST_RUNTIME_VENV_PIP} install -r {GUEST_REQUIREMENTS_INSTALL_PATH} >/tmp/helloworld_macos_pip_sync.log 2>&1 && "
            f"{GUEST_RUNTIME_VENV_PYTHON} -m py_compile {GUEST_RUNTIME_INSTALL_PATH} && "
            f"launchctl kickstart -k gui/$(id -u)/{GUEST_RUNTIME_LABEL}"
        )

        last_error: Optional[str] = None
        for _ in range(GUEST_RUNTIME_SYNC_RETRIES):
            try:
                scp_proc = subprocess.run(
                    scp_base,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if scp_proc.returncode != 0:
                    last_error = (scp_proc.stderr or scp_proc.stdout or "").strip() or "scp failed"
                    time.sleep(GUEST_RUNTIME_SYNC_INTERVAL_SECONDS)
                    continue

                ssh_proc = subprocess.run(
                    [*ssh_base, remote_cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=20,
                    check=False,
                )
                if ssh_proc.returncode == 0:
                    return True, None
                last_error = (ssh_proc.stderr or ssh_proc.stdout or "").strip() or "ssh remote command failed"
            except Exception as exc:
                last_error = str(exc)
            time.sleep(GUEST_RUNTIME_SYNC_INTERVAL_SECONDS)

        return False, last_error or "unknown guest runtime sync failure"

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
        clone_name: Optional[str] = None,
        vm_ip: Optional[str] = None,
        runtime_url: Optional[str] = None,
        cleanup_error: Optional[str] = None,
        base_vm_name: Optional[str] = None,
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
            "clone_name": clone_name,
            "vm_ip": vm_ip,
            "runtime_url": runtime_url,
            "cleanup_error": cleanup_error,
            "base_vm_name": base_vm_name,
        }

    @staticmethod
    def _prepare_vm_for_run(
        args,
        context: Dict[str, Any],
        manager: Optional[MacOSVMManager],
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str], Optional[str]]:
        fallback_vm_ip = str(args.vm_ip)
        runtime_url = f"http://{fallback_vm_ip}:{int(args.runtime_port)}"
        if MacOSBenchmarkRunner._skip_vm_clone_enabled():
            return True, None, None, fallback_vm_ip, runtime_url
        if manager is None:
            return False, "VM manager is not initialized", None, None, None

        base_vm_name = context.get("base_vm_name") or args.base_vm_name
        clone_name = context.get("clone_name")
        if not base_vm_name:
            return False, "--base-vm-name is required", None, None, None

        prepared = manager.prepare_benchmark_environment(
            base_vm_name=base_vm_name,
            clone_name=str(clone_name).strip() if clone_name else None,
        )
        if not prepared:
            return False, f"prepare_benchmark_environment failed (base={base_vm_name})", None, None, None

        clone_name = prepared

        time.sleep(CLONE_POST_BOOT_SETTLE_SECONDS)
        vm_ip = manager.resolve_runtime_host(clone_name, fallback_host=fallback_vm_ip)
        if MacOSBenchmarkRunner._guest_runtime_sync_enabled():
            sync_ok, sync_error = MacOSBenchmarkRunner._sync_guest_runtime(vm_ip)
            if not sync_ok:
                manager.cleanup_benchmark_environment(clone_name)
                return False, f"guest runtime sync failed for {vm_ip}: {sync_error}", clone_name, vm_ip, None
        runtime_url = f"http://{vm_ip}:{int(args.runtime_port)}"

        return True, None, clone_name, vm_ip, runtime_url

    @staticmethod
    def _cleanup_ephemeral_vm(
        manager: MacOSVMManager,
        clone_name: Optional[str],
    ) -> Tuple[bool, Optional[str]]:
        if not clone_name:
            return True, None
        try:
            ok = manager.cleanup_benchmark_environment(clone_name)
            if ok:
                return True, None
            return False, f"cleanup_benchmark_environment failed for {clone_name}"
        except Exception as e:
            return False, f"cleanup_benchmark_environment exception for {clone_name}: {e}"

    def _validate_and_get_models(self, args: Any) -> List[str]:
        if str(args.action_mode).strip() != "code_adapter":
            raise ValueError("--action-mode must be code_adapter")

        raw_models = self.parse_csv_list(args.models)
        if not raw_models:
            raise ValueError("--models cannot be empty")
        return list(dict.fromkeys(raw_models))

    def _load_task_descriptor(self, args: Any) -> Dict[str, Any]:
        task_file = str(args.task_file)
        task = load_task_from_file(task_file)
        if not task.source_file:
            raise ValueError(f"Task file has no source path: {task_file}")
        resolved_task_file = str(Path(task.source_file).resolve())
        execution_base_vm_name = self._resolve_execution_base_vm_name(getattr(args, "execution_file", None))
        return {
            "task_id": task.id,
            "task_goal": task.goal,
            "task_file": resolved_task_file,
            "base_vm_name": self._resolve_task_base_vm_name(resolved_task_file) or execution_base_vm_name,
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
                    "base_vm_name": task.get("base_vm_name"),
                }
            )
        return jobs

    def _resolve_benchmark_name(self, args: Any) -> str:
        return self.safe_name(getattr(args, "benchmark_name", None) or "macos_benchmark")

    def _prepare_benchmark_dirs(
        self,
        *,
        args: Any,
        benchmark_name: str,
        timestamp: str,
    ) -> Tuple[Path, Path, Path]:
        output_root = Path(str(getattr(args, "output_root", MACOS_BENCHMARK_OUTPUT_ROOT)))
        benchmark_dir = output_root / f"{benchmark_name}_{timestamp}"
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
        effective_base_vm_name = str(task.get("base_vm_name") or args.base_vm_name or "").strip() or None
        logger.info("Benchmark Dir: %s", benchmark_dir)
        logger.info("Task: %s, Models: %s", task["task_id"], models)
        logger.info("Base VM Name: %s", effective_base_vm_name or args.base_vm_name)
        logger.info("Skip VM Clone: %s", "yes" if self._skip_vm_clone_enabled() else "no")
        logger.info("VM IP: %s", args.vm_ip)
        logger.info("Runtime Port: %d", int(args.runtime_port))
        self.append_runner_log(
            runner_log_path,
            (
                f"# Benchmark: {benchmark_name}\n"
                f"# Created: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
                f"# Task id: {task['task_id']}\n"
                f"# Task file: {task['task_file']}\n"
                f"# Models: {','.join(models)}\n"
                f"# Base VM Name: {effective_base_vm_name or args.base_vm_name}\n"
                f"# Skip VM Clone: {'yes' if self._skip_vm_clone_enabled() else 'no'}\n"
                f"# VM IP: {args.vm_ip}\n"
                f"# Runtime Port: {args.runtime_port}\n"
            ),
        )

    def _before_runs(
        self,
        args: Any,
        task: Dict[str, Any],
        models: List[str],
        benchmark_dir: Path,
        run_root: Path,
        runner_log_path: Path,
    ) -> None:
        if self._skip_vm_clone_enabled():
            self._manager = None
            return
        effective_base_vm_name = str(task.get("base_vm_name") or args.base_vm_name or "").strip()
        if not effective_base_vm_name:
            raise ValueError("--base-vm-name is required")
        manager = create_macos_vm_manager(getattr(args, "vm_provider", "tart"), tart_home=getattr(args, "tart_home", None))
        if not manager.vm_exists(effective_base_vm_name):
            raise ValueError(f"Base VM not found: {effective_base_vm_name}")
        self._manager = manager

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
        self._manager = None

    def _resolve_cli_entry_path(self) -> str:
        return str(MACOS_PLATFORM_DIR / "host" / "cli.py")

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
        effective_base_vm_name = str(job.get("base_vm_name") or args.base_vm_name or "").strip() or None

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
            "base_vm_name": effective_base_vm_name,
            "clone_name": clone_name,
        }

        logger.info("=" * 72)
        logger.info("[Run %d] model=%s task=%s", run_index, model, task_id)
        logger.info("=" * 72)
        self.append_runner_log(
            runner_log_path,
            (
                f"\n[Run {run_index}] model={model} task={task_id}\n"
                f"[Run {run_index}] task_file={task_file}\n"
                f"[Run {run_index}] effective_base_vm_name={effective_base_vm_name or ''}"
            ),
        )

        clone_name: Optional[str] = None
        vm_ip = str(args.vm_ip)
        runtime_url: Optional[str] = None
        cleanup_error: Optional[str] = None
        record: Optional[Dict[str, Any]] = None

        try:
            reset_ok, reset_error, clone_name, resolved_vm_ip, runtime_url = self._prepare_vm_for_run(
                args,
                context,
                self._manager,
            )
            if resolved_vm_ip:
                vm_ip = str(resolved_vm_ip)
            if not reset_ok:
                self.append_runner_log(runner_log_path, f"[Run {run_index}] reset_failed={reset_error}")
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
                    clone_name=clone_name,
                    vm_ip=vm_ip,
                    runtime_url=runtime_url,
                    base_vm_name=effective_base_vm_name,
                )
                return record

            assert runtime_url is not None
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
                "--prompt-profile",
                str(getattr(args, "prompt_profile", "benchmark")),
                "--history-window",
                str(int(getattr(args, "history_window", 5))),
                "--vm-ip",
                vm_ip,
                "--runtime-port",
                str(args.runtime_port),
                "--vm-token",
                str(args.vm_token),
            ]
            if getattr(args, "execution_file", None):
                cmd.extend(["--execution-file", str(args.execution_file)])
            if args.max_steps is not None:
                cmd.extend(["--max-steps", str(args.max_steps)])
            if args.timeout is not None:
                cmd.extend(["--timeout", str(args.timeout)])
            child_env = os.environ.copy()
            child_env[MACOS_OUTPUT_DIR_ENV] = str(model_output_dir)
            child_env[MACOS_SKIP_VM_CLONE_ENV] = "1"

            logger.info("[Run %d] runtime_url=%s clone=%s", run_index, runtime_url, clone_name)
            self.append_runner_log(
                runner_log_path,
                f"[Run {run_index}] runtime_url={runtime_url} clone={clone_name} ip={vm_ip or ''}",
            )

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
                clone_name=clone_name,
                vm_ip=vm_ip,
                runtime_url=runtime_url,
                base_vm_name=effective_base_vm_name,
            )
            return record
        finally:
            if clone_name and self._manager is not None:
                _, cleanup_error = self._cleanup_ephemeral_vm(self._manager, clone_name)
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
            vm_ip=str(args.vm_ip),
            runtime_url=f"http://{args.vm_ip}:{int(args.runtime_port)}",
            base_vm_name=str(job.get("base_vm_name") or args.base_vm_name or "").strip() or None,
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
            logger.info(
                "Runs: %d, Success: %d, Rate: %.1f%%",
                total_runs,
                total_success,
                (total_success / total_runs) * 100.0,
            )
        else:
            logger.info("Runs: 0")
        logger.info("Runner Log: %s", runner_log_path)
        logger.info("=" * 72)


def run_benchmark_command(args) -> int:
    return MacOSBenchmarkRunner().run(args)


__all__ = [
    "MACOS_BENCHMARK_OUTPUT_ROOT",
    "run_benchmark_command",
]
