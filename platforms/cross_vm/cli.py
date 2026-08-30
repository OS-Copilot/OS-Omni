#!/usr/bin/env python3
"""Cross-VM Windows -> Linux execution entrypoint."""

from __future__ import annotations

import argparse
import logging
import sys

from platforms.cross_vm.runner import run_execution
from platforms.cross_vm.types import load_cross_vm_execution


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-VM Windows -> Linux execution runner.")
    parser.add_argument("--execution", required=True, help="Path to cross-VM execution YAML file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        execution = load_cross_vm_execution(args.execution)
        return run_execution(execution)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as exc:
        print(f"Error: {exc}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

