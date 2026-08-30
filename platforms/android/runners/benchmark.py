"""Android benchmark runner.

Coordinates emulator lifecycle, task execution, and result collection
for a single task × model combination.

Uses the EpisodeRunner for the full LLM-powered agent step loop:
  init → [observe → LLM decide → execute action → repeat] → eval
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.llm.llm_client import LLMClientManager

from platforms.android.controller import AdbController
from platforms.android.core.types import load_task_from_file
from platforms.android.device_stability import wait_for_device_stable
from platforms.android.runners.episode import EpisodeRunner

logger = logging.getLogger(__name__)


def run_benchmark(
    *,
    task_path: Path,
    model_id: str,
    adb_device: str,
    run_dir: Path,
    action_mode: str = "code_adapter",
    observation_mode: str = "screenshot_and_a11y_tree",
    history_window: int = 5,
    max_steps: Optional[int] = None,
    timeout: Optional[int] = None,
) -> int:
    """Run a single Android benchmark episode with the full LLM agent loop."""

    if str(action_mode).strip() != "code_adapter":
        raise ValueError("action_mode must be code_adapter")

    run_dir.mkdir(parents=True, exist_ok=True)

    # Load task via the core types system (proper Task dataclass)
    task = load_task_from_file(str(task_path))

    # Apply overrides
    if max_steps is not None:
        task.max_steps = max_steps
    if timeout is not None:
        task.step_timeout_seconds = timeout

    logger.info("=" * 60)
    logger.info("Android Benchmark: %s", task.id)
    logger.info("Model: %s | Device: %s", model_id, adb_device)
    logger.info(
        "Max steps: %d | Step timeout: %s",
        task.max_steps,
        f"{task.step_timeout_seconds}s" if getattr(task, "step_timeout_seconds", None) is not None else "none",
    )
    logger.info("Action mode: %s | Observation mode: %s", action_mode, observation_mode)
    logger.info("=" * 60)

    # Build controller
    controller = AdbController(adb_device=adb_device)
    stability = wait_for_device_stable(controller)
    logger.info("Device stability preflight: %s", stability)

    # Check health
    health = controller.health()
    if health.get("status") != "HEALTHY":
        logger.error("Device not healthy: %s", health)
        _save_error_result(run_dir, task.id, model_id, "Device not reachable")
        return 1
    controller.disable_touch_debug_overlays()

    # Build LLM client
    try:
        llm_client = LLMClientManager.from_default_models_yaml()
    except Exception as exc:
        logger.error("Failed to initialize LLM client: %s", exc)
        _save_error_result(run_dir, task.id, model_id, f"LLM client init failed: {exc}")
        return 1

    # Build and run the episode runner (full step loop)
    runner = EpisodeRunner(
        controller=controller,
        llm_client=llm_client,
        model_id=model_id,
        action_mode=action_mode,
        observation_mode=observation_mode,
        save_trajectory=True,
        output_dir=str(run_dir.parent),
        history_window=history_window,
        run_dir=run_dir,
        step_settle_seconds=0.5,
    )

    result = runner.run_episode(task)

    if result.success:
        logger.info("✓ Task completed successfully in %d steps", result.steps_taken)
    else:
        logger.error("✗ Task failed: %s", result.failure_message)
        logger.error("Status: %s", result.status)

    return 0 if result.success else 1


def _save_error_result(
    run_dir: Path,
    task_id: str,
    model_id: str,
    message: str,
) -> None:
    """Save an error result when the runner couldn't even start."""
    result = {
        "task_id": task_id,
        "model_id": model_id,
        "platform": "android",
        "status": "ERROR",
        "message": message,
        "elapsed_seconds": 0.0,
        "timestamp": datetime.now().isoformat(),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "result.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info("Error result saved to %s", run_dir)
