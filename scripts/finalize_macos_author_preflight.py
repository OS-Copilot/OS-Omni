#!/usr/bin/env python3
"""Validate cached task preflights and write the explicit Mac preflight gate report."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from platforms.macos.runtime_config import MACOS_RUNTIME_CONFIG_PATH, load_macos_runtime_config
from scripts.author_eval_queue import (
    code_version_hash,
    load_manifest_tasks,
    manifest_hash,
    sha256_file,
    task_implementation_hash,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / "records/macos-author-preflight-full-20261012"
SKIP_ID = "macos.photos.favorite_receipts_hard"
SKIP_REASON = (
    "macOS Photos cannot create/open its first-run library on the active VM; "
    "the expected Photos.sqlite database remains absent and evaluation errors before model actions."
)


def main() -> int:
    gate_path = OUTPUT / "formal_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    map_path = Path(gate["initial_fail_evidence"])
    if not map_path.is_absolute():
        map_path = (OUTPUT / map_path).resolve()
    evidence = json.loads(map_path.read_text(encoding="utf-8"))
    inventory = load_manifest_tasks(platform="macos")
    by_id = {item["task_id"]: item for item in inventory}
    if len(by_id) != 48 or len(evidence) != len(by_id):
        raise SystemExit(f"task evidence inventory mismatch: {len(evidence)} / {len(by_id)}")

    photos = evidence[SKIP_ID]
    photo_dir = OUTPUT / SKIP_ID.replace(".", "_")
    screenshot = photo_dir / "screenshots/photos-init-error_20261012_144057_308.jpg"
    error_record = photo_dir / "preflight.json"
    if not screenshot.is_file() or not error_record.is_file():
        raise SystemExit("Photos skip requires its preserved initializer/evaluator error and screenshot")
    task_path = ROOT / by_id[SKIP_ID]["task_path"]
    photos.update(
        {
            "status": "SKIPPED_BY_AUTHOR",
            "skip_reason": SKIP_REASON,
            "classification": "benchmark_environment_blocker",
            "task_sha256": sha256_file(task_path),
            "task_implementation_sha256": task_implementation_hash(task_path),
            "evidence": str(error_record),
            "screenshot": str(screenshot),
        }
    )
    evidence[SKIP_ID] = photos

    stale = []
    for task_id, item in evidence.items():
        evidence_ref = Path(str(item.get("evidence") or ""))
        if not evidence_ref.is_absolute():
            evidence_ref = (Path.cwd() / evidence_ref).resolve()
        item["evidence"] = str(evidence_ref)
        screenshot_ref = item.get("initial_screenshot")
        if screenshot_ref:
            screenshot_path = Path(str(screenshot_ref))
            if not screenshot_path.is_absolute():
                item["initial_screenshot"] = str((Path.cwd() / screenshot_path).resolve())
        if task_id == SKIP_ID:
            continue
        task_path = ROOT / by_id[task_id]["task_path"]
        if item.get("status") != "FAIL" or item.get("initializer_status") != "PASS":
            stale.append(f"{task_id}: not initializer PASS / initial FAIL")
        elif item.get("task_sha256") != sha256_file(task_path):
            stale.append(f"{task_id}: task hash is stale")
        elif item.get("task_implementation_sha256") != task_implementation_hash(task_path):
            stale.append(f"{task_id}: implementation hash is stale")
        elif not Path(item.get("evidence", "")).is_file():
            stale.append(f"{task_id}: evidence file is missing")
    if stale:
        raise SystemExit("invalid task evidence:\n" + "\n".join(stale))
    map_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    config = load_macos_runtime_config(MACOS_RUNTIME_CONFIG_PATH)
    vm_ip = os.environ.get("HELLOWORLD_MACOS_VM_IP", config.vm_ip)
    previous = json.loads((OUTPUT / "preflight_report.json").read_text(encoding="utf-8"))
    report = {
        "passed": True,
        "platform": "macos",
        "checks": {
            **previous.get("checks", {}),
            "runtime_health": "HEALTHY",
            "runtime_url": f"http://{vm_ip}:{config.runtime_port}",
            "task_count": len(by_id),
            "expected_task_count": len(by_id),
            "initial_fail_count": len(by_id) - 1,
            "author_skipped_count": 1,
            "author_skipped_task_ids": [SKIP_ID],
            "manifest_sha256": manifest_hash(),
            "code_version": code_version_hash("macos"),
            "finalized_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }
    report_path = OUTPUT / "preflight_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
