#!/usr/bin/env python3
"""Audit CUA task briefs against their original reviewed instructions."""

from __future__ import annotations

import argparse
import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

try:
    from tools.generate_cua_tasks_review_instructions import _source_tasks
except ModuleNotFoundError:
    from generate_cua_tasks_review_instructions import _source_tasks

SYSTEM_PROMPT = """You audit whether an English task brief faithfully describes the original task. Check every artifact, message, attachment, booking, setting, and record against the source, especially its destination, source, exact value, and necessary order. Distinguish copied source text placed in Saved Messages from a different message forwarded to a group. Identify false claims even when all quoted values are present. Treat an instruction to use the full text of a source message as different from merely typing a marker. Ignore omitted UI navigation, clicks, waits, and redundant process wording. Only report MATERIAL differences: missing required work, invented work, wrong associations, or lost final-state constraints. Return JSON only: {"issues":[{"type":"missing|invented|wrong_destination|wrong_source|wrong_value|wrong_order","detail":"one concise, specific sentence"}]}. Return {"issues":[]} if the brief is faithful."""


def _audit(endpoint: str, model: str, source: str, brief: str) -> list[dict[str, Any]]:
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 1000,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"source_instruction": source, "task_brief": brief},
                    ensure_ascii=False,
                ),
            },
        ],
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    last_error: Exception | None = None
    parsed: dict[str, Any] | None = None
    for _ in range(3):
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.load(response)
        try:
            parsed = json.loads(result["choices"][0]["message"]["content"])
            break
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            last_error = exc
    if parsed is None:
        raise ValueError("Could not parse audit response") from last_error
    issues = parsed.get("issues")
    if not isinstance(issues, list):
        raise ValueError(f"Invalid audit response: {parsed}")
    return [issue for issue in issues if isinstance(issue, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("instruction_map", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8003")
    parser.add_argument("--model", default="qwen3.8-27b")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    tasks = _source_tasks(args.source_root.resolve())
    briefs = json.loads(args.instruction_map.read_text(encoding="utf-8"))[
        "instructions"
    ]
    if set(briefs) != {str(task["task_id"]).lower() for task in tasks}:
        raise ValueError("Instruction map does not exactly cover the source tasks")

    reports: dict[str, Any] = {}
    if args.output.is_file():
        reports = json.loads(args.output.read_text(encoding="utf-8"))
    pending = [task for task in tasks if str(task["task_id"]).lower() not in reports]
    lock = threading.Lock()
    print(f"Auditing {len(pending)} of {len(tasks)} task briefs", flush=True)

    def save() -> None:
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(dict(sorted(reports.items())), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.output)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                _audit,
                args.endpoint,
                args.model,
                str(task.get("instruction") or ""),
                str(briefs[str(task["task_id"]).lower()]["instruction"]),
            ): str(task["task_id"]).lower()
            for task in pending
        }
        for future in as_completed(futures):
            task_id = futures[future]
            try:
                issues = future.result()
            except Exception as exc:
                print(f"FAILED {task_id}: {exc}", flush=True)
                continue
            with lock:
                reports[task_id] = issues
                save()
                if issues:
                    print(f"[{len(reports)}/{len(tasks)}] {task_id}: {len(issues)} issues", flush=True)

    print(
        f"Audited {len(reports)} tasks; "
        f"flagged {sum(bool(issues) for issues in reports.values())}",
        flush=True,
    )
    return 0 if len(reports) == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
