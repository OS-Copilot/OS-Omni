#!/usr/bin/env python3
"""Run one Android task repeatedly with either capped retries or fixed trials."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_repo_env() -> None:
    """Load repo-root .env for parity with platform CLI entrypoints."""
    env_path = REPO_ROOT / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
        return
    except ImportError:
        pass

    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or name in os.environ:
            continue
        os.environ[name] = value.strip().strip('"').strip("'")


_load_repo_env()

from platforms.android.runners.benchmark import run_benchmark  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class AttemptSummary:
    attempt: int
    run_dir: str
    exit_code: int
    status: str
    latency_ms: float | None
    steps_taken: int | None
    started_at: str | None
    ended_at: str | None
    failure_message: str | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repeat one Android task until pass or for a fixed number of trials.",
    )
    parser.add_argument("--task", required=True, help="Path to one Android task YAML.")
    parser.add_argument("--model-id", required=True, help="Model id from configs/models.yaml.")
    parser.add_argument("--adb-device", default="emulator-5554", help="ADB device serial.")
    parser.add_argument(
        "--mode",
        choices=("until_pass", "fixed"),
        default="until_pass",
        help="until_pass stops on first PASS; fixed runs exactly --attempts times.",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=5,
        help="Max attempts for until_pass, or exact attempts for fixed mode.",
    )
    parser.add_argument("--action-mode", default="code_adapter")
    parser.add_argument("--observation-mode", default="screenshot_and_a11y_tree")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=None, help="Override task timeout in seconds.")
    parser.add_argument("--delay-seconds", type=float, default=0.0, help="Sleep between attempts.")
    parser.add_argument(
        "--label",
        default="manual_retry",
        help="Session label used under results/<model>/android/<label>_<timestamp>/",
    )
    parser.add_argument(
        "--results-root",
        default=None,
        help="Optional explicit results root. Defaults to results/<model_id>/android.",
    )
    return parser


def _load_result(run_dir: Path) -> dict:
    result_path = run_dir / "result.json"
    with result_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _attempt_summary(attempt: int, run_dir: Path, exit_code: int, result: dict) -> AttemptSummary:
    failure_message = None
    episode = result.get("episode_result")
    if isinstance(episode, dict):
        failure_message = episode.get("message")
    if not failure_message:
        failure_message = result.get("message")

    return AttemptSummary(
        attempt=attempt,
        run_dir=str(run_dir),
        exit_code=exit_code,
        status=str(result.get("status", "UNKNOWN")),
        latency_ms=result.get("latency_ms"),
        steps_taken=result.get("steps_taken"),
        started_at=result.get("started_at"),
        ended_at=result.get("ended_at"),
        failure_message=failure_message,
    )


def _should_stop(mode: str, status: str) -> bool:
    return mode == "until_pass" and status == "PASS"


def _run_one_attempt(
    *,
    task_path: Path,
    model_id: str,
    adb_device: str,
    run_dir: Path,
    action_mode: str,
    observation_mode: str,
    max_steps: int | None,
    timeout: int | None,
) -> tuple[int, dict]:
    exit_code = run_benchmark(
        task_path=task_path,
        model_id=model_id,
        adb_device=adb_device,
        run_dir=run_dir,
        action_mode=action_mode,
        observation_mode=observation_mode,
        max_steps=max_steps,
        timeout=timeout,
    )
    result = _load_result(run_dir)
    return exit_code, result


def run_trials(
    *,
    task_path: Path,
    model_id: str,
    adb_device: str,
    mode: str,
    attempts: int,
    action_mode: str,
    observation_mode: str,
    max_steps: int | None,
    timeout: int | None,
    delay_seconds: float,
    session_dir: Path,
    runner: Callable[..., tuple[int, dict]] = _run_one_attempt,
) -> dict:
    session_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[AttemptSummary] = []

    for attempt in range(1, attempts + 1):
        run_dir = session_dir / f"attempt_{attempt:02d}"
        logger.info("Attempt %d/%d -> %s", attempt, attempts, run_dir)
        exit_code, result = runner(
            task_path=task_path,
            model_id=model_id,
            adb_device=adb_device,
            run_dir=run_dir,
            action_mode=action_mode,
            observation_mode=observation_mode,
            max_steps=max_steps,
            timeout=timeout,
        )
        summary = _attempt_summary(attempt, run_dir, exit_code, result)
        summaries.append(summary)

        logger.info(
            "Attempt %d status=%s exit_code=%d steps=%s latency_ms=%s",
            attempt,
            summary.status,
            summary.exit_code,
            summary.steps_taken,
            summary.latency_ms,
        )
        if summary.failure_message and summary.status != "PASS":
            logger.info("Attempt %d failure=%s", attempt, summary.failure_message)

        if _should_stop(mode, summary.status):
            break
        if attempt < attempts and delay_seconds > 0:
            time.sleep(delay_seconds)

    total_attempts = len(summaries)
    pass_count = sum(1 for item in summaries if item.status == "PASS")
    first_pass_attempt = next((item.attempt for item in summaries if item.status == "PASS"), None)

    return {
        "task_path": str(task_path),
        "model_id": model_id,
        "adb_device": adb_device,
        "mode": mode,
        "requested_attempts": attempts,
        "completed_attempts": total_attempts,
        "pass_count": pass_count,
        "success_rate": pass_count / total_attempts if total_attempts else 0.0,
        "first_pass_attempt": first_pass_attempt,
        "session_dir": str(session_dir),
        "attempts": [asdict(item) for item in summaries],
    }


def _default_results_root(model_id: str) -> Path:
    return REPO_ROOT / "results" / model_id / "android"


def _session_dir(results_root: Path, label: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return results_root / f"{label}_{timestamp}"


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    task_path = Path(args.task)
    results_root = Path(args.results_root) if args.results_root else _default_results_root(args.model_id)
    session_dir = _session_dir(results_root, args.label)

    payload = run_trials(
        task_path=task_path,
        model_id=args.model_id,
        adb_device=args.adb_device,
        mode=args.mode,
        attempts=args.attempts,
        action_mode=args.action_mode,
        observation_mode=args.observation_mode,
        max_steps=args.max_steps,
        timeout=args.timeout,
        delay_seconds=args.delay_seconds,
        session_dir=session_dir,
    )

    summary_path = session_dir / "summary.json"
    summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"SESSION_DIR={session_dir}")
    print(f"SUMMARY_JSON={summary_path}")
    print(f"MODE={payload['mode']}")
    print(f"COMPLETED_ATTEMPTS={payload['completed_attempts']}")
    print(f"PASS_COUNT={payload['pass_count']}")
    print(f"SUCCESS_RATE={payload['success_rate']:.4f}")
    if payload["first_pass_attempt"] is not None:
        print(f"FIRST_PASS_ATTEMPT={payload['first_pass_attempt']}")
        return 0

    if args.mode == "fixed":
        return 1 if payload["pass_count"] == 0 else 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

