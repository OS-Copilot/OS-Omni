"""
Episode execution engine for Android benchmark.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.artifacts.run_args import write_run_args_snapshot
from core.llm.llm_client import LLMClientManager

from platforms.android.agent.prompt_builder import AndroidPromptBuilder
from platforms.android.runners.base_episode import BaseEpisodeRunner
from platforms.android.runners.initialization import run_task_initialization

from platforms.android.core.types import Task
from platforms.android.runtime_config import ANDROID_RUNTIME_CONFIG_PATH
from platforms.android.controller import AdbController, Observation
from platforms.android.device_stability import wait_for_device_stable

logger = logging.getLogger(__name__)

ANDROID_PLATFORM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
ANDROID_DEFAULT_EPISODES_DIR = str(REPO_ROOT / "results" / "android" / "episodes")
ANDROID_OUTPUT_DIR_ENV = "ANDROID_OUTPUT_DIR"


class EpisodeRunner(BaseEpisodeRunner):
    """Executes one Android task episode."""

    def __init__(
        self,
        controller: AdbController,
        llm_client: LLMClientManager,
        model_id: str,
        action_mode: str = "code_adapter",
        observation_mode: str = "screenshot_and_a11y_tree",
        save_trajectory: bool = True,
        output_dir: str = ANDROID_DEFAULT_EPISODES_DIR,
        history_window: int = 5,
        run_dir: Optional[Path] = None,
        step_settle_seconds: float = 0.5,
    ):
        super().__init__(
            controller=controller,
            llm_client=llm_client,
            model_id=model_id,
            action_mode=action_mode,
            observation_mode=observation_mode,
            save_trajectory=save_trajectory,
            output_dir=output_dir,
            prompt_builder_cls=AndroidPromptBuilder,
            history_window=history_window,
            run_dir=run_dir,
            step_settle_seconds=step_settle_seconds,
            logger_obj=logger,
        )

    def _observe(self, *, include_ui_tree: bool = True, include_screenshot: bool = True) -> Observation:
        """Read current environment observation via ADB.

        Returns an Observation dataclass that BaseEpisodeRunner can use
        (it has .ui_nodes, .width, .height, etc.).
        """
        # BaseEpisodeRunner captures and attaches the actual screenshot via
        # controller.save_screenshot(). Avoid taking a second unused screenshot
        # here, which can race with other ADB clients and confuse debugging.
        return self.controller.observe(
            include_ui_tree=include_ui_tree,
            include_screenshot_data=False,
        )

    @property
    def platform_name(self) -> str:
        return "android"

    def _build_observation_addition_info(self, observation: Observation) -> Dict[str, Any]:
        return {
            "width": observation.width,
            "height": observation.height,
            "foreground_app": observation.foreground_app,
            "foreground_bundle_id": observation.foreground_bundle_id,
            "foreground_window": observation.foreground_window,
        }

    def _initialize_task(self, task: Task, run_dir: Path):
        stability = wait_for_device_stable(self.controller)
        logger.info("Device stability before initializer: %s", stability)
        return run_task_initialization(
            task=task,
            controller=self.controller,
            model_id=self.model_id,
            run_dir=run_dir,
            logger_obj=logger,
        )


def run_benchmark_task_command(args) -> int:
    from platforms.android.core.types import create_simple_task, load_task_from_file

    output_dir = os.environ.get(ANDROID_OUTPUT_DIR_ENV, ANDROID_DEFAULT_EPISODES_DIR)
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
            max_steps=args.max_steps if args.max_steps is not None else 15,
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

    run_dir = Path(output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_run_args_snapshot(
        run_dir,
        platform="android",
        task=task,
        model_id=model_id,
        action_mode=args.action_mode,
        observation_mode=observation_mode,
        history_window=history_window,
        execution_file=getattr(args, "execution_file", None),
        platform_config_path=ANDROID_RUNTIME_CONFIG_PATH,
    )

    logger.info("Output Dir: %s", run_dir)
    logger.info("Task ID: %s", task.id)
    logger.info("Goal: %s", task.goal)
    logger.info("Max Steps: %d", task.max_steps)
    logger.info("Step Timeout: %s", f"{task.step_timeout_seconds}s" if task.step_timeout_seconds is not None else "none")
    logger.info("Model: %s", model_id)
    logger.info("Action Mode: %s", args.action_mode)
    logger.info("Observation Mode: %s", observation_mode)
    logger.info("History Window: %d", history_window)
    logger.info("ADB Device: %s", args.adb_device)

    controller = AdbController(adb_device=args.adb_device)
    health = controller.health()
    if health.get("status") != "HEALTHY":
        logger.error("Device not reachable: %s", health)
        return 1
    controller.disable_touch_debug_overlays()

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
    )

    result = runner.run_episode(task)
    if result.success:
        logger.info("✓ Task completed successfully in %d steps", result.steps_taken)
    else:
        logger.error("✗ Task failed: %s", result.failure_message)
        logger.error("Status: %s", result.status)
    return 0 if result.success else 1


run_task_command = run_benchmark_task_command
