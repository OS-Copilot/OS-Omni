"""
Episode execution engine for Windows benchmark.
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from core.artifacts.run_args import write_run_args_snapshot
from core.evaluation import EvalResult, EvalStatus
from core.llm.llm_client import LLMClientManager

from platforms.windows.agent.prompt_builder import WindowsPromptBuilder
from platforms.windows.agent.planners.reflection_pyautogui_planner import ReflectionPyAutoGUIPlanner
from platforms.windows.runners.base_episode import BaseEpisodeRunner
from platforms.windows.runners.evaluation import EvaluationRunResult, run_task_evaluation
from platforms.windows.runners.initialization import InitializationRunResult, run_task_initialization

from platforms.windows.core.types import Task
from platforms.windows.runtime_config import WINDOWS_RUNTIME_CONFIG_PATH, load_windows_runtime_config
from platforms.windows.runtime_env.controller import WindowsRuntimeController, WindowsRuntimeError, Observation
from platforms.windows.runtime_env.vm_manager import (
    VMwareWindowsVMProvider,
    WindowsVMError,
    ensure_windows_guest_runtime,
)

logger = logging.getLogger(__name__)

WINDOWS_PLATFORM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DEFAULT_EPISODES_DIR = str(REPO_ROOT / "results" / "windows" / "episodes")
WINDOWS_OUTPUT_DIR_ENV = "WINDOWS_OUTPUT_DIR"
RUNTIME_READY_TIMEOUT_SECONDS = 30.0
RUNTIME_READY_POLL_INTERVAL_SECONDS = 1.0
CONTROLLER_TIMEOUT_SECONDS = float(os.environ.get("HELLOWORLD_WINDOWS_CONTROLLER_TIMEOUT", "20.0"))

WINDOWS_RUNTIME_INFRA_ERROR_MARKERS = (
    "winerror 10060",
    "timed out",
    "read timed out",
    "connection refused",
    "failed to establish a new connection",
    "actively refused",
    "connection aborted",
    "connection reset",
    "remote end closed connection",
)

WINDOWS_RUNTIME_ENDPOINT_MARKERS = (
    "/run_python",
    "/run_powershell",
    "/observe",
    "/screenshot",
    "/health",
    "request failed get http://",
    "request failed post http://",
    "windows runtime",
)


def build_runtime_url(vm_ip: str, runtime_port: int) -> str:
    ip = (vm_ip or "").strip()
    if not ip:
        raise ValueError("--vm-ip is required")
    if "://" in ip:
        raise ValueError("--vm-ip should be an IP/host without scheme")
    return f"http://{ip}:{int(runtime_port)}"


def build_controller_from_args(args):
    runtime_url = build_runtime_url(args.vm_ip, args.runtime_port)
    logger.info("Controller: windows-runtime (%s)", runtime_url)
    return WindowsRuntimeController(
        runtime_url=runtime_url,
        token=str(args.runtime_token),
        timeout=CONTROLLER_TIMEOUT_SECONDS,
    )


def wait_for_runtime_ready(
    runtime_url: str,
    token: str,
    timeout_seconds: float = RUNTIME_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = RUNTIME_READY_POLL_INTERVAL_SECONDS,
) -> None:
    checker = WindowsRuntimeController(runtime_url=runtime_url, token=token, timeout=5.0)
    start = time.time()
    last_error = None
    while time.time() - start < timeout_seconds:
        try:
            payload = checker.health()
            status = str(payload.get("status", "")).upper()
            if status == "HEALTHY":
                try:
                    smoke = checker.run_powershell_script("'HELLOWORLD_PS_OK'", timeout=10)
                    output = str(smoke.get("output") or "")
                    if str(smoke.get("status") or "").lower() == "success" and "HELLOWORLD_PS_OK" in output:
                        return
                    last_error = f"PowerShell smoke check failed: {smoke}"
                except WindowsRuntimeError as smoke_exc:
                    last_error = f"PowerShell smoke check failed: {smoke_exc}"
            else:
                last_error = f"unexpected health status: {status or payload}"
        except WindowsRuntimeError as exc:
            last_error = str(exc)
            if "HTTP 401" in last_error:
                raise RuntimeError(f"Windows runtime unauthorized at {runtime_url}. Check --runtime-token.") from exc
            # Compatibility fallback for runtimes exposing /probe but not /health.
            if (("HTTP 404" in last_error) or ("404 Not Found" in last_error)) and "/health" in last_error:
                try:
                    probe = checker._request_json("GET", "/probe")  # noqa: SLF001 - intentional compatibility path
                    probe_status = str(probe.get("status", "")).lower()
                    probe_message = str(probe.get("message", "")).lower()
                    if "probe" in probe_status or "operational" in probe_message:
                        return
                    last_error = f"unexpected probe payload: {probe}"
                except WindowsRuntimeError as probe_exc:
                    last_error = f"{last_error}; probe fallback failed: {probe_exc}"
        time.sleep(poll_interval_seconds)
    raise RuntimeError(
        f"Windows runtime not ready within {int(timeout_seconds)}s at {runtime_url} "
        f"(/health plus /run_powershell smoke test). "
        f"Last error: {last_error or 'unknown'}"
    )


class EpisodeRunner(BaseEpisodeRunner):
    """Executes one Windows task episode."""

    def __init__(
        self,
        controller: WindowsRuntimeController,
        llm_client: LLMClientManager,
        model_id: str,
        action_mode: str = "code_adapter",
        observation_mode: str = "screenshot_and_a11y_tree",
        save_trajectory: bool = True,
        output_dir: str = WINDOWS_DEFAULT_EPISODES_DIR,
        history_window: int = 5,
        run_dir: Optional[Path] = None,
        step_settle_seconds: float = 0.3,
        client_password: str | None = None,
        resume_from_trajectory: Optional[Path] = None,
        skip_initialization: bool = False,
    ):
        super().__init__(
            controller=controller,
            llm_client=llm_client,
            model_id=model_id,
            action_mode=action_mode,
            observation_mode=observation_mode,
            save_trajectory=save_trajectory,
            output_dir=output_dir,
            prompt_builder_cls=WindowsPromptBuilder,
            history_window=history_window,
            run_dir=run_dir,
            step_settle_seconds=step_settle_seconds,
            client_password=client_password,
            logger_obj=logger,
            resume_from_trajectory=resume_from_trajectory,
            skip_initialization=skip_initialization,
        )

    def _observe(self, *, include_ui_tree: bool = True, include_screenshot: bool = True) -> Observation:
        return self.controller.observe(
            include_ui_tree=include_ui_tree,
            include_screenshot_data=include_screenshot,
        )

    def _max_runtime_recoveries_per_step(self) -> int:
        raw = os.environ.get("HELLOWORLD_WINDOWS_STEP_RUNTIME_RECOVERIES", "2")
        try:
            return max(0, int(raw))
        except ValueError:
            logger.warning("Ignoring invalid HELLOWORLD_WINDOWS_STEP_RUNTIME_RECOVERIES=%r; using 2", raw)
            return 2

    def _is_recoverable_runtime_error(self, error: Exception | str) -> bool:
        text = str(error or "").lower()
        if not text:
            return False
        has_endpoint = any(marker in text for marker in WINDOWS_RUNTIME_ENDPOINT_MARKERS)
        has_transport_error = any(marker in text for marker in WINDOWS_RUNTIME_INFRA_ERROR_MARKERS)
        return has_endpoint and has_transport_error

    def _recover_runtime_after_error(
        self,
        *,
        phase: str,
        current_step: int,
        error: Exception | str,
    ) -> bool:
        timeout_raw = os.environ.get("HELLOWORLD_WINDOWS_STEP_RECOVERY_READY_TIMEOUT", "75")
        try:
            timeout_seconds = max(1.0, float(timeout_raw))
        except ValueError:
            logger.warning(
                "Ignoring invalid HELLOWORLD_WINDOWS_STEP_RECOVERY_READY_TIMEOUT=%r; using 75",
                timeout_raw,
            )
            timeout_seconds = 75.0

        self._logger.warning(
            "[Step %d] Windows runtime transport failure during %s; waiting up to %.0fs for passive recovery: %s",
            current_step,
            phase,
            timeout_seconds,
            error,
        )
        try:
            wait_for_runtime_ready(
                self.controller.runtime_url,
                self.controller.token,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=1.0,
            )
            self._logger.warning("[Step %d] Windows runtime recovered after %s failure.", current_step, phase)
            return True
        except Exception as recovery_exc:
            self._logger.warning(
                "[Step %d] Passive Windows runtime recovery failed after %s failure: %s",
                current_step,
                phase,
                recovery_exc,
            )
        return self._restart_guest_runtime_and_wait(phase=phase, current_step=current_step)

    def _runtime_host_from_controller(self) -> str:
        parsed = urlparse(self.controller.runtime_url)
        return str(parsed.hostname or "").strip()

    def _restart_guest_runtime_and_wait(self, *, phase: str, current_step: int) -> bool:
        try:
            config = load_windows_runtime_config(WINDOWS_RUNTIME_CONFIG_PATH)
        except Exception as exc:
            self._logger.error(
                "[Step %d] Cannot load Windows runtime config for guest runtime restart after %s: %s",
                current_step,
                phase,
                exc,
            )
            return False

        if str(config.vm_provider or "").strip().lower() != "vmware":
            self._logger.error(
                "[Step %d] Guest runtime restart requires vm_provider=vmware; configured provider=%r",
                current_step,
                config.vm_provider,
            )
            return False
        if not config.vm_path or not config.vm_guest_username or not config.vm_guest_password:
            self._logger.error(
                "[Step %d] Guest runtime restart requires vm_path, vm_guest_username, and vm_guest_password.",
                current_step,
            )
            return False

        runtime_host = self._runtime_host_from_controller() or config.vm_ip
        if not runtime_host:
            self._logger.error("[Step %d] Cannot infer Windows runtime host for guest restart.", current_step)
            return False

        bootstrap_timeout_raw = os.environ.get("HELLOWORLD_WINDOWS_STEP_RECOVERY_BOOTSTRAP_TIMEOUT", "120")
        try:
            bootstrap_timeout = max(30.0, float(bootstrap_timeout_raw))
        except ValueError:
            self._logger.warning(
                "Ignoring invalid HELLOWORLD_WINDOWS_STEP_RECOVERY_BOOTSTRAP_TIMEOUT=%r; using 120",
                bootstrap_timeout_raw,
            )
            bootstrap_timeout = 120.0

        self._logger.warning(
            "[Step %d] Attempting VMware guest runtime restart after %s failure at http://%s:%d ...",
            current_step,
            phase,
            runtime_host,
            config.runtime_port,
        )
        try:
            provider = VMwareWindowsVMProvider(vm_password=config.vm_password)
            ensure_windows_guest_runtime(
                config,
                provider=provider,
                vm_path=str(config.vm_path),
                runtime_host=runtime_host,
                logger_obj=self._logger,
            )
            wait_for_runtime_ready(
                self.controller.runtime_url,
                self.controller.token,
                timeout_seconds=bootstrap_timeout,
                poll_interval_seconds=1.0,
            )
            self._logger.warning(
                "[Step %d] VMware guest runtime restart succeeded after %s failure.",
                current_step,
                phase,
            )
            return True
        except (WindowsVMError, Exception) as exc:
            self._logger.error(
                "[Step %d] VMware guest runtime restart failed after %s failure: %s",
                current_step,
                phase,
                exc,
            )
            return False

    def _run_task_evaluation(
        self,
        *,
        task,
        final_observation,
        run_dir: Path,
        trajectory_path: Optional[Path],
    ):
        first = run_task_evaluation(
            task=task,
            controller=self.controller,
            final_observation=final_observation,
            model_id=self.model_id,
            run_dir=run_dir,
            trajectory_path=trajectory_path,
            logger_obj=self._logger,
        )
        if first is None:
            return None
        result = first.result
        message = str(getattr(result, "message", "") or "")
        if result.status != EvalStatus.ERROR or not self._is_recoverable_runtime_error(message):
            return first

        self._logger.warning("Evaluator hit a recoverable Windows runtime error; restarting guest runtime and retrying evaluator once.")
        if not self._restart_guest_runtime_and_wait(phase="evaluation", current_step=-1):
            return first

        retry = run_task_evaluation(
            task=task,
            controller=self.controller,
            final_observation=final_observation,
            model_id=self.model_id,
            run_dir=run_dir,
            trajectory_path=trajectory_path,
            logger_obj=self._logger,
        )
        if retry is None:
            return first

        metadata = dict(retry.summary.get("metadata") or {})
        metadata["retried_after_runtime_restart"] = True
        retry_summary = dict(retry.summary)
        retry_summary["metadata"] = metadata
        retry_result = EvalResult(
            status=retry.result.status,
            message=retry.result.message,
            metadata=metadata,
        )
        return EvaluationRunResult(result=retry_result, summary=retry_summary)

    def _reflection_pyautogui_planner_cls(self):
        return ReflectionPyAutoGUIPlanner

    @property
    def platform_name(self) -> str:
        return "windows"

    def _build_observation_addition_info(self, observation: Observation) -> dict[str, object]:
        return {
            "width": observation.width,
            "height": observation.height,
            "foreground_app": observation.foreground_app,
            "foreground_bundle_id": observation.foreground_bundle_id,
            "foreground_window": observation.foreground_window,
        }

    def _initialize_task(self, task: Task, run_dir: Path):
        first = run_task_initialization(
            task=task,
            controller=self.controller,
            model_id=self.model_id,
            run_dir=run_dir,
            logger_obj=logger,
        )
        if first is None:
            return None
        status = str(first.result.status.value if hasattr(first.result.status, "value") else first.result.status)
        message = str(first.result.message or "")
        if status != "ERROR" or not self._is_recoverable_runtime_error(message):
            return first

        self._logger.warning(
            "Initializer hit a recoverable Windows runtime error; recovering runtime and retrying initializer once: %s",
            message,
        )
        recovered = self._recover_runtime_after_error(
            phase="initializer",
            current_step=0,
            error=message,
        )
        if not recovered:
            return first

        retry = run_task_initialization(
            task=task,
            controller=self.controller,
            model_id=self.model_id,
            run_dir=run_dir,
            logger_obj=logger,
        )
        if retry is None:
            return first
        retry_summary = dict(retry.summary)
        metadata = dict(retry_summary.get("metadata") or {})
        metadata["retried_after_runtime_recovery"] = True
        retry_summary["metadata"] = metadata
        return InitializationRunResult(result=retry.result, summary=retry_summary)


def run_benchmark_task_command(args) -> int:
    from platforms.windows.core.types import create_simple_task, load_task_from_file

    output_dir = os.environ.get(WINDOWS_OUTPUT_DIR_ENV, WINDOWS_DEFAULT_EPISODES_DIR)
    model_id = str(args.model or "").strip()
    if not model_id:
        raise ValueError("--model cannot be empty")

    task_file = getattr(args, "task_file", None)
    goal = getattr(args, "goal", None)
    if task_file:
        task = load_task_from_file(task_file)
    elif goal:
        task = create_simple_task(
            task_id=f"custom_{datetime.now().strftime('%H%M%S')}",
            goal=goal,
            max_steps=args.max_steps if args.max_steps is not None else 30,
            step_timeout_seconds=args.timeout if args.timeout is not None and args.timeout > 0 else 300,
        )
    else:
        raise ValueError("Must provide either --task-file or --goal")

    if args.max_steps is not None:
        task.max_steps = args.max_steps
    if args.timeout is not None:
        task.step_timeout_seconds = args.timeout
    history_window = int(getattr(args, "history_window", 5))
    if history_window <= 0:
        raise ValueError("--history-window must be a positive integer")
    observation_mode = str(getattr(args, "observation_mode", "screenshot_and_a11y_tree")).strip()
    client_password = str(getattr(args, "vm_guest_password", "") or "").strip() or None

    run_dir = Path(output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_run_args_snapshot(
        run_dir,
        platform="windows",
        task=task,
        model_id=model_id,
        action_mode=args.action_mode,
        observation_mode=observation_mode,
        history_window=history_window,
        execution_file=getattr(args, "execution_file", None),
        platform_config_path=WINDOWS_RUNTIME_CONFIG_PATH,
    )

    logger.info("Output Dir: %s", run_dir)
    logger.info("Task ID: %s", task.id)
    logger.info("Goal: %s", task.goal)
    logger.info("Max Steps: %d", task.max_steps)
    logger.info("Step Timeout: %ss", getattr(task, "step_timeout_seconds", None))
    logger.info("Model: %s", model_id)
    logger.info("Action Mode: %s", args.action_mode)
    logger.info("Observation Mode: %s", observation_mode)
    logger.info("History Window: %d", history_window)
    logger.info("Runtime: %s:%d", args.vm_ip, int(args.runtime_port))
    resume_from_trajectory = getattr(args, "resume_from_trajectory", None)
    skip_initialization = bool(getattr(args, "skip_initialization", False))
    if resume_from_trajectory:
        logger.info("Resume Trajectory: %s", resume_from_trajectory)
        logger.info("Skip Initialization: %s", skip_initialization)

    runtime_url = build_runtime_url(args.vm_ip, args.runtime_port)
    logger.info("Waiting for runtime readiness: %s ...", runtime_url)
    wait_for_runtime_ready(runtime_url, str(args.runtime_token))

    controller = build_controller_from_args(args)
    llm_client = LLMClientManager.from_default_models_yaml()

    runner = EpisodeRunner(
        controller=controller,
        llm_client=llm_client,
        model_id=model_id,
        action_mode=args.action_mode,
        observation_mode=observation_mode,
        save_trajectory=True,
        history_window=history_window,
        output_dir=output_dir,
        run_dir=run_dir,
        client_password=client_password,
        resume_from_trajectory=Path(resume_from_trajectory) if resume_from_trajectory else None,
        skip_initialization=skip_initialization,
    )

    result = runner.run_episode(task)
    if result.success:
        logger.info("✓ Task completed successfully in %d steps", result.steps_taken)
    else:
        logger.error("✗ Task failed: %s", result.failure_message)
        logger.error("Status: %s", result.status)
    return 0 if result.success else 1


run_task_command = run_benchmark_task_command
