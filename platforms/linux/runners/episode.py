"""
Episode execution engine for Linux benchmark.
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.artifacts.run_args import write_run_args_snapshot
from core.llm.llm_client import LLMClientManager

from platforms.linux.agent.prompt_builder import LinuxPromptBuilder
from platforms.linux.runners.base_episode import BaseEpisodeRunner
from platforms.linux.runners.initialization import run_task_initialization

from platforms.linux.core.types import Task
from platforms.linux.runtime_config import LINUX_RUNTIME_CONFIG_PATH
from platforms.linux.runtime_env.controller import LinuxRuntimeController, LinuxRuntimeError, Observation

logger = logging.getLogger(__name__)

LINUX_PLATFORM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
LINUX_DEFAULT_EPISODES_DIR = str(REPO_ROOT / "results" / "linux" / "episodes")
LINUX_OUTPUT_DIR_ENV = "LINUX_OUTPUT_DIR"
RUNTIME_READY_TIMEOUT_SECONDS = 30.0
RUNTIME_READY_POLL_INTERVAL_SECONDS = 1.0
CONTROLLER_TIMEOUT_SECONDS = 20.0


def build_runtime_url(vm_ip: str, runtime_port: int) -> str:
    ip = (vm_ip or "").strip()
    if not ip:
        raise ValueError("--vm-ip is required")
    if "://" in ip:
        raise ValueError("--vm-ip should be an IP/host without scheme")
    return f"http://{ip}:{int(runtime_port)}"


def build_controller_from_args(args):
    runtime_url = build_runtime_url(args.vm_ip, args.runtime_port)
    logger.info("Controller: linux-runtime (%s)", runtime_url)
    return LinuxRuntimeController(
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
    checker = LinuxRuntimeController(runtime_url=runtime_url, token=token, timeout=5.0)
    start = time.time()
    last_error = None
    while time.time() - start < timeout_seconds:
        try:
            payload = checker.health()
            status = str(payload.get("status", "")).upper()
            if status == "HEALTHY":
                return
            last_error = f"unexpected health status: {status or payload}"
        except LinuxRuntimeError as exc:
            last_error = str(exc)
            if "HTTP 401" in last_error:
                raise RuntimeError(f"Linux runtime unauthorized at {runtime_url}. Check --runtime-token.") from exc
        time.sleep(poll_interval_seconds)
    raise RuntimeError(
        f"Linux runtime not ready within {int(timeout_seconds)}s at {runtime_url}. "
        f"Last error: {last_error or 'unknown'}"
    )


class EpisodeRunner(BaseEpisodeRunner):
    """Executes one Linux task episode."""

    def __init__(
        self,
        controller: LinuxRuntimeController,
        llm_client: LLMClientManager,
        model_id: str,
        action_mode: str = "code_adapter",
        observation_mode: str = "screenshot_only",
        save_trajectory: bool = True,
        output_dir: str = LINUX_DEFAULT_EPISODES_DIR,
        history_window: int = 5,
        run_dir: Optional[Path] = None,
        step_settle_seconds: float = 0.3,
        client_password: str | None = None,
    ):
        super().__init__(
            controller=controller,
            llm_client=llm_client,
            model_id=model_id,
            action_mode=action_mode,
            observation_mode=observation_mode,
            save_trajectory=save_trajectory,
            output_dir=output_dir,
            prompt_builder_cls=LinuxPromptBuilder,
            history_window=history_window,
            run_dir=run_dir,
            step_settle_seconds=step_settle_seconds,
            client_password=client_password,
            logger_obj=logger,
        )

    def _observe(self, *, include_ui_tree: bool = True, include_screenshot: bool = True) -> Observation:
        return self.controller.observe(
            include_ui_tree=include_ui_tree,
            include_screenshot_data=include_screenshot,
        )

    @property
    def platform_name(self) -> str:
        return "linux"

    def _build_observation_addition_info(self, observation: Observation) -> dict[str, object]:
        return {
            "width": observation.width,
            "height": observation.height,
            "foreground_app": observation.foreground_app,
            "foreground_bundle_id": observation.foreground_bundle_id,
            "foreground_window": observation.foreground_window,
        }

    def _initialize_task(self, task: Task, run_dir: Path):
        return run_task_initialization(
            task=task,
            controller=self.controller,
            model_id=self.model_id,
            run_dir=run_dir,
            logger_obj=logger,
        )


def run_benchmark_task_command(args) -> int:
    from platforms.linux.core.types import create_simple_task, load_task_from_file

    output_dir = os.environ.get(LINUX_OUTPUT_DIR_ENV, LINUX_DEFAULT_EPISODES_DIR)
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
            step_timeout_seconds=args.timeout if args.timeout is not None and args.timeout > 0 else 120,
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
    observation_mode = str(getattr(args, "observation_mode", "screenshot_only")).strip()
    client_password = str(getattr(args, "vm_guest_password", "") or "").strip() or None

    run_dir = Path(output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_run_args_snapshot(
        run_dir,
        platform="linux",
        task=task,
        model_id=model_id,
        action_mode=args.action_mode,
        observation_mode=observation_mode,
        history_window=history_window,
        execution_file=getattr(args, "execution_file", None),
        platform_config_path=LINUX_RUNTIME_CONFIG_PATH,
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
    )

    result = runner.run_episode(task)
    if result.success:
        logger.info("✓ Task completed successfully in %d steps", result.steps_taken)
    else:
        logger.error("✗ Task failed: %s", result.failure_message)
        logger.error("Status: %s", result.status)
    return 0 if result.success else 1


run_task_command = run_benchmark_task_command
