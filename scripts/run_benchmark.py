#!/usr/bin/env python3
"""Shared benchmark preflight entry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate one execution and prepare shared handoff payload.",
    )
    parser.add_argument(
        "--execution",
        required=True,
        help="Path to one execution YAML file.",
    )
    return parser


def _print_text_summary(summary: dict) -> None:
    print("Execution preflight succeeded.")
    print(f"Execution: {summary['execution_path']}")
    print(f"Platform: {summary['platform']}")
    print(f"Tasks: {summary['task_count']}")
    for item in summary["tasks"]:
        print(f"  - {item['task_id']} ({item['path']})")
    print(f"Models: {summary['model_count']}")
    for model_id in summary["models"]:
        print(f"  - {model_id}")
    agent = summary.get("agent")
    if agent:
        print("Agent:")
        for key, value in agent.items():
            print(f"  - {key}: {value}")
    print("Ready for platform handoff. Platform dispatch is not wired yet.")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    from core.launcher import prepare_execution, prepare_execution_summary
    from core.specs.errors import SpecValidationError

    try:
        prepared = prepare_execution(args.execution)
        summary = prepare_execution_summary(prepared)
    except SpecValidationError as exc:
        print(f"[SPEC ERROR] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  
        print(f"[UNEXPECTED ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _print_text_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
