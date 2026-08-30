# episode_runner.py
"""
Episode execution engine for macOS benchmark.
Orchestrates the complete episode lifecycle from initialization to completion.
"""

import io
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.benchmark_policy import DEFAULT_PROMPT_PROFILE, normalize_prompt_profile
from core.artifacts.run_args import write_run_args_snapshot
from core.llm.llm_client import LLMClientManager

from platforms.macos.host.agent.prompt_builder import MacOSPromptBuilder
from platforms.macos.host.runners.base_episode import BaseEpisodeRunner
from platforms.macos.host.runners.initialization import run_task_initialization

from platforms.macos.host.core.types import EpisodeResult, Task
from platforms.macos.host.runtime_env.vm_manager import create_macos_vm_manager
from platforms.macos.host.runtime_env.vm_runtime_controller import (
    Observation,
    VMRuntimeController,
    VMRuntimeError,
)
from platforms.macos.runtime_config import MACOS_RUNTIME_CONFIG_PATH

logger = logging.getLogger(__name__)

MACOS_PLATFORM_DIR = Path(__file__).resolve().parents[2]
V2_BASE_DIR = Path(__file__).resolve().parents[4]
MACOS_DEFAULT_EPISODES_DIR = str(V2_BASE_DIR / "results" / "macos" / "episodes")
MACOS_EPISODE_OUTPUT_DIR_ENV = "MACOS_OUTPUT_DIR"
MACOS_SKIP_VM_CLONE_ENV = "MACOS_SKIP_VM_CLONE"
RUNTIME_READY_TIMEOUT_SECONDS = 60.0
RUNTIME_READY_POLL_INTERVAL_SECONDS = 1.0
CONTROLLER_TIMEOUT_SECONDS = 20.0
DEFAULT_RUNTIME_SCREEN_WIDTH = 1920
DEFAULT_RUNTIME_SCREEN_HEIGHT = 1080


def _safe_vm_name(raw: str) -> str:
    text = (raw or "").strip() or "task"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text)


def build_runtime_url(vm_ip: str, runtime_port: int) -> str:
    """Build runtime URL from VM IP and runtime port."""
    ip = (vm_ip or "").strip()
    if not ip:
        raise ValueError("--vm-ip is required")
    if "://" in ip:
        raise ValueError("--vm-ip should be an IP/host without scheme, e.g. 192.168.64.4")
    return f"http://{ip}:{int(runtime_port)}"


def build_controller_from_args(args):
    """Build VM runtime controller from CLI args."""
    runtime_url = build_runtime_url(args.vm_ip, args.runtime_port)
    runtime_token = args.vm_token
    logger.info("Controller: vm (%s)", runtime_url)
    return VMRuntimeController(
        runtime_url=runtime_url,
        token=runtime_token,
        timeout=CONTROLLER_TIMEOUT_SECONDS,
    )


def _decode_image_size(image_data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for macOS runtime screenshot smoke checks.") from exc

    try:
        with Image.open(io.BytesIO(image_data)) as image:
            return int(image.width), int(image.height)
    except Exception as exc:
        raise RuntimeError(f"failed to decode screenshot image: {exc}") from exc


def runtime_screen_smoke_check(
    controller: VMRuntimeController,
    *,
    expected_width: int = DEFAULT_RUNTIME_SCREEN_WIDTH,
    expected_height: int = DEFAULT_RUNTIME_SCREEN_HEIGHT,
) -> tuple[bool, str]:
    try:
        observation = controller.observe(include_ui_tree=False, include_screenshot_data=True)
    except VMRuntimeError as exc:
        return False, str(exc)

    if observation.width != expected_width or observation.height != expected_height:
        return (
            False,
            f"runtime reported {observation.width}x{observation.height}; expected {expected_width}x{expected_height}",
        )

    screenshot_data = observation.screenshot_data or b""
    if not screenshot_data:
        return False, "runtime returned no screenshot data"

    try:
        image_width, image_height = _decode_image_size(screenshot_data)
    except RuntimeError as exc:
        return False, str(exc)

    if (image_width, image_height) != (observation.width, observation.height):
        return (
            False,
            "runtime screenshot size "
            f"{image_width}x{image_height} does not match observation metadata "
            f"{observation.width}x{observation.height}",
        )

    if image_width != expected_width or image_height != expected_height:
        return False, f"runtime screenshot is {image_width}x{image_height}; expected {expected_width}x{expected_height}"

    return True, f"runtime screenshot smoke passed at {image_width}x{image_height}"


def wait_for_runtime_ready(
    runtime_url: str,
    token: str,
    timeout_seconds: float = RUNTIME_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = RUNTIME_READY_POLL_INTERVAL_SECONDS,
) -> None:
    """Wait until VM runtime /health is reachable and healthy."""
    checker = VMRuntimeController(
        runtime_url=runtime_url,
        token=token,
        timeout=5.0,
    )
    start = time.time()
    last_error = None
    while time.time() - start < timeout_seconds:
        try:
            payload = checker.health()
            status = str(payload.get("status", "")).upper()
            if status == "HEALTHY":
                screen_ok, screen_detail = runtime_screen_smoke_check(checker)
                if screen_ok:
                    logger.info(screen_detail)
                    return
                last_error = screen_detail
                time.sleep(poll_interval_seconds)
                continue
            last_error = f"unexpected health status: {status or payload}"
        except VMRuntimeError as exc:
            last_error = str(exc)
            if "HTTP 401" in last_error:
                raise RuntimeError(f"VM runtime unauthorized at {runtime_url}. Check --vm-token.") from exc
        time.sleep(poll_interval_seconds)
    raise RuntimeError(
        f"VM runtime not ready within {int(timeout_seconds)}s at {runtime_url}. "
        f"Last error: {last_error or 'unknown'}"
    )


class EpisodeRunner(BaseEpisodeRunner):
    """Executes a complete episode (one task evaluation run)."""

    def __init__(
        self,
        controller: VMRuntimeController,
        llm_client: LLMClientManager,
        model_id: str,
        action_mode: str = "code_adapter",
        observation_mode: str = "screenshot_and_a11y_tree",
        save_trajectory: bool = True,
        output_dir: str = MACOS_DEFAULT_EPISODES_DIR,
        history_window: int = 5,
        prompt_profile: str = DEFAULT_PROMPT_PROFILE,
        run_dir: Optional[Path] = None,
        step_settle_seconds: float = 0.3,
    ):
        super().__init__(
            controller=controller,
            llm_client=llm_client,
            model_id=model_id,
            action_mode=action_mode,
            observation_mode=observation_mode,
            save_trajectory=save_trajectory,
            output_dir=output_dir,
            prompt_builder_cls=MacOSPromptBuilder,
            history_window=history_window,
            prompt_profile=prompt_profile,
            run_dir=run_dir,
            step_settle_seconds=step_settle_seconds,
            logger_obj=logger,
        )

    def _observe(self, *, include_ui_tree: bool = True, include_screenshot: bool = True) -> Observation:
        return self.controller.observe(
            include_ui_tree=include_ui_tree,
            include_screenshot_data=False,
        )

    @property
    def platform_name(self) -> str:
        return "macos"

    def _build_evaluator_context(
        self,
        *,
        task: Task,
        final_observation: Observation | None,
        run_dir: Path,
    ) -> dict[str, Any]:
        evaluation = getattr(task, "evaluation", None)
        params = {}
        if evaluation is not None:
            params = dict(evaluation.params)
        return {
            "task": task,
            "params": params,
            "controller": self.controller,
            "final_observation": final_observation,
            "run_dir": run_dir,
        }

    def _build_observation_addition_info(self, observation: Observation) -> dict[str, object]:
        return {
            "width": observation.width,
            "height": observation.height,
            "foreground_app": observation.foreground_app,
            "foreground_bundle_id": observation.foreground_bundle_id,
        }

    def _initialize_task(self, task: Task, run_dir: Path):
        return run_task_initialization(
            task=task,
            build_context=lambda: {
                "task": task,
                "params": dict(task.init.params) if task.init is not None else {},
                "controller": self.controller,
                "run_dir": run_dir,
            },
            model_id=self.model_id,
            run_dir=run_dir,
            logger_obj=logger,
        )


def run_benchmark_task_command(args) -> int:
    """CLI handler: run one benchmark task episode."""
    from platforms.macos.host.core.types import create_simple_task, load_task_from_file

    output_dir = os.environ.get(MACOS_EPISODE_OUTPUT_DIR_ENV, MACOS_DEFAULT_EPISODES_DIR)
    model_id = str(args.model or "").strip()
    if not model_id:
        raise ValueError("--model cannot be empty")
    skip_vm_clone = os.environ.get(MACOS_SKIP_VM_CLONE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    task_file = getattr(args, "task_file", None)
    goal = getattr(args, "goal", None)
    if task_file:
        task = load_task_from_file(task_file)
    elif goal:
        task = create_simple_task(
            task_id=f"custom_{datetime.now().strftime('%H%M%S')}",
            goal=goal,
            max_steps=args.max_steps if args.max_steps is not None else 100,
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
    observation_mode = str(getattr(args, "observation_mode", "screenshot_and_a11y_tree")).strip()
    prompt_profile = normalize_prompt_profile(getattr(args, "prompt_profile", DEFAULT_PROMPT_PROFILE))

    run_dir = Path(output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_run_args_snapshot(
        run_dir,
        platform="macos",
        task=task,
        model_id=model_id,
        action_mode=args.action_mode,
        observation_mode=observation_mode,
        history_window=history_window,
        prompt_profile=prompt_profile,
        execution_file=getattr(args, "execution_file", None),
        platform_config_path=MACOS_RUNTIME_CONFIG_PATH,
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
    logger.info("Prompt Profile: %s", prompt_profile)
    logger.info("VM IP: %s", args.vm_ip)

    cloned_vm_name = None
    result: Optional[EpisodeResult] = None
    vm_manager = create_macos_vm_manager(getattr(args, "vm_provider", "tart"), tart_home=getattr(args, "tart_home", None)) if not skip_vm_clone else None
    try:
        if not skip_vm_clone:
            if not args.base_vm_name:
                raise ValueError("benchmark task worker requires --base-vm-name")
            assert vm_manager is not None
            if not vm_manager.vm_exists(args.base_vm_name):
                raise ValueError(f"Base VM not found: {args.base_vm_name}")
            clone_name = f"{_safe_vm_name(task.id)}_{int(time.time() * 1000)}"
            prepared = vm_manager.prepare_benchmark_environment(
                base_vm_name=args.base_vm_name,
                clone_name=clone_name,
            )
            if not prepared:
                raise RuntimeError(f"Failed to prepare VM clone from base '{args.base_vm_name}'")
            cloned_vm_name = prepared
            args.vm_ip = vm_manager.resolve_runtime_host(cloned_vm_name, fallback_host=str(args.vm_ip))
            logger.info("Ephemeral VM: %s", cloned_vm_name)
            logger.info("Resolved clone runtime host: %s", args.vm_ip)

        runtime_url = build_runtime_url(args.vm_ip, args.runtime_port)
        runtime_token = args.vm_token
        logger.info("Waiting for runtime readiness: %s ...", runtime_url)
        wait_for_runtime_ready(
            runtime_url,
            runtime_token,
            timeout_seconds=RUNTIME_READY_TIMEOUT_SECONDS,
            poll_interval_seconds=RUNTIME_READY_POLL_INTERVAL_SECONDS,
        )

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
            prompt_profile=prompt_profile,
            output_dir=output_dir,
            run_dir=run_dir,
        )

        result = runner.run_episode(task)
    finally:
        if cloned_vm_name and vm_manager is not None:
            cleanup_ok = vm_manager.cleanup_benchmark_environment(cloned_vm_name)
            if not cleanup_ok:
                logger.warning("cleanup failed for ephemeral VM '%s'", cloned_vm_name)

    if result is None:
        raise RuntimeError("Episode did not produce a result.")

    if result.success:
        logger.info("✓ Task completed successfully in %d steps", result.steps_taken)
    else:
        logger.error("✗ Task failed: %s", result.failure_message)
        logger.error("Status: %s", result.status)

    return 0 if result.success else 1


# Backward compatibility for older imports.
run_task_command = run_benchmark_task_command
