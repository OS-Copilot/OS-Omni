#!/usr/bin/env python3
"""Correct material source-versus-brief mismatches in CUA task instructions."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.generate_cua_tasks_review_instructions import (
        _required_payload_literals,
        _source_tasks,
        _validation_error,
    )
except ModuleNotFoundError:
    from generate_cua_tasks_review_instructions import (
        _required_payload_literals,
        _source_tasks,
        _validation_error,
    )

SYSTEM_PROMPT = """Correct the supplied English task brief so that it faithfully matches the original task. The source instruction is authoritative. Review the listed QA issues carefully; repair only real issues and do not remove correct requirements. Do not invent values from inferred application behavior or hidden evaluator details. Preserve all unaffected exact text, names, dates, amounts, choices, formatting, artifact relationships, and final-state requirements.

Keep the natural task-brief style, like “Transfer the data from our 'Employee Performance Evaluation Summary' Excel sheet into our standardized PDF evaluation forms. Each employee's evaluation data should be…” Begin with an imperative request, then describe what finished work should contain. Do not write a step-by-step UI tutorial, headings, bullets, numbered lists, click/tap/scroll instructions, or screen-navigation prose. Return only the corrected English task brief."""


def _request(
    endpoint: str,
    model: str,
    task: Mapping[str, Any],
    brief: str,
    issues: list[dict[str, Any]],
    error: str = "",
) -> str:
    context = {
        "task_id": task.get("task_id"),
        "source_instruction": task.get("instruction"),
        "current_brief": brief,
        "qa_issues": issues,
        "required_exact_values": _required_payload_literals(task),
    }
    if error:
        context["previous_error"] = error
    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 3500,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.load(response)
    return str(result["choices"][0]["message"]["content"]).strip()


def _refine(
    endpoint: str,
    model: str,
    task: Mapping[str, Any],
    brief: str,
    issues: list[dict[str, Any]],
) -> str:
    values = _required_payload_literals(task)
    error = ""
    candidate = brief
    for _ in range(5):
        candidate = _request(endpoint, model, task, candidate, issues, error)
        error = _validation_error(candidate, values) or ""
        if not error:
            return candidate
    raise ValueError(f"Could not refine {task.get('task_id')}: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("instruction_map", type=Path)
    parser.add_argument("audit_report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8003")
    parser.add_argument("--model", default="qwen3.8-27b")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    if args.output.resolve() == args.instruction_map.resolve():
        parser.error("--output must differ from the input map")

    tasks = _source_tasks(args.source_root.resolve())
    base = json.loads(args.instruction_map.read_text(encoding="utf-8"))
    audits = json.loads(args.audit_report.read_text(encoding="utf-8"))
    records = dict(base["instructions"])
    if args.output.is_file():
        records.update(
            json.loads(args.output.read_text(encoding="utf-8"))["instructions"]
        )
    task_ids = {str(task["task_id"]).lower() for task in tasks}
    if set(records) != task_ids:
        raise ValueError("Instruction map does not exactly cover source tasks")
    pending = [
        task
        for task in tasks
        if audits.get(str(task["task_id"]).lower())
        and not records[str(task["task_id"]).lower()].get("source_audit_corrected")
    ]
    print(f"Refining {len(pending)} of {len(tasks)} task briefs", flush=True)
    lock = threading.Lock()
    failures: list[str] = []

    def save() -> None:
        payload = dict(base)
        payload["instructions"] = dict(sorted(records.items()))
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.output)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                _refine,
                args.endpoint,
                args.model,
                task,
                str(records[str(task["task_id"]).lower()]["instruction"]),
                audits[str(task["task_id"]).lower()],
            ): task
            for task in pending
        }
        for future in as_completed(futures):
            task = futures[future]
            task_id = str(task["task_id"]).lower()
            try:
                instruction = future.result()
            except Exception as exc:
                failures.append(task_id)
                print(f"FAILED {task_id}: {exc}", flush=True)
                continue
            original = str(task.get("instruction") or "")
            with lock:
                records[task_id] = {
                    "style_version": 2,
                    "source_instruction_sha256": hashlib.sha256(
                        original.encode("utf-8")
                    ).hexdigest(),
                    "instruction": instruction,
                    "source_audit_corrected": True,
                }
                save()
                print(f"corrected {task_id}", flush=True)

    if failures:
        raise RuntimeError(f"Could not refine {len(failures)} tasks: {failures}")
    if not args.output.is_file():
        save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
