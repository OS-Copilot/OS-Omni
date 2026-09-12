#!/usr/bin/env python3
"""Generate English natural-language instructions for the CUA review task pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.import_cua_tasks_review import INVENTORY_NAME, _extract_task, _read_json
except ModuleNotFoundError:
    from import_cua_tasks_review import INVENTORY_NAME, _extract_task, _read_json

SYSTEM_PROMPT = """Write a new English task brief for a GUI agent. Match the style of this work request: “Transfer the data from our 'Employee Performance Evaluation Summary' Excel sheet into our standardized PDF evaluation forms. Each employee's evaluation data should be…”

Begin with one direct imperative sentence naming the overall deliverable and application. Subsequent connected prose should describe what each resulting document, message, booking, setting, record, or other artifact should contain, how they relate, and what state should remain at completion. Group related requirements by outcome, not by the order in which screens are visited. The prior instruction is a source of facts, not a writing template.

This must NOT be a walkthrough. Do not narrate going to or returning from screens, switching apps or tabs, searching or clearing queries, clicking, tapping, scrolling, focusing fields, or waiting. Do not use headings, bullets, numbering, or procedural transitions such as "first", "next", "then", and "finally" outside quoted content. If an interaction itself is the task, describe its meaningful result naturally. Preserve every substantive operation, exact authored string, recipient, account, date, quantity, selected option, filename, message, formatting requirement, image description, source-to-destination relationship, necessary dependency, prohibition, and final-state condition. Preserve intentional spelling and capitalization, including apparent typos. A source message containing a marker means the whole message is needed, not only the marker. Do not invent facts or relationships (for example, finding a contact does not mean adding that contact to a group).

Do not mention evaluators, APIs, source instructions, translation, or benchmark machinery. Return only the new task brief."""

CJK_RE = re.compile(r"[\u3400-\u9fff]")
LIST_RE = re.compile(r"(?m)^\s*(?:[-*#]|\d+[.)])\s+")
CHOREOGRAPHY_RE = re.compile(
    r"(?i)\b(?:double[- ]click|click|tap|scroll|swipe)(?:s|ed|ing)?\b|"
    r"\bwait\s+(?:for|until)\b|\[step\s+\d+\]|"
    r"\b(?:return|switch|navigate)\s+to\b|"
    r"\bclear\s+the\s+search\b|"
    r"(?:(?<=\.)|(?<=!))\s*(?:first|next|then|finally|afterward)\b"
)
PAYLOAD_ACTION_RE = re.compile(
    r"(?i)(?:输入(?!框)|键入|填写|\btype\b|with the exact text|text exactly|named\b|titled\b)"
)
QUOTED_VALUE_RE = re.compile(r'`([^`]+)`|“([^”]+)”|"([^"\n]+)"')
UI_COMMAND_VALUES = {"Format Document", "Save File", "Run Tests"}


def _source_tasks(source_root: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    inventory = source_root / INVENTORY_NAME
    for line in inventory.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        app, platform_dir, task_dir = line.split("\t")
        directory = source_root / app / platform_dir / task_dir
        task, _ = _extract_task(_read_json(directory / "args.json"), directory)
        tasks.append(task)
    return tasks


def _request_instruction(
    endpoint: str,
    model: str,
    task: Mapping[str, Any],
    prior_instruction: str,
    previous_error: str = "",
    previous_draft: str = "",
) -> str:
    metadata = task.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    context = {
        "task_id": task.get("task_id"),
        "prior_instruction": prior_instruction,
        "description": metadata.get("description"),
        "required_exact_values": _required_payload_literals(task),
    }
    user_content = json.dumps(context, ensure_ascii=False)
    if previous_error:
        user_content += (
            f"\n\nThe previous draft was rejected because: {previous_error}. "
            "Revise it as an outcome-based work request while "
            "retaining every substantive requirement."
        )
    if previous_draft:
        user_content += f"\n\nPrevious draft:\n{previous_draft}"
    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 3200,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
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


def _required_payload_literals(task: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    source = str(task.get("instruction") or "")
    for line in source.splitlines():
        actions = list(PAYLOAD_ACTION_RE.finditer(line))
        if not actions:
            continue
        position = actions[-1].end()
        quoted = [
            next(group for group in match.groups() if group is not None)
            for match in QUOTED_VALUE_RE.finditer(line)
            if match.start() >= position
        ]
        if (
            quoted
            and len(quoted[0]) > 1
            and quoted[0] not in UI_COMMAND_VALUES
            and quoted[0] not in values
        ):
            values.append(quoted[0])
    return values


def _validation_error(
    instruction: str, required_values: list[str] | None = None
) -> str | None:
    if not instruction:
        return "the response was empty"
    if CJK_RE.search(instruction):
        return "it contained Chinese characters; translate all prose into English"
    if LIST_RE.search(instruction):
        return "it used a heading, bullet, or numbered list; use prose paragraphs only"
    prose = re.sub(r'`[^`]*`|"[^"\n]*"|“[^”\n]*”', "", instruction)
    if CHOREOGRAPHY_RE.search(prose):
        return "it retained UI navigation, search, gestures, waiting, or procedural transitions; describe the required outcomes instead"
    if re.search(
        r"(?i)\b(?:source instruction|evaluator|benchmark machinery)\b", instruction
    ):
        return "it referred to benchmark implementation details"
    missing = [value for value in required_values or [] if value not in instruction]
    if missing:
        return "it omitted these exact required values: " + json.dumps(
            missing, ensure_ascii=False
        )
    return None


def _generate_one(
    endpoint: str, model: str, task: Mapping[str, Any], prior_instruction: str
) -> str:
    error = ""
    instruction = ""
    required_values = _required_payload_literals(task)
    for _ in range(5):
        instruction = _request_instruction(
            endpoint, model, task, prior_instruction, error, instruction
        )
        error = _validation_error(instruction, required_values) or ""
        if not error:
            return instruction
    raise ValueError(f"Could not generate {task.get('task_id')}: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument(
        "--prior-map",
        type=Path,
        required=True,
        help="Existing reviewed instruction map used as a fact source",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New instruction map; must differ from --prior-map",
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:8003")
    parser.add_argument("--model", default="qwen3.8-27b")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    if args.output.resolve() == args.prior_map.resolve():
        parser.error("--output must differ from --prior-map")

    tasks = _source_tasks(args.source_root.resolve())
    prior_records = _read_json(args.prior_map)["instructions"]
    if set(prior_records) != {str(task["task_id"]).lower() for task in tasks}:
        raise ValueError("Prior instruction map does not exactly match source tasks")
    existing: dict[str, Any] = {}
    if args.output.is_file():
        existing = json.loads(args.output.read_text(encoding="utf-8")).get(
            "instructions", {}
        )
    records = dict(existing)
    pending: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task["task_id"]).lower()
        source = str(task.get("instruction") or "")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        record = records.get(task_id)
        existing_instruction = (
            str(record.get("instruction") or "")
            if isinstance(record, Mapping)
            else ""
        )
        required_values = _required_payload_literals(task)
        if (
            not isinstance(record, Mapping)
            or record.get("style_version") != 2
            or record.get("source_instruction_sha256") != digest
            or _validation_error(existing_instruction, required_values)
        ):
            pending.append(task)

    lock = threading.Lock()

    def save() -> None:
        payload = {
            "schema_version": 1,
            "generation_model": args.model,
            "instruction_format": "english_natural_language",
            "style_version": 2,
            "instructions": dict(sorted(records.items())),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.output)

    completed = len(tasks) - len(pending)
    failures: list[str] = []
    print(f"Generating {len(pending)} of {len(tasks)} instructions", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                _generate_one,
                args.endpoint,
                args.model,
                task,
                str(prior_records[str(task["task_id"]).lower()]["instruction"]),
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
            source = str(task.get("instruction") or "")
            with lock:
                records[task_id] = {
                    "style_version": 2,
                    "source_instruction_sha256": hashlib.sha256(
                        source.encode("utf-8")
                    ).hexdigest(),
                    "instruction": instruction,
                }
                completed += 1
                save()
                print(f"[{completed}/{len(tasks)}] {task_id}", flush=True)

    if failures:
        raise RuntimeError(f"Could not generate {len(failures)} tasks: {failures}")
    if set(records) != {str(task["task_id"]).lower() for task in tasks}:
        raise ValueError("Generated instruction map does not exactly match source tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
