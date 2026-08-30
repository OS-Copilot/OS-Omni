#!/usr/bin/env python3
"""Summarize macOS oracle audit status and latest verification evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.benchmark_policy import HARD_MIN_ORACLE_STEPS
from core.oracle_audit import OracleAuditFinding, audit_task_tree, summarize_findings

_RESULT_BUCKET_PREFIXES = {
    "fresh": "fresh_verification_",
    "repeatability": "repeatability_",
    "history_window1": "history_window1_",
}


@dataclass(frozen=True)
class ResultRecord:
    task_id: str
    status: str
    path: Path
    ended_at: datetime


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-root", default=str(REPO_ROOT / "tasks" / "macos"))
    parser.add_argument("--results-root", default=str(REPO_ROOT / "results"))
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Render machine-readable JSON or human-readable Markdown.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _detect_bucket(path: Path) -> str | None:
    for part in path.parts:
        for bucket, prefix in _RESULT_BUCKET_PREFIXES.items():
            if part.startswith(prefix):
                return bucket
    return None


def _parse_result_time(payload: dict[str, Any], path: Path) -> datetime:
    for key in ("ended_at", "started_at"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def _collect_latest_results(results_root: Path) -> dict[str, dict[str, ResultRecord]]:
    latest: dict[str, dict[str, ResultRecord]] = {bucket: {} for bucket in _RESULT_BUCKET_PREFIXES}
    for result_path in results_root.glob("**/result.json"):
        bucket = _detect_bucket(result_path)
        if bucket is None:
            continue
        payload = _load_json(result_path)
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            continue
        record = ResultRecord(
            task_id=task_id,
            status=str(payload.get("status") or "UNKNOWN").strip().upper() or "UNKNOWN",
            path=result_path,
            ended_at=_parse_result_time(payload, result_path),
        )
        previous = latest[bucket].get(task_id)
        if previous is None or (record.ended_at, str(record.path)) > (previous.ended_at, str(previous.path)):
            latest[bucket][task_id] = record
    return latest


def _difficulty_counts(findings: Iterable[OracleAuditFinding]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for item in findings:
        counter[str(item.benchmark_difficulty or "missing").lower()] += 1
    return counter


def _run_coverage(task_ids: set[str], latest_results: dict[str, ResultRecord]) -> dict[str, Any]:
    latest_for_scope = {task_id: latest_results[task_id] for task_id in task_ids if task_id in latest_results}
    pass_covered = sorted(task_id for task_id, record in latest_for_scope.items() if record.status == "PASS")
    remaining = sorted(task_ids - set(pass_covered))
    status_counts = Counter(record.status for record in latest_for_scope.values())
    return {
        "covered": len(pass_covered),
        "total": len(task_ids),
        "all_covered": len(pass_covered) == len(task_ids),
        "remaining": remaining,
        "latest_status_counts": dict(sorted(status_counts.items())),
    }


def build_summary(tasks_root: Path, results_root: Path) -> dict[str, Any]:
    findings = audit_task_tree(tasks_root)
    task_ids = {item.benchmark_task_id for item in findings}
    real_gui_task_ids = {item.benchmark_task_id for item in findings if item.real_gui_ok}
    style_to_task_ids: dict[str, set[str]] = defaultdict(set)
    for item in findings:
        style_to_task_ids[str(item.oracle_execution_style or "unknown")].add(item.benchmark_task_id)

    latest_results = _collect_latest_results(results_root)
    difficulty_counts = _difficulty_counts(findings)
    medium_task_ids = sorted(item.benchmark_task_id for item in findings if item.benchmark_difficulty == "medium")
    hard_below_threshold = sorted(
        item.benchmark_task_id
        for item in findings
        if item.benchmark_difficulty == "hard"
        and isinstance(item.oracle_steps, int)
        and item.oracle_steps < HARD_MIN_ORACLE_STEPS
    )

    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tasks_root": str(tasks_root),
        "results_root": str(results_root),
        "audit": {
            **summarize_findings(findings),
            "difficulty_counts": dict(sorted(difficulty_counts.items())),
            "medium_task_ids": medium_task_ids,
            "hard_below_threshold_task_ids": hard_below_threshold,
        },
        "verification": {
            "fresh_all_tasks": _run_coverage(task_ids, latest_results["fresh"]),
            "history_window1_all_tasks": _run_coverage(task_ids, latest_results["history_window1"]),
            "repeatability_all_tasks": _run_coverage(task_ids, latest_results["repeatability"]),
            "real_gui_total": len(real_gui_task_ids),
            "real_gui": {
                "fresh": _run_coverage(real_gui_task_ids, latest_results["fresh"]),
                "repeatability": _run_coverage(real_gui_task_ids, latest_results["repeatability"]),
                "history_window1": _run_coverage(real_gui_task_ids, latest_results["history_window1"]),
            },
            "history_window1_by_execution_style": {
                style: _run_coverage(task_id_set, latest_results["history_window1"])
                for style, task_id_set in sorted(style_to_task_ids.items())
            },
        },
    }
    return summary


def _render_markdown(summary: dict[str, Any]) -> str:
    audit = summary["audit"]
    verification = summary["verification"]
    lines = [
        "# macOS Oracle Verification Summary",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        "This snapshot is generated from the current `tasks/macos` tree and the latest local `results/**/result.json` evidence.",
        "Regenerate with:",
        "",
        "```bash",
        ".venv/bin/python scripts/summarize_macos_oracle_verification.py --format markdown > docs/benchmark-oracle-verification-summary.md",
        "```",
        "",
        "## Audit status",
        "",
        f"- Clean tasks: **{audit['ok']}/{audit['total']}**",
        f"- Failing tasks: **{audit['failing']}**",
        f"- Total issues: **{audit['issues']}**",
        f"- Difficulty counts: `{json.dumps(audit['difficulty_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- Medium tasks remaining: **{len(audit['medium_task_ids'])}**",
        f"- Hard tasks below {HARD_MIN_ORACLE_STEPS} oracle steps: **{len(audit['hard_below_threshold_task_ids'])}**",
        "",
        "## Latest verification coverage",
        "",
        f"- Fresh verification (all tasks): **{verification['fresh_all_tasks']['covered']}/{verification['fresh_all_tasks']['total']} PASS**",
        f"- History window = 1 (all tasks): **{verification['history_window1_all_tasks']['covered']}/{verification['history_window1_all_tasks']['total']} PASS**",
        f"- Repeatability (all tasks with latest evidence): **{verification['repeatability_all_tasks']['covered']}/{verification['repeatability_all_tasks']['total']} PASS**",
        f"- Real-GUI subset coverage (diagnostic only): fresh **{verification['real_gui']['fresh']['covered']}/{verification['real_gui_total']}**, repeatability **{verification['real_gui']['repeatability']['covered']}/{verification['real_gui_total']}**, history_window1 **{verification['real_gui']['history_window1']['covered']}/{verification['real_gui_total']}**",
        "",
        "## History-window-1 coverage by oracle execution style",
        "",
        "| Execution style | Covered | Total | All covered |",
        "| --- | ---: | ---: | --- |",
    ]
    for style, style_summary in verification["history_window1_by_execution_style"].items():
        lines.append(
            f"| `{style}` | {style_summary['covered']} | {style_summary['total']} | {'yes' if style_summary['all_covered'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `repeatability_all_tasks` is informational; the core requirement in this lane is deterministic evaluator-valid completion, not GUI fidelity.",
            "- The real-GUI subset counts are diagnostic only. Non-GUI oracle styles are acceptable when they reliably drive the task to the same evaluator-visible end state.",
            "- `history_window1` is the strongest regression stress pass for the oracle adapters because it proves every task still completes with an aggressively truncated assistant history.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    summary = build_summary(Path(args.tasks_root), Path(args.results_root))
    if args.format == "markdown":
        sys.stdout.write(_render_markdown(summary))
    else:
        json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
