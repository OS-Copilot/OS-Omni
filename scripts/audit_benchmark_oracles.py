#!/usr/bin/env python3
"""Audit benchmark tasks for oracle linkage and difficulty policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.oracle_audit import (
    audit_task_tree,
    filter_findings,
    real_gui_gap_findings,
    summarize_findings,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks-root",
        default=str(REPO_ROOT / "tasks"),
        help="Root task directory to audit (default: repo tasks/).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a text report.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any task has audit issues.",
    )
    parser.add_argument(
        "--task-id-prefix",
        action="append",
        default=[],
        help="Only include benchmark task ids that start with this prefix. Repeatable.",
    )
    parser.add_argument(
        "--oracle-execution-style",
        action="append",
        default=[],
        help="Only include tasks whose oracle audit classifies to this execution style. Repeatable.",
    )
    parser.add_argument(
        "--require-real-gui",
        action="store_true",
        help=(
            "Optional diagnostic gate: exit non-zero when any included task is not "
            "classified as a real-GUI oracle (gui_actions or scripted_gui)."
        ),
    )
    parser.add_argument(
        "--only-real-gui-gaps",
        action="store_true",
        help="Render only tasks whose oracle is not yet classified as real GUI.",
    )
    args = parser.parse_args()

    findings = filter_findings(
        audit_task_tree(args.tasks_root),
        task_id_prefixes=args.task_id_prefix,
        oracle_execution_styles=args.oracle_execution_style,
    )
    summary = summarize_findings(findings)
    real_gui_gaps = real_gui_gap_findings(findings)
    rendered_findings = real_gui_gaps if args.only_real_gui_gaps else findings

    if args.json:
        payload = {
            "summary": summary,
            "filters": {
                "task_id_prefix": list(args.task_id_prefix),
                "oracle_execution_style": list(args.oracle_execution_style),
                "require_real_gui": bool(args.require_real_gui),
                "only_real_gui_gaps": bool(args.only_real_gui_gaps),
            },
            "real_gui_gap_task_ids": [item.benchmark_task_id for item in real_gui_gaps],
            "findings": [
                {
                    "benchmark_task_path": str(item.benchmark_task_path),
                    "benchmark_task_id": item.benchmark_task_id,
                    "benchmark_difficulty": item.benchmark_difficulty,
                    "oracle_source": item.oracle_source,
                    "oracle_task_path": str(item.oracle_task_path) if item.oracle_task_path else None,
                    "oracle_steps": item.oracle_steps,
                    "derived_difficulty": item.derived_difficulty,
                    "oracle_execution_style": item.oracle_execution_style,
                    "oracle_real_gui": item.oracle_real_gui,
                    "issues": list(item.issues),
                }
                for item in rendered_findings
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "Benchmark oracle audit: "
            f"{summary['ok']}/{summary['total']} tasks clean, "
            f"{summary['failing']} failing, {summary['issues']} total issues."
        )
        if summary.get("oracle_execution_styles"):
            styles = ", ".join(
                f"{style}={count}"
                for style, count in sorted(summary["oracle_execution_styles"].items())
            )
            print(
                "Oracle execution styles: "
                f"{styles} | real_gui={summary['real_gui_oracles']} "
                f"non_real_gui={summary['non_real_gui_oracles']} "
                f"unknown={summary['unknown_gui_oracles']}"
            )
        if args.require_real_gui:
            print(f"Real-GUI requirement: {summary['real_gui_oracles']}/{summary['total']} included tasks pass.")
        render_real_gui_gaps = bool(args.require_real_gui or args.only_real_gui_gaps)
        for item in rendered_findings:
            has_audit_issue = not item.ok
            has_real_gui_gap = render_real_gui_gaps and item in real_gui_gaps
            if not has_audit_issue and not has_real_gui_gap:
                continue
            print(f"- {item.benchmark_task_id} ({item.benchmark_task_path})")
            if item.oracle_task_path:
                print(f"  oracle task: {item.oracle_task_path}")
            if item.oracle_steps is not None:
                print(
                    f"  oracle steps: {item.oracle_steps} "
                    f"-> derived difficulty: {item.derived_difficulty}"
                )
            if item.oracle_execution_style:
                print(
                    "  oracle execution: "
                    f"{item.oracle_execution_style} "
                    f"(real_gui={item.oracle_real_gui})"
                )
            if has_real_gui_gap:
                print("  issue: oracle-not-classified-as-real-gui")
            for issue in item.issues:
                print(f"  issue: {issue}")

    has_real_gui_violation = bool(args.require_real_gui and real_gui_gaps)
    has_audit_violation = bool(args.strict and summary["failing"])
    return 1 if (has_audit_violation or has_real_gui_violation) else 0


if __name__ == "__main__":
    raise SystemExit(main())
