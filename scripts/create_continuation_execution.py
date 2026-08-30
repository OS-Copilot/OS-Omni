#!/usr/bin/env python3
"""Generate a continuation execution from the latest local run evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.specs.loader import load_execution_spec, load_task_spec


@dataclass(frozen=True)
class RunRecord:
    task_id: str
    task_path: Path
    run_dir: Path
    model_id: str
    status: str
    timestamp: str
    has_result: bool
    execution_path: Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution", required=True, help="Original execution YAML to continue.")
    parser.add_argument(
        "--model",
        default=None,
        help="Model id to continue. Required when the original execution contains multiple models.",
    )
    parser.add_argument(
        "--results-root",
        default=str(REPO_ROOT / "results"),
        help="Results root to scan. Defaults to repo results/.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Continuation execution output path. Defaults to <original>_continue_<timestamp>.yaml.",
    )
    parser.add_argument(
        "--include-statuses",
        nargs="*",
        default=["FAIL", "ERROR", "INCOMPLETE", "MISSING", "UNKNOWN"],
        help="Statuses that should be included in the continuation file.",
    )
    return parser.parse_args()


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    else:
        path = path.resolve()
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML payload must be an object: {path}")
    return payload


def _normalize_status(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if text in {"PASS", "FAIL", "ERROR"}:
        return text
    return "UNKNOWN"


def _timestamp_key(raw: str) -> tuple[int, str]:
    text = (raw or "").strip()
    return (0, "") if not text else (1, text)


def _relative_to_repo(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def _infer_model_id(run_dir: Path, results_root: Path) -> str | None:
    try:
        relative = run_dir.resolve().relative_to(results_root.resolve())
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 4:
        return None
    return parts[0]


def _parse_run_record(args_path: Path, *, results_root: Path) -> RunRecord | None:
    try:
        args_payload = json.loads(args_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(args_payload, dict):
        return None

    execution_section = args_payload.get("execution")
    task_section = args_payload.get("task")
    if not isinstance(execution_section, dict) or not isinstance(task_section, dict):
        return None

    execution_path_raw = execution_section.get("path")
    task_path_raw = task_section.get("path")
    task_snapshot = task_section.get("snapshot")
    created_at = str(args_payload.get("created_at") or "").strip()
    if not execution_path_raw or not task_path_raw or not isinstance(task_snapshot, dict):
        return None

    task_id = str(task_snapshot.get("task_id") or "").strip()
    if not task_id:
        return None

    run_dir = args_path.parent
    result_path = run_dir / "result.json"
    status = "INCOMPLETE"
    timestamp = created_at
    if result_path.exists():
        try:
            result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            result_payload = {}
        if isinstance(result_payload, dict):
            status = _normalize_status(result_payload.get("status")) or "UNKNOWN"
            timestamp = (
                str(result_payload.get("ended_at") or "").strip()
                or str(result_payload.get("started_at") or "").strip()
                or created_at
            )
        else:
            status = "UNKNOWN"
    elif not timestamp:
        timestamp = datetime.fromtimestamp(run_dir.stat().st_mtime).astimezone().isoformat()

    model_id = _infer_model_id(run_dir, results_root)
    if not model_id:
        return None

    return RunRecord(
        task_id=task_id,
        task_path=_resolve_path(task_path_raw),
        run_dir=run_dir.resolve(),
        model_id=model_id,
        status=status,
        timestamp=timestamp,
        has_result=result_path.exists(),
        execution_path=_resolve_path(execution_path_raw),
    )


def _collect_latest_records(*, execution_path: Path, model_id: str, results_root: Path) -> dict[str, RunRecord]:
    latest: dict[str, RunRecord] = {}
    for args_path in results_root.rglob("args.json"):
        record = _parse_run_record(args_path, results_root=results_root)
        if record is None:
            continue
        if record.execution_path != execution_path or record.model_id != model_id:
            continue
        existing = latest.get(record.task_id)
        if existing is None or (_timestamp_key(record.timestamp), str(record.run_dir)) > (
            _timestamp_key(existing.timestamp),
            str(existing.run_dir),
        ):
            latest[record.task_id] = record
    return latest


def _default_output_path(execution_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return execution_path.with_name(f"{execution_path.stem}_continue_{timestamp}.yaml")


def main() -> int:
    args = _parse_args()
    execution_path = _resolve_path(args.execution)
    results_root = _resolve_path(args.results_root)

    execution_spec = load_execution_spec(execution_path)
    execution_yaml = _load_yaml(execution_path)
    raw_tasks = execution_yaml.get("tasks")
    if not isinstance(raw_tasks, list) or len(raw_tasks) != len(execution_spec.task_paths):
        raise ValueError(f"execution.tasks must align with the validated task list: {execution_path}")

    model_ids = list(execution_spec.models)
    if args.model:
        model_id = str(args.model).strip()
        if model_id not in model_ids:
            raise ValueError(f"model {model_id!r} is not present in execution.models: {model_ids}")
    else:
        if len(model_ids) != 1:
            raise ValueError(
                f"execution contains multiple models {model_ids}; pass --model to choose one continuation target."
            )
        model_id = model_ids[0]

    include_statuses = {str(item).strip().upper() for item in args.include_statuses if str(item).strip()}
    latest_records = _collect_latest_records(
        execution_path=execution_path.resolve(),
        model_id=model_id,
        results_root=results_root,
    )

    pending_tasks: list[str] = []
    report_rows: list[dict[str, Any]] = []
    for raw_task, task_path in zip(raw_tasks, execution_spec.task_paths):
        task_spec = load_task_spec(task_path)
        latest = latest_records.get(task_spec.task_id)
        status = latest.status if latest is not None else "MISSING"
        report_rows.append(
            {
                "task_id": task_spec.task_id,
                "task_path": _relative_to_repo(task_path),
                "status": status,
                "latest_run_dir": _relative_to_repo(latest.run_dir) if latest is not None else None,
                "latest_timestamp": latest.timestamp if latest is not None else None,
            }
        )
        if status in include_statuses:
            pending_tasks.append(str(raw_task))

    output_path = _resolve_path(args.output) if args.output else _default_output_path(execution_path)
    continuation_payload = dict(execution_yaml)
    continuation_payload["tasks"] = pending_tasks
    continuation_payload["models"] = [model_id]
    metadata = continuation_payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = dict(metadata)
    metadata.update(
        {
            "continued_from_execution": _relative_to_repo(execution_path),
            "continued_from_model": model_id,
            "generated_by": "scripts/create_continuation_execution.py",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    )
    continuation_payload["metadata"] = metadata

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(continuation_payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )

    summary = {
        "status": "ok",
        "execution": _relative_to_repo(execution_path),
        "model": model_id,
        "results_root": _relative_to_repo(results_root),
        "output": _relative_to_repo(output_path),
        "pending_count": len(pending_tasks),
        "pending_tasks": pending_tasks,
        "task_statuses": report_rows,
    }
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
