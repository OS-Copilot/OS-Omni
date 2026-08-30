"""Episode execution engine for iOSWorld benchmark."""

import logging
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.artifacts.run_args import write_run_args_snapshot
from core.llm.llm_client import LLMClientManager

from platforms.ios.agent.prompt_builder import IOSPromptBuilder
from platforms.ios.runners.base_episode import BaseEpisodeRunner
from platforms.ios.runners.initialization import run_task_initialization

from platforms.ios.core.types import EpisodeResult, Task
from platforms.ios.runtime_config import IOS_RUNTIME_CONFIG_PATH
from platforms.ios.runtime_env.controller import Observation, iOSController

IOS_PLATFORM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
IOS_DEFAULT_RUN_DIR = os.getenv(
    "IOSWORLD_OUTPUT_DIR",
    str(REPO_ROOT / "results" / "ios" / "run"),
)

logger = logging.getLogger(__name__)


def _build_appium_server_url(host: str, port: int) -> str:
    """Build Appium server URL from validated host/port."""
    return f"http://{host}:{int(port)}"


def _find_free_tcp_port(host: str = "127.0.0.1") -> int:
    """Ask the OS for a currently free localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _build_wda_runtime_options(udid: str, run_dir: Optional[Path] = None) -> dict[str, object]:
    """Generate isolated WDA/Appium runtime options for one simulator session."""
    safe_udid = (udid or "").strip() or "unknown_udid"
    if run_dir is not None:
        derived_data_path = run_dir / "wda_derived_data"
    else:
        derived_data_path = REPO_ROOT / "results" / "ios" / "wda_derived_data" / safe_udid
    derived_data_path.mkdir(parents=True, exist_ok=True)
    return {
        "wda_local_port": _find_free_tcp_port(),
        "mjpeg_server_port": _find_free_tcp_port(),
        "derived_data_path": str(derived_data_path),
    }


class EpisodeRunner(BaseEpisodeRunner):
    """Executes one task episode from initialization to terminal state."""

    def __init__(
        self,
        controller: iOSController,
        llm_client: LLMClientManager,
        model_id: str,
        action_mode: str = "code_adapter",
        observation_mode: str = "screenshot_and_a11y_tree",
        save_trajectory: bool = True,
        output_dir: str = IOS_DEFAULT_RUN_DIR,
        history_window: int = 5,
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
            prompt_builder_cls=IOSPromptBuilder,
            history_window=history_window,
            run_dir=run_dir,
            step_settle_seconds=step_settle_seconds,
            logger_obj=logger,
        )

    def _observe(self, *, include_ui_tree: bool = True, include_screenshot: bool = True) -> Observation:
        return self.controller.observe(include_ui_tree=include_ui_tree)

    @property
    def platform_name(self) -> str:
        return "ios"

    def _should_attach_image(self, screenshot_path: str) -> bool:
        return bool(screenshot_path)

    def _build_observation_addition_info(self, observation: Observation) -> dict[str, object]:
        return {
            "width": observation.width,
            "height": observation.height,
            "viewport_rect": dict(observation.viewport_rect),
            "foreground_bundle_id": observation.foreground_bundle_id,
            "device_info": dict(observation.device_info),
            "is_keyboard_shown": observation.is_keyboard_shown,
        }

    def _initialize_task(self, task: Task, run_dir: Path):
        return run_task_initialization(
            task=task,
            controller=self.controller,
            model_id=self.model_id,
            run_dir=run_dir,
            logger_obj=logger,
        )

def run_single_task(
    task: Task,
    udid: str,
    model: str = "gpt5_4",
    action_mode: str = "code_adapter",
    observation_mode: str = "screenshot_and_a11y_tree",
    history_window: int = 5,
    output_dir: str = IOS_DEFAULT_RUN_DIR,
    appium_host: str = "127.0.0.1",
    appium_port: int = 4723,
) -> EpisodeResult:
    """Convenience wrapper for running a single task episode."""
    if not udid:
        raise ValueError("udid is required for run_single_task in simulator-only mode")
    if not str(appium_host).strip():
        raise ValueError("appium_host must be a non-empty string")
    if int(appium_port) <= 0:
        raise ValueError("appium_port must be a positive integer")
    model_id = str(model or "").strip()
    if not model_id:
        raise ValueError("model cannot be empty")

    controller = iOSController(
        server_url=_build_appium_server_url(str(appium_host).strip(), appium_port),
        udid=udid,
        **_build_wda_runtime_options(udid),
    )

    llm_client = LLMClientManager.from_default_models_yaml()

    runner = EpisodeRunner(
        controller=controller,
        llm_client=llm_client,
        model_id=model_id,
        action_mode=action_mode,
        observation_mode=observation_mode,
        history_window=history_window,
        output_dir=output_dir,
    )

    try:
        result = runner.run_episode(task)
    finally:
        controller.quit()

    return result


def run_benchmark_job_command(args) -> int:
    """Internal CLI handler: execute one benchmark job task."""
    from platforms.ios.core.types import create_simple_task, load_task_from_file

    if args.task_file:
        task = load_task_from_file(args.task_file)
    elif args.goal:
        task = create_simple_task(
            task_id=args.task_id or f"custom_{datetime.now().strftime('%H%M%S')}",
            goal=args.goal,
            max_steps=args.max_steps if args.max_steps is not None else 30,
            step_timeout_seconds=args.timeout if args.timeout is not None and args.timeout > 0 else 300,
        )
    else:
        raise ValueError("Must provide either --task-file or --goal")

    if args.max_steps is not None:
        task.max_steps = args.max_steps
    if args.timeout is not None:
        task.step_timeout_seconds = args.timeout
    appium_host = str(getattr(args, "appium_host", "127.0.0.1")).strip()
    if not appium_host:
        raise ValueError("--appium-host must be a non-empty string")
    if int(args.appium_port) <= 0:
        raise ValueError("--appium-port must be a positive integer")
    history_window = int(getattr(args, "history_window", 5))
    if history_window <= 0:
        raise ValueError("--history-window must be a positive integer")
    observation_mode = str(getattr(args, "observation_mode", "screenshot_and_a11y_tree")).strip()

    output_dir = os.getenv("IOSWORLD_OUTPUT_DIR", IOS_DEFAULT_RUN_DIR)
    model_id = str(args.model or "").strip()
    if not model_id:
        raise ValueError("--model cannot be empty")
    run_dir = Path(output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_run_args_snapshot(
        run_dir,
        platform="ios",
        task=task,
        model_id=model_id,
        action_mode=args.action_mode,
        observation_mode=observation_mode,
        history_window=history_window,
        execution_file=getattr(args, "execution_file", None),
        platform_config_path=IOS_RUNTIME_CONFIG_PATH,
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
    logger.info("Device: simulator")
    logger.info("Appium Host: %s", appium_host)
    logger.info("Appium Port: %d", int(args.appium_port))

    if not args.udid:
        raise ValueError("--udid is required for simulator runs")

    controller = None
    try:
        wda_runtime_options = _build_wda_runtime_options(args.udid, run_dir)
        logger.info(
            "WDA Runtime: wdaLocalPort=%s mjpegServerPort=%s derivedDataPath=%s",
            wda_runtime_options["wda_local_port"],
            wda_runtime_options["mjpeg_server_port"],
            wda_runtime_options["derived_data_path"],
        )
        controller = iOSController(
            server_url=_build_appium_server_url(
                appium_host,
                args.appium_port,
            ),
            udid=args.udid,
            **wda_runtime_options,
        )
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
    finally:
        if controller is not None:
            controller.quit()


def run_task_command(args) -> int:
    """Backward-compatible alias for internal imports."""
    return run_benchmark_job_command(args)
