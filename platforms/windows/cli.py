#!/usr/bin/env python3
"""
Windows platform entrypoint.
Public input is execution + Windows runtime config.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shlex
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

WINDOWS_RUNTIME_CONFIG_PATH = repo_root / "configs" / "windows.yaml"
INTERNAL_BENCHMARK_TASK_COMMAND = "__benchmark_task"

logger = logging.getLogger(__name__)

RUNTIME_INFRA_ERROR_MARKERS = (
    "winerror 10060",
    "timed out",
    "read timed out",
    "connection refused",
    "failed to establish a new connection",
    "actively refused",
    "windows runtime not ready",
    "did not become ready",
    "runtime health check failed",
    "vmware guest command failed",
    "guest program exited",
)

RUNTIME_ENDPOINT_MARKERS = (
    "/run_python",
    "/observe",
    "/execute",
    "/health",
    "request failed get http://",
    "request failed post http://",
    "windows runtime",
)


def _build_execution_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Windows execution runner (execution-driven input).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--execution", required=True, help="Path to execution YAML file.")
    return parser


def _build_internal_benchmark_task_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal Windows benchmark task worker command.")
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
    parser.add_argument("--vm-ip", required=True, type=str)
    parser.add_argument("--runtime-port", required=True, type=int)
    parser.add_argument("--runtime-token", required=True, type=str)
    parser.add_argument("--vm-guest-password", type=str, default=None)
    parser.add_argument("--resume-from-trajectory", type=str, default=None)
    parser.add_argument("--skip-initialization", action="store_true")
    return parser


def _run_benchmark_task_command(args):
    from platforms.windows.runners.episode import run_benchmark_task_command

    return run_benchmark_task_command(args)


def _run_benchmark_command(args):
    from platforms.windows.runners.benchmark import run_benchmark_command

    return run_benchmark_command(args)


def _normalize_action_mode(action_mode_raw: str | None) -> str:
    if not action_mode_raw:
        return "code_adapter"
    normalized = action_mode_raw.strip().lower()
    if normalized != "code_adapter":
        raise ValueError(
            "execution.action_mode only supports code_adapter for Windows."
        )
    return normalized


def _safe_name(raw: str) -> str:
    text = (raw or "").strip() or "unnamed"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_nonnegative_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid integer %s=%r; using %d", name, raw, default)
        return default
    return max(0, value)


def _read_text_tail(path: Path, *, max_chars: int = 20000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_chars), os.SEEK_SET)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _is_runtime_infra_error_text(text: str) -> bool:
    lower = text.lower()
    if not lower:
        return False
    vmware_guest_failure = (
        "vmware guest command failed" in lower
        or "runprograminguest" in lower
        or "guest program exited" in lower
        or "getguestipaddress" in lower
    )
    if vmware_guest_failure:
        return True
    has_runtime_endpoint = any(marker in lower for marker in RUNTIME_ENDPOINT_MARKERS)
    has_timeout_or_connection_error = any(marker in lower for marker in RUNTIME_INFRA_ERROR_MARKERS)
    return has_runtime_endpoint and has_timeout_or_connection_error


def _latest_benchmark_dir(output_root: Path, benchmark_name: str) -> Path | None:
    if not output_root.exists():
        return None
    prefix = f"{benchmark_name}_"
    candidates = [path for path in output_root.iterdir() if path.is_dir() and path.name.startswith(prefix)]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _task_run_has_runtime_infra_error(task_run_dir: Path | None) -> bool:
    if task_run_dir is None:
        return False

    result_path = task_run_dir / "result.json"
    try:
        with result_path.open("r", encoding="utf-8") as fh:
            result_payload = json.load(fh)
        result_status = str(result_payload.get("status", "")).upper()
        result_message = json.dumps(result_payload.get("episode_result", {}), ensure_ascii=False)
        if result_status == "ERROR" and _is_runtime_infra_error_text(result_message):
            return True
    except (OSError, json.JSONDecodeError):
        pass

    scan_text = "\n".join(
        [
            _read_text_tail(task_run_dir / "runner.log"),
            _read_text_tail(task_run_dir / "trajectory.jsonl"),
            _read_text_tail(result_path),
        ]
    )
    return _is_runtime_infra_error_text(scan_text)


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
            "execution.observation_mode only supports screenshot_only/a11y_tree_only/screenshot_and_a11y_tree for Windows."
        )
    return observation_mode


def _normalize_history_window(history_window_raw: object) -> int:
    if history_window_raw is None:
        return 3
    if isinstance(history_window_raw, bool) or not isinstance(history_window_raw, int) or history_window_raw <= 0:
        raise ValueError("execution.history_window must be a positive integer for Windows.")
    return int(history_window_raw)


def _normalize_optional_positive_int(value_raw: object, *, field_name: str) -> int | None:
    if value_raw is None:
        return None
    if isinstance(value_raw, bool) or not isinstance(value_raw, int) or value_raw < 0:
        raise ValueError(f"execution.{field_name} must be a non-negative integer for Windows when provided.")
    return int(value_raw)


def _resolve_execution_base_name(execution_path: Path) -> str:
    return _safe_name(execution_path.stem)


def _resolve_model_results_root(model_id: str) -> Path:
    return repo_root / "results" / _safe_name(model_id) / "windows"


def _resolve_task_label(task_path: Path) -> str:
    with task_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"Task file is missing task_id: {task_path}")
    return task_id.strip()


def _run_livecleanup_between_tasks(runtime_config, *, runtime_host: str | None = None) -> None:
    from platforms.windows.runners.episode import build_runtime_url, wait_for_runtime_ready
    from platforms.windows.runtime_env.controller import WindowsRuntimeController

    host = (runtime_host or runtime_config.vm_ip or "").strip()
    if not host:
        raise RuntimeError("Cannot run Windows livecleanup without a resolved runtime host.")

    runtime_url = build_runtime_url(host, runtime_config.runtime_port)
    ready_timeout = float(os.environ.get("HELLOWORLD_WINDOWS_LIVECLEANUP_READY_TIMEOUT", "60"))
    wait_for_runtime_ready(runtime_url, str(runtime_config.runtime_token), timeout_seconds=ready_timeout)
    controller = WindowsRuntimeController(
        runtime_url=runtime_url,
        token=str(runtime_config.runtime_token),
        timeout=20.0,
    )
    cleanup_script = repo_root / "platforms" / "windows" / "vm" / "setup" / "cleanup-generic-state.ps1"
    remote_cleanup_script = r"C:\Users\User\AppData\Local\Temp\cleanup-generic-state.ps1"
    controller.upload_file(str(cleanup_script), remote_cleanup_script)
    controller.execute_command(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            remote_cleanup_script,
        ],
        shell=False,
        timeout=240,
    )
    wait_for_runtime_ready(runtime_url, str(runtime_config.runtime_token), timeout_seconds=ready_timeout)


def _to_wsl_path(path: Path) -> str:
    raw = str(path.resolve()).replace("\\", "/")
    if len(raw) >= 3 and raw[1:3] == ":/":
        drive = raw[0].lower()
        return f"/mnt/{drive}/{raw[3:]}"
    return raw


def _restart_windows_vm_for_recovery(runtime_config) -> None:
    from platforms.windows.runners.episode import build_runtime_url, wait_for_runtime_ready

    if runtime_config.vm_provider:
        from platforms.windows.runtime_env.vm_manager import start_windows_vm_session

        logger.warning("Attempting Windows VM restart/recovery through configured VM provider...")
        vm_session = start_windows_vm_session(runtime_config, logger_obj=logger)
        runtime_url = build_runtime_url(vm_session.runtime_host, runtime_config.runtime_port)
        recovery_timeout = float(os.environ.get("HELLOWORLD_WINDOWS_RECOVERY_READY_TIMEOUT", "180"))
        wait_for_runtime_ready(
            runtime_url,
            str(runtime_config.runtime_token),
            timeout_seconds=recovery_timeout,
        )
        return

    runtime_url = build_runtime_url(runtime_config.vm_ip, runtime_config.runtime_port)
    repo_for_shell = _to_wsl_path(repo_root) if os.name == "nt" else str(repo_root)
    shell_command = (
        f"cd {shlex.quote(repo_for_shell)} && "
        "HELLOWORLD_WINDOWS_ALLOW_FORCE_REMOVE=true "
        "bash platforms/windows/scripts/gentle_shutdown_and_reset.sh && "
        "HELLOWORLD_WINDOWS_ALLOW_FORCE_REMOVE=true "
        "bash platforms/windows/start_windows_vm.sh"
    )
    if os.name == "nt":
        command = ["wsl.exe", "sh", "-lc", shell_command]
    else:
        command = ["bash", "-lc", shell_command]

    logger.warning("Attempting Windows VM restart/recovery with overlay reset...")
    subprocess.run(command, check=True)
    recovery_timeout = float(os.environ.get("HELLOWORLD_WINDOWS_RECOVERY_READY_TIMEOUT", "180"))
    wait_for_runtime_ready(
        runtime_url,
        str(runtime_config.runtime_token),
        timeout_seconds=recovery_timeout,
    )


def _run_execution_command(args: argparse.Namespace) -> int:
    from platforms.windows.runtime_config import load_execution_handoff, load_windows_runtime_config
    from platforms.windows.runners.episode import build_runtime_url, wait_for_runtime_ready
    from platforms.windows.runtime_env.vm_manager import start_windows_vm_session

    execution = load_execution_handoff(args.execution)
    runtime_config = load_windows_runtime_config(WINDOWS_RUNTIME_CONFIG_PATH)
    action_mode = _normalize_action_mode(execution.get("action_mode"))
    observation_mode = _normalize_observation_mode(execution.get("observation_mode"))
    history_window = _normalize_history_window(execution.get("history_window"))
    max_steps = _normalize_optional_positive_int(execution.get("max_steps"), field_name="max_steps")
    timeout = _normalize_optional_positive_int(execution.get("timeout"), field_name="timeout")
    model_ids = list(dict.fromkeys(execution.get("models", [])))
    if not model_ids:
        raise ValueError("execution.models cannot be empty for Windows.")
    execution_base_name = _resolve_execution_base_name(execution["source_path"])
    task_paths = execution.get("task_paths", [])
    execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    reuse_vm_session = bool(execution.get("reuse_vm_session", False))
    use_snapshot_reset = bool(runtime_config.vm_provider and runtime_config.vm_reset_between_tasks and not reuse_vm_session)

    logger.info("Execution: %s", execution["source_path"])
    logger.info("Tasks: %d, Models: %d", len(task_paths), len(model_ids))
    logger.info("Config: %s", WINDOWS_RUNTIME_CONFIG_PATH)
    logger.info("Runtime: %s:%d", runtime_config.vm_ip, runtime_config.runtime_port)
    logger.info(
        "VM Session Mode: %s",
        "reuse_per_execution"
        if reuse_vm_session
        else ("snapshot_per_task" if use_snapshot_reset else "external_runtime"),
    )
    runtime_timeout_retries = _env_nonnegative_int("HELLOWORLD_WINDOWS_RUNTIME_TIMEOUT_RETRIES", 2)
    runtime_retry_enabled = _env_bool("HELLOWORLD_WINDOWS_RUNTIME_RETRY_ON_TIMEOUT", True)
    logger.info(
        "Runtime timeout retry: %s, retries per task: %d",
        "enabled" if runtime_retry_enabled else "disabled",
        runtime_timeout_retries,
    )

    shared_vm_session: Any = None
    shared_runtime_host = runtime_config.vm_ip
    if reuse_vm_session and runtime_config.vm_provider:
        shared_vm_session = start_windows_vm_session(runtime_config, logger_obj=logger)
        if shared_vm_session is not None:
            shared_runtime_host = shared_vm_session.runtime_host
        runtime_url = build_runtime_url(shared_runtime_host, runtime_config.runtime_port)
        ready_timeout = float(os.environ.get("HELLOWORLD_WINDOWS_VM_READY_TIMEOUT", "180"))
        wait_for_runtime_ready(
            runtime_url,
            str(runtime_config.runtime_token),
            timeout_seconds=ready_timeout,
        )

    failed_tasks: list[str] = []
    try:
        for model_id in model_ids:
            execution_run_dir = _resolve_model_results_root(model_id) / f"{execution_base_name}_{execution_timestamp}"
            execution_run_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Execution output dir for model %s: %s", model_id, execution_run_dir)

            dedupe_counter: dict[str, int] = {}
            for task_index, task_path in enumerate(task_paths, start=1):
                task_label = _resolve_task_label(task_path)
                dedupe_counter[task_label] = dedupe_counter.get(task_label, 0) + 1
                suffix = dedupe_counter[task_label]
                benchmark_name = task_label if suffix == 1 else f"{task_label}_{suffix}"
                task_runtime_host = shared_runtime_host
                task_succeeded = False
                task_recorded_failure = False
                max_attempts = 1 + (runtime_timeout_retries if runtime_retry_enabled else 0)

                for attempt in range(max_attempts):
                    vm_session: Any = None
                    close_failed = False
                    should_retry_runtime = False
                    attempt_benchmark_name = benchmark_name if attempt == 0 else f"{benchmark_name}_retry{attempt}"
                    task_runtime_host = shared_runtime_host

                    try:
                        if use_snapshot_reset:
                            logger.info(
                                "Resetting Windows VM from snapshot before task (%d/%d, attempt %d/%d): %s",
                                task_index,
                                len(task_paths),
                                attempt + 1,
                                max_attempts,
                                task_path,
                            )
                            vm_session = start_windows_vm_session(runtime_config, logger_obj=logger)
                            if vm_session is not None:
                                task_runtime_host = vm_session.runtime_host
                            runtime_url = build_runtime_url(task_runtime_host, runtime_config.runtime_port)
                            ready_timeout = float(os.environ.get("HELLOWORLD_WINDOWS_VM_READY_TIMEOUT", "180"))
                            wait_for_runtime_ready(
                                runtime_url,
                                str(runtime_config.runtime_token),
                                timeout_seconds=ready_timeout,
                            )
                            if _env_bool("HELLOWORLD_WINDOWS_CLEANUP_AFTER_SNAPSHOT", True):
                                logger.info(
                                    "Running Windows generic cleanup after snapshot reset before task (%d/%d): %s",
                                    task_index,
                                    len(task_paths),
                                    task_path,
                                )
                                _run_livecleanup_between_tasks(runtime_config, runtime_host=task_runtime_host)

                        bench_args = argparse.Namespace(
                            task_file=str(task_path),
                            execution_file=str(execution["source_path"]),
                            models=model_id,
                            benchmark_name=attempt_benchmark_name,
                            output_root=str(execution_run_dir),
                            action_mode=action_mode,
                            observation_mode=observation_mode,
                            history_window=history_window,
                            max_steps=max_steps,
                            timeout=timeout,
                            vm_ip=task_runtime_host,
                            runtime_port=runtime_config.runtime_port,
                            runtime_token=runtime_config.runtime_token,
                            vm_guest_password=runtime_config.vm_guest_password,
                        )
                        logger.info(
                            "Running task benchmark for model %s (attempt %d/%d): %s",
                            model_id,
                            attempt + 1,
                            max_attempts,
                            task_path,
                        )
                        exit_code = _run_benchmark_command(bench_args)
                        if exit_code == 0:
                            task_succeeded = True
                        else:
                            latest_run_dir = _latest_benchmark_dir(execution_run_dir, attempt_benchmark_name)
                            should_retry_runtime = (
                                runtime_retry_enabled
                                and attempt < max_attempts - 1
                                and _task_run_has_runtime_infra_error(latest_run_dir)
                            )
                            if should_retry_runtime:
                                logger.warning(
                                    "Windows runtime infrastructure error detected for %s; retrying as %s.",
                                    latest_run_dir or attempt_benchmark_name,
                                    f"{benchmark_name}_retry{attempt + 1}",
                                )
                            else:
                                failure_suffix = f":attempt{attempt + 1}" if attempt else ""
                                failed_tasks.append(f"{model_id}:{task_path}{failure_suffix}")
                                task_recorded_failure = True
                    except Exception as exc:
                        should_retry_runtime = (
                            runtime_retry_enabled
                            and attempt < max_attempts - 1
                            and _is_runtime_infra_error_text(str(exc))
                        )
                        if should_retry_runtime:
                            logger.warning(
                                "Windows runtime/session infrastructure error before benchmark for %s; "
                                "retrying as %s. Error: %s",
                                task_path,
                                f"{benchmark_name}_retry{attempt + 1}",
                                exc,
                            )
                            if runtime_config.vm_provider:
                                try:
                                    _restart_windows_vm_for_recovery(runtime_config)
                                except Exception:
                                    logger.exception(
                                        "Runtime recovery restart failed before retrying task %s; retry will still proceed.",
                                        task_path,
                                    )
                        else:
                            failure_suffix = f":attempt{attempt + 1}" if attempt else ""
                            failed_tasks.append(f"{model_id}:{task_path}{failure_suffix}:session_start_failed:{exc}")
                            task_recorded_failure = True
                    finally:
                        if vm_session is not None:
                            try:
                                vm_session.close()
                            except Exception as exc:
                                logger.exception("Failed to close Windows VM session after task %s", task_path)
                                failed_tasks.append(f"{model_id}:{task_path}:vm_cleanup_failed:{exc}")
                                close_failed = True

                    if close_failed or task_succeeded or task_recorded_failure:
                        break

                    if should_retry_runtime:
                        if not use_snapshot_reset and runtime_config.vm_provider:
                            try:
                                _restart_windows_vm_for_recovery(runtime_config)
                            except Exception as recovery_exc:
                                logger.exception("Runtime recovery failed before retrying task %s", task_path)
                                failed_tasks.append(
                                    f"{model_id}:{task_path}:runtime_retry_recovery_failed:{recovery_exc}"
                                )
                                break
                        continue

                    break

                if reuse_vm_session and task_index < len(task_paths):
                    logger.info(
                        "Running livecleanup between tasks (%d/%d) after %s",
                        task_index,
                        len(task_paths),
                        task_path,
                    )
                    try:
                        _run_livecleanup_between_tasks(runtime_config, runtime_host=task_runtime_host)
                    except Exception as exc:
                        logger.exception("Livecleanup failed after task %s", task_path)
                        if os.environ.get("HELLOWORLD_WINDOWS_RESTART_ON_LIVECLEANUP_FAIL", "true").lower() in {
                            "1",
                            "true",
                            "yes",
                        }:
                            try:
                                _restart_windows_vm_for_recovery(runtime_config)
                                logger.info(
                                    "Runtime recovered after livecleanup failure; continuing with next task."
                                )
                                continue
                            except Exception as recovery_exc:
                                logger.exception("Runtime recovery failed after task %s", task_path)
                                failed_tasks.append(
                                    f"{model_id}:{task_path}:livecleanup_failed:{exc}:"
                                    f"recovery_failed:{recovery_exc}"
                                )
                                break
                        failed_tasks.append(f"{model_id}:{task_path}:livecleanup_failed:{exc}")
                        break
    finally:
        if shared_vm_session is not None:
            shared_vm_session.close()

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
