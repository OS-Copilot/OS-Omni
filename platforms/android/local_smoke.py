#!/usr/bin/env python3
"""Run an offline smoke test for the Android platform.

This script starts a local smoke execution against a connected emulator,
verifying the init → eval pipeline without requiring a real LLM API key.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_EXECUTION_PATH = REPO_ROOT / "executions" / "android_test_1.yaml"

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Run a local Android smoke test against a connected emulator.",
    )
    parser.add_argument(
        "--execution",
        default=str(DEFAULT_EXECUTION_PATH),
        help="Path to execution YAML file. Defaults to android_test_1.yaml.",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help="Run a specific task YAML file instead of the full execution.",
    )
    args = parser.parse_args(argv)

    import os
    os.environ.setdefault("HELLOWORLD_MOCK_API_KEY", "local-smoke-token")
    os.environ.setdefault("HELLOWORLD_SCRIPTED_API_KEY", "local-scripted-token")

    from platforms.android.controller import AdbController
    from platforms.android.runtime_config import load_android_runtime_config

    # Load config
    config = load_android_runtime_config()
    controller = AdbController(adb_device=config.adb_device)

    # Health check
    health = controller.health()
    if health.get("status") != "HEALTHY":
        logger.error("No Android device/emulator connected!")
        logger.error("Device state: %s", health)
        logger.info("")
        logger.info("To fix this, either:")
        logger.info("  1. Start AndroidWorldAvd emulator manually")
        logger.info("  2. Connect a device via USB")
        logger.info("  3. Run: emulator -avd AndroidWorldAvd")
        return 1

    logger.info("Device is HEALTHY (%s)", config.adb_device)

    if args.task:
        # Run a single task
        from platforms.android.runners.benchmark import run_benchmark
        task_path = Path(args.task)
        if not task_path.is_absolute():
            task_path = (REPO_ROOT / task_path).resolve()

        run_dir = REPO_ROOT / "results" / "smoke" / "android" / task_path.stem
        return run_benchmark(
            task_path=task_path,
            model_id="smoke_test",
            adb_device=config.adb_device,
            run_dir=run_dir,
        )
    else:
        # Run full execution
        logger.info("Running full execution: %s", args.execution)
        result = __import__("subprocess").run(
            [
                sys.executable, "-m", "platforms.android.cli",
                "--execution", args.execution,
            ],
            cwd=str(REPO_ROOT),
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
