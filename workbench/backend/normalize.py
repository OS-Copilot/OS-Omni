from __future__ import annotations

import datetime as dt
import json
import mimetypes
from pathlib import Path
from typing import Any

from .utils import isoformat, load_json, parse_datetime, relative_path, resolve_path, safe_float, safe_int, stable_id


RUN_MARKER = "result.json"
RUNNER_LOG_PREVIEW_LINES = 120
RUNNER_LOG_MAX_CHARS = 120_000
STEP_NODE_SAMPLE_LIMIT = 18


class AssetRegistry:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def register(self, path: Path | None, kind: str = "image") -> dict[str, Any] | None:
        if path is None:
            return None
        try:
            resolved = path.resolve()
        except OSError:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None

        asset_id = stable_id("asset", str(resolved))
        if asset_id not in self._items:
            mime_type, _ = mimetypes.guess_type(str(resolved))
            self._items[asset_id] = {
                "id": asset_id,
                "path": resolved,
                "kind": kind,
                "mimeType": mime_type or "application/octet-stream",
                "url": f"/api/assets/{asset_id}",
            }

        item = self._items[asset_id]
        return {
            "id": item["id"],
            "kind": item["kind"],
            "mimeType": item["mimeType"],
            "url": item["url"],
        }

    def lookup(self, asset_id: str) -> dict[str, Any] | None:
        return self._items.get(asset_id)


def scan_workspace(
    repo_root: Path,
    result_roots: list[Path],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]], AssetRegistry]:
    registry = AssetRegistry()

    run_details: dict[str, dict[str, Any]] = {}
    for result_root, run_dir in _discover_run_dirs(result_roots):
        detail = _build_run_detail(
            repo_root=repo_root,
            result_root=result_root,
            run_dir=run_dir,
            registry=registry,
        )
        if detail is None:
            continue
        run_details[detail["id"]] = detail

    runs = sorted(
        (_summary_from_detail(detail) for detail in run_details.values()),
        key=lambda item: (item.get("sortTimestamp") or 0.0, item.get("stepsTaken") or 0),
        reverse=True,
    )
    execution_details = _build_execution_details(runs=runs, run_details=run_details)
    execution_summaries = sorted(
        (_summary_from_execution(detail) for detail in execution_details.values()),
        key=lambda item: item.get("sortTimestamp") or 0.0,
        reverse=True,
    )

    workspace = {
        "app": {
            "name": "Benchmark Workbench",
            "version": "0.2.0",
            "tagline": "Execution-aware inspection for GUI benchmark artifacts",
        },
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repoRoot": str(repo_root.resolve()),
        "roots": [relative_path(root, repo_root) for root in result_roots if root.exists()],
        "stats": _build_workspace_stats(runs, execution_summaries),
        "facets": _build_facets(runs, execution_summaries),
        "tasks": _build_task_index(runs),
        "executions": execution_summaries,
        "runs": runs,
    }
    return workspace, run_details, execution_details, registry


def _discover_run_dirs(result_roots: list[Path]) -> list[tuple[Path, Path]]:
    discovered: dict[str, tuple[Path, Path]] = {}
    for root in result_roots:
        if not root.exists():
            continue
        resolved_root = root.resolve()
        for result_path in resolved_root.rglob(RUN_MARKER):
            if not result_path.is_file():
                continue
            run_dir = result_path.parent.resolve()
            discovered[str(run_dir)] = (resolved_root, run_dir)
    return sorted(discovered.values(), key=lambda item: str(item[1]))


def _build_run_detail(
    *,
    repo_root: Path,
    result_root: Path,
    run_dir: Path,
    registry: AssetRegistry,
) -> dict[str, Any] | None:
    args_path = run_dir / "args.json"
    result_path = run_dir / "result.json"
    trajectory_path = run_dir / "trajectory.jsonl"
    screenshots_dir = run_dir / "screenshots"

    result_payload = load_json(result_path)
    if not isinstance(result_payload, dict):
        return None
    args_payload = load_json(args_path)
    if not isinstance(args_payload, dict):
        args_payload = {}

    task_section = _section(args_payload, "task")
    execution_section = _section(args_payload, "execution")
    model_section = _section(args_payload, "model")
    platform_config_section = _section(args_payload, "platform_config")

    task_snapshot = _snapshot(task_section)
    execution_snapshot = _snapshot(execution_section)
    model_snapshot = _snapshot(model_section)
    platform_config_snapshot = _snapshot(platform_config_section)

    task_path = _path_from_section(task_section)
    execution_path = _path_from_section(execution_section)
    platform_config_path = _path_from_section(platform_config_section)

    execution_dir = _find_execution_dir(run_dir)
    runner_log_path = _find_runner_log(run_dir)
    runner_log = _load_runner_log(runner_log_path, repo_root)

    task_id = _pick(result_payload.get("task_id"), task_snapshot.get("task_id"))
    task_label = _pick(task_snapshot.get("instruction"), task_id)
    platform = _pick(result_payload.get("platform"), task_snapshot.get("platform"))
    model_id = result_payload.get("model_id")
    model_name = _pick(model_snapshot.get("model_name"), model_snapshot.get("model"), model_id)
    provider = model_snapshot.get("provider")

    execution_id = stable_id("execution", str(execution_dir.resolve()))
    execution_name = execution_dir.name
    task_order = _execution_task_order(execution_snapshot, execution_path, task_path)
    model_order = _execution_model_order(execution_snapshot, model_id)

    steps = [_normalize_step(step, registry, run_dir) for step in _load_jsonl(trajectory_path)]
    final_observation_raw = result_payload.get("final_observation")
    if not isinstance(final_observation_raw, dict):
        final_observation_raw = {}
    final_observation = _normalize_observation_block(
        final_observation_raw,
        registry,
        run_dir,
    )
    final_asset = final_observation.get("screenshot") if final_observation else None
    preview_asset = next((step.get("screenshot") for step in steps if step.get("screenshot")), None) or final_asset

    status = str(result_payload.get("status") or "ERROR").upper()
    started_at = _pick(isoformat(result_payload.get("started_at")), isoformat(args_payload.get("created_at")))
    ended_at = isoformat(result_payload.get("ended_at"))
    latency_ms = safe_float(result_payload.get("latency_ms"))
    steps_taken = safe_int(result_payload.get("steps_taken")) or len(steps)

    detail = {
        "id": stable_id("run", str(run_dir.resolve())),
        "title": task_label,
        "status": status,
        "success": status == "PASS",
        "failureMessage": _failure_message(result_payload),
        "platform": platform,
        "modelId": model_id,
        "modelName": model_name,
        "provider": provider,
        "taskId": task_id,
        "taskLabel": task_label,
        "taskPath": relative_path(task_path, repo_root),
        "tags": _string_list(_metadata(task_snapshot).get("tags")),
        "appName": _metadata(task_snapshot).get("app"),
        "description": _metadata(task_snapshot).get("description"),
        "actionMode": execution_snapshot.get("action_mode"),
        "observationMode": execution_snapshot.get("observation_mode"),
        "historyWindow": execution_snapshot.get("history_window"),
        "stepsTaken": steps_taken,
        "latencyMs": latency_ms,
        "startedAt": started_at,
        "endedAt": ended_at,
        "sortTimestamp": _sort_timestamp(ended_at, started_at, run_dir),
        "previewAsset": preview_asset,
        "finalAsset": final_asset,
        "runnerLogAvailable": runner_log is not None,
        "taskOrder": task_order,
        "modelOrder": model_order,
        "execution": {
            "id": execution_id,
            "name": execution_name,
            "sourcePath": relative_path(execution_path, repo_root),
            "dirPath": relative_path(execution_dir, repo_root),
            "dirName": execution_name,
            "metadata": _metadata(execution_snapshot),
        },
        "benchmark": {
            "id": execution_id,
            "name": execution_name,
            "runnerLogPath": relative_path(runner_log_path, repo_root),
        },
        "paths": {
            "resultRoot": relative_path(result_root, repo_root),
            "executionDir": relative_path(execution_dir, repo_root),
            "benchmarkDir": relative_path(execution_dir, repo_root),
            "benchmarkDirAbs": str(execution_dir.resolve()),
            "runDir": relative_path(run_dir, repo_root),
            "args": relative_path(args_path, repo_root) if args_path.exists() else None,
            "result": relative_path(result_path, repo_root),
            "trajectory": relative_path(trajectory_path, repo_root) if trajectory_path.exists() else None,
            "runnerLog": relative_path(runner_log_path, repo_root),
            "taskFile": relative_path(task_path, repo_root),
            "executionFile": relative_path(execution_path, repo_root),
            "platformConfig": relative_path(platform_config_path, repo_root),
        },
        "task": _build_task_payload(task_id, task_label, task_path, task_snapshot, repo_root),
        "executionSpec": _build_execution_payload(execution_path, execution_snapshot, execution_name, execution_id, repo_root),
        "model": _build_model_payload(model_id, model_snapshot),
        "platformConfig": _build_platform_config_payload(platform_config_path, platform_config_snapshot, repo_root),
        "result": result_payload,
        "args": args_payload if args_payload else None,
        "steps": steps,
        "finalObservation": final_observation,
        "runnerLog": runner_log,
        "notes": _build_notes(result_payload, runner_log),
        "artifacts": {
            "argsExists": args_path.exists(),
            "resultExists": True,
            "trajectoryExists": trajectory_path.exists(),
            "runnerLogExists": runner_log is not None,
            "screenshotsDir": relative_path(screenshots_dir, repo_root) if screenshots_dir.exists() else None,
            "files": {
                "args": _build_file_artifact(args_path, repo_root, registry, kind="json"),
                "result": _build_file_artifact(result_path, repo_root, registry, kind="json"),
                "trajectory": _build_file_artifact(trajectory_path, repo_root, registry, kind="jsonl"),
                "runnerLog": _build_file_artifact(runner_log_path, repo_root, registry, kind="log"),
            },
        },
    }
    return detail


def _build_execution_details(
    *,
    runs: list[dict[str, Any]],
    run_details: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for run in runs:
        execution = run.get("execution") or {}
        execution_id = execution.get("id")
        if not execution_id:
            continue

        group = groups.setdefault(
            execution_id,
            {
                "id": execution_id,
                "name": execution.get("name"),
                "platform": run.get("platform"),
                "sourcePath": execution.get("sourcePath"),
                "dirPaths": set(),
                "metadata": execution.get("metadata") or {},
                "actionModes": set(),
                "observationModes": set(),
                "historyWindows": set(),
                "models": {},
                "tasks": {},
                "runs": [],
                "statusCounts": {"PASS": 0, "FAIL": 0, "ERROR": 0},
                "startedAt": None,
                "endedAt": None,
                "sortTimestamp": 0.0,
            },
        )

        if execution.get("dirPath"):
            group["dirPaths"].add(execution["dirPath"])
        if run.get("actionMode"):
            group["actionModes"].add(run["actionMode"])
        if run.get("observationMode"):
            group["observationModes"].add(run["observationMode"])
        if run.get("historyWindow") is not None:
            group["historyWindows"].add(run["historyWindow"])

        model_id = run.get("modelId") or "unknown"
        model_entry = group["models"].setdefault(
            model_id,
            {
                "modelId": model_id,
                "modelName": run.get("modelName") or model_id,
                "provider": run.get("provider"),
                "runCount": 0,
                "passedRuns": 0,
                "stepsTaken": 0,
                "latencyMs": 0.0,
                "order": run.get("modelOrder"),
            },
        )
        model_entry["runCount"] += 1
        model_entry["passedRuns"] += 1 if run.get("success") else 0
        model_entry["stepsTaken"] += run.get("stepsTaken") or 0
        model_entry["latencyMs"] += run.get("latencyMs") or 0.0

        task_key = run.get("taskId") or run["id"]
        task_entry = group["tasks"].setdefault(
            task_key,
            {
                "taskId": run.get("taskId"),
                "label": run.get("taskLabel") or run.get("taskId"),
                "taskPath": run.get("taskPath"),
                "tags": set(run.get("tags") or []),
                "appName": run.get("appName"),
                "description": run.get("description"),
                "order": run.get("taskOrder"),
                "runs": [],
                "byModel": {},
                "statusCounts": {"PASS": 0, "FAIL": 0, "ERROR": 0},
            },
        )
        task_entry["runs"].append(run)
        if run.get("status") in task_entry["statusCounts"]:
            task_entry["statusCounts"][run["status"]] += 1
        task_entry["byModel"][model_id] = {
            "runId": run["id"],
            "status": run.get("status"),
            "success": run.get("success"),
            "stepsTaken": run.get("stepsTaken"),
            "latencyMs": run.get("latencyMs"),
            "startedAt": run.get("startedAt"),
            "failureMessage": run.get("failureMessage"),
        }

        group["runs"].append(run)
        if run.get("status") in group["statusCounts"]:
            group["statusCounts"][run["status"]] += 1
        group["sortTimestamp"] = max(group["sortTimestamp"], run.get("sortTimestamp") or 0.0)
        group["startedAt"] = _min_iso(group["startedAt"], run.get("startedAt"))
        group["endedAt"] = _max_iso(group["endedAt"], run.get("endedAt"))

    execution_details: dict[str, dict[str, Any]] = {}
    for execution_id, group in groups.items():
        models = sorted(
            (
                {
                    **model,
                    "successRate": _ratio(model["passedRuns"], model["runCount"]),
                    "averageSteps": round(model["stepsTaken"] / model["runCount"], 2) if model["runCount"] else 0.0,
                    "averageLatencySeconds": round((model["latencyMs"] / model["runCount"]) / 1000, 2)
                    if model["runCount"]
                    else 0.0,
                }
                for model in group["models"].values()
            ),
            key=lambda item: (
                item.get("order") if item.get("order") is not None else 10_000,
                item.get("modelName") or item.get("modelId") or "",
            ),
        )
        tasks = sorted(
            (
                {
                    "taskId": task["taskId"],
                    "label": task["label"],
                    "taskPath": task["taskPath"],
                    "tags": sorted(task["tags"]),
                    "appName": task["appName"],
                    "description": task["description"],
                    "order": task["order"],
                    "runs": sorted(
                        task["runs"],
                        key=lambda item: (
                            item.get("modelOrder") if item.get("modelOrder") is not None else 10_000,
                            item.get("modelName") or "",
                        ),
                    ),
                    "byModel": task["byModel"],
                    "statusCounts": task["statusCounts"],
                    "successRate": _ratio(task["statusCounts"]["PASS"], len(task["runs"])),
                }
                for task in group["tasks"].values()
            ),
            key=lambda item: (
                item.get("order") if item.get("order") is not None else 10_000,
                item.get("label") or item.get("taskId") or "",
            ),
        )
        execution_details[execution_id] = {
            "id": execution_id,
            "name": group["name"],
            "platform": group["platform"],
            "sourcePath": group["sourcePath"],
            "dirPaths": sorted(group["dirPaths"]),
            "metadata": group["metadata"],
            "actionModes": sorted(group["actionModes"]),
            "observationModes": sorted(group["observationModes"]),
            "historyWindows": sorted(group["historyWindows"]),
            "models": models,
            "tasks": tasks,
            "runs": group["runs"],
            "runCount": len(group["runs"]),
            "taskCount": len(tasks),
            "modelCount": len(models),
            "statusCounts": group["statusCounts"],
            "successRate": _ratio(group["statusCounts"]["PASS"], len(group["runs"])),
            "startedAt": group["startedAt"],
            "endedAt": group["endedAt"],
            "sortTimestamp": group["sortTimestamp"],
        }

    for detail in run_details.values():
        execution_id = detail.get("execution", {}).get("id")
        peers = execution_details.get(execution_id, {}).get("runs", [])
        detail["executionPeers"] = [
            {
                "id": peer["id"],
                "modelId": peer.get("modelId"),
                "modelName": peer.get("modelName"),
                "taskId": peer.get("taskId"),
                "taskLabel": peer.get("taskLabel"),
                "status": peer.get("status"),
                "success": peer.get("success"),
                "stepsTaken": peer.get("stepsTaken"),
                "latencyMs": peer.get("latencyMs"),
            }
            for peer in peers
            if peer["id"] != detail["id"]
        ]

    return execution_details


def _summary_from_execution(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": detail["id"],
        "name": detail.get("name"),
        "platform": detail.get("platform"),
        "sourcePath": detail.get("sourcePath"),
        "dirPaths": detail.get("dirPaths"),
        "runCount": detail.get("runCount"),
        "taskCount": detail.get("taskCount"),
        "modelCount": detail.get("modelCount"),
        "statusCounts": detail.get("statusCounts"),
        "successRate": detail.get("successRate"),
        "startedAt": detail.get("startedAt"),
        "endedAt": detail.get("endedAt"),
        "sortTimestamp": detail.get("sortTimestamp"),
        "models": [
            {
                "modelId": model.get("modelId"),
                "modelName": model.get("modelName"),
                "provider": model.get("provider"),
                "runCount": model.get("runCount"),
                "successRate": model.get("successRate"),
            }
            for model in detail.get("models", [])
        ],
        "tasks": [
            {
                "taskId": task.get("taskId"),
                "label": task.get("label"),
                "successRate": task.get("successRate"),
            }
            for task in detail.get("tasks", [])
        ],
        "actionModes": detail.get("actionModes"),
        "observationModes": detail.get("observationModes"),
        "historyWindows": detail.get("historyWindows"),
        "metadata": detail.get("metadata"),
    }


def _summary_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": detail["id"],
        "title": detail.get("title"),
        "status": detail.get("status"),
        "success": detail.get("success"),
        "failureMessage": detail.get("failureMessage"),
        "platform": detail.get("platform"),
        "modelId": detail.get("modelId"),
        "modelName": detail.get("modelName"),
        "provider": detail.get("provider"),
        "taskId": detail.get("taskId"),
        "taskLabel": detail.get("taskLabel"),
        "taskPath": detail.get("taskPath"),
        "tags": detail.get("tags"),
        "appName": detail.get("appName"),
        "description": detail.get("description"),
        "actionMode": detail.get("actionMode"),
        "observationMode": detail.get("observationMode"),
        "historyWindow": detail.get("historyWindow"),
        "stepsTaken": detail.get("stepsTaken"),
        "latencyMs": detail.get("latencyMs"),
        "startedAt": detail.get("startedAt"),
        "endedAt": detail.get("endedAt"),
        "sortTimestamp": detail.get("sortTimestamp"),
        "previewAsset": detail.get("previewAsset"),
        "finalAsset": detail.get("finalAsset"),
        "runnerLogAvailable": detail.get("runnerLogAvailable"),
        "execution": detail.get("execution"),
        "benchmark": detail.get("benchmark"),
        "paths": {key: value for key, value in (detail.get("paths") or {}).items() if key != "benchmarkDirAbs"},
        "finalObservation": detail.get("finalObservation"),
        "taskOrder": detail.get("taskOrder"),
        "modelOrder": detail.get("modelOrder"),
    }


def _normalize_step(step: dict[str, Any], registry: AssetRegistry, run_dir: Path) -> dict[str, Any]:
    observation = step.get("observation")
    if not isinstance(observation, dict):
        observation = {}
    normalized_observation = _normalize_observation_block(observation, registry, run_dir)
    action_parse = step.get("action_parse")
    if not isinstance(action_parse, dict):
        action_parse = {}
    action_execution = step.get("action_execution")
    if not isinstance(action_execution, dict):
        action_execution = None
    return {
        "index": safe_int(step.get("step_index")),
        "label": f"Step {safe_int(step.get('step_index')) or '?'}",
        "timestamp": isoformat(step.get("timestamp")) or step.get("timestamp"),
        "screenshot": normalized_observation.get("screenshot") if normalized_observation else None,
        "observation": normalized_observation,
        "prompt": step.get("prompt"),
        "llmResponse": step.get("llm_response"),
        "llmReasoning": step.get("llm_reasoning"),
        "actionParse": action_parse,
        "actionExecution": action_execution,
        "latencyMs": safe_float(step.get("latency_ms")),
        "nodeCount": normalized_observation.get("nodeCount") if normalized_observation else 0,
        "foregroundApp": normalized_observation.get("foregroundApp") if normalized_observation else None,
        "foregroundBundleId": normalized_observation.get("foregroundBundleId") if normalized_observation else None,
    }


def _normalize_observation_block(
    observation: dict[str, Any] | None,
    registry: AssetRegistry,
    run_dir: Path,
) -> dict[str, Any] | None:
    if not observation:
        return None

    raw = observation if isinstance(observation, dict) else {}
    screenshot_asset = registry.register(_resolve_artifact_path(raw.get("screenshot_path"), run_dir))
    a11y_tree = raw.get("a11y_tree")
    if not isinstance(a11y_tree, list):
        a11y_tree = []
    addition_info = raw.get("addition_info")
    if not isinstance(addition_info, dict):
        addition_info = {}
    normalized_nodes = [_normalize_node(node) for node in a11y_tree if isinstance(node, dict)]

    return {
        "screenshot": screenshot_asset,
        "screenshotPath": raw.get("screenshot_path"),
        "nodeCount": len(normalized_nodes),
        "nodes": normalized_nodes,
        "sampleNodes": normalized_nodes[:STEP_NODE_SAMPLE_LIMIT],
        "foregroundApp": _pick(addition_info.get("foreground_app"), raw.get("foreground_app")),
        "foregroundBundleId": _pick(addition_info.get("foreground_bundle_id"), raw.get("foreground_bundle_id")),
        "width": safe_int(addition_info.get("width")),
        "height": safe_int(addition_info.get("height")),
        "isKeyboardShown": addition_info.get("is_keyboard_shown"),
        "additionInfo": addition_info,
    }


def _normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    rect = node.get("rect")
    if not isinstance(rect, dict):
        rect = None
    return {
        "id": node.get("id"),
        "type": node.get("type"),
        "text": node.get("text"),
        "description": node.get("description"),
        "identifier": node.get("identifier"),
        "selector": node.get("selector"),
        "enabled": node.get("enabled"),
        "roleDescription": node.get("roleDescription"),
        "subrole": node.get("subrole"),
        "label": _pick(node.get("text"), node.get("description"), node.get("identifier"), node.get("selector"), node.get("type")),
        "rect": {
            "x": safe_float(_pick(rect.get("x"), rect.get("left"))) if rect else None,
            "y": safe_float(_pick(rect.get("y"), rect.get("top"))) if rect else None,
            "width": safe_float(_pick(rect.get("width"), rect.get("w"))) if rect else None,
            "height": safe_float(_pick(rect.get("height"), rect.get("h"))) if rect else None,
        }
        if rect
        else None,
    }


def _load_runner_log(path: Path | None, repo_root: Path) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    truncated = False
    if len(text) > RUNNER_LOG_MAX_CHARS:
        text = text[:RUNNER_LOG_MAX_CHARS].rstrip() + "\n...[truncated]"
        truncated = True
    return {
        "path": relative_path(path, repo_root),
        "preview": "\n".join(lines[-RUNNER_LOG_PREVIEW_LINES:]),
        "text": text,
        "lineCount": len(lines),
        "truncated": truncated,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                payload = line.strip()
                if not payload:
                    continue
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)
    except OSError:
        return []
    return records


def _build_task_payload(task_id: str | None, task_label: str | None, task_path: Path | None, task_snapshot: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    return {
        "taskId": task_id,
        "label": task_label,
        "path": relative_path(task_path, repo_root),
        "metadata": _metadata(task_snapshot),
        "snapshot": task_snapshot if task_snapshot else None,
        "catalog": None,
    }


def _build_execution_payload(
    execution_path: Path | None,
    execution_snapshot: dict[str, Any],
    execution_name: str,
    execution_id: str,
    repo_root: Path,
) -> dict[str, Any]:
    return {
        "id": execution_id,
        "name": execution_name,
        "path": relative_path(execution_path, repo_root),
        "snapshot": execution_snapshot if execution_snapshot else None,
        "actionMode": execution_snapshot.get("action_mode"),
        "observationMode": execution_snapshot.get("observation_mode"),
        "historyWindow": execution_snapshot.get("history_window"),
        "metadata": _metadata(execution_snapshot),
        "taskPaths": execution_snapshot.get("tasks") if isinstance(execution_snapshot.get("tasks"), list) else [],
        "models": execution_snapshot.get("models") if isinstance(execution_snapshot.get("models"), list) else [],
    }


def _build_model_payload(model_id: str | None, model_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "modelId": model_id,
        "provider": model_snapshot.get("provider"),
        "modelName": _pick(model_snapshot.get("model_name"), model_snapshot.get("model"), model_id),
        "snapshot": model_snapshot if model_snapshot else None,
    }


def _build_platform_config_payload(
    platform_config_path: Path | None,
    platform_config_snapshot: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any] | None:
    if platform_config_path is None and not platform_config_snapshot:
        return None
    return {
        "path": relative_path(platform_config_path, repo_root),
        "snapshot": platform_config_snapshot if platform_config_snapshot else None,
    }


def _build_file_artifact(
    path: Path | None,
    repo_root: Path,
    registry: AssetRegistry,
    *,
    kind: str,
) -> dict[str, Any] | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        size_bytes = path.stat().st_size
    except OSError:
        size_bytes = None
    return {
        "path": relative_path(path, repo_root),
        "sizeBytes": size_bytes,
        "asset": registry.register(path, kind=kind),
    }


def _build_notes(result_payload: dict[str, Any], runner_log: dict[str, Any] | None) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    message = _failure_message(result_payload)
    if message:
        notes.append({"kind": "status", "message": message})
    if runner_log and runner_log.get("truncated"):
        notes.append({"kind": "runner_log", "message": "runner.log truncated in API response"})
    return notes


def _build_workspace_stats(runs: list[dict[str, Any]], executions: list[dict[str, Any]]) -> dict[str, Any]:
    total_runs = len(runs)
    passed_runs = sum(1 for run in runs if run.get("status") == "PASS")
    failed_runs = sum(1 for run in runs if run.get("status") == "FAIL")
    error_runs = sum(1 for run in runs if run.get("status") == "ERROR")
    steps = [run.get("stepsTaken") for run in runs if isinstance(run.get("stepsTaken"), int)]
    latencies = [run.get("latencyMs") for run in runs if isinstance(run.get("latencyMs"), (int, float))]
    return {
        "executionCount": len(executions),
        "runCount": total_runs,
        "passedRuns": passed_runs,
        "failedRuns": failed_runs,
        "errorRuns": error_runs,
        "successRate": _ratio(passed_runs, total_runs),
        "taskCount": len({run.get("taskId") for run in runs if run.get("taskId")}),
        "modelCount": len({run.get("modelId") for run in runs if run.get("modelId")}),
        "averageSteps": round(sum(steps) / len(steps), 2) if steps else 0.0,
        "averageLatencySeconds": round((sum(latencies) / len(latencies)) / 1000, 2) if latencies else 0.0,
    }


def _build_task_index(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    for run in runs:
        key = run.get("taskId") or run["id"]
        entry = tasks.setdefault(
            key,
            {
                "taskId": run.get("taskId"),
                "label": run.get("taskLabel") or run.get("taskId"),
                "platforms": set(),
                "models": set(),
                "tags": set(),
                "runCount": 0,
                "passedRuns": 0,
            },
        )
        entry["runCount"] += 1
        entry["passedRuns"] += 1 if run.get("success") else 0
        if run.get("platform"):
            entry["platforms"].add(run["platform"])
        if run.get("modelId"):
            entry["models"].add(run["modelId"])
        entry["tags"].update(run.get("tags") or [])

    task_index = [
        {
            "taskId": entry["taskId"],
            "label": entry["label"],
            "runCount": entry["runCount"],
            "passedRuns": entry["passedRuns"],
            "successRate": _ratio(entry["passedRuns"], entry["runCount"]),
            "platforms": sorted(entry["platforms"]),
            "models": sorted(entry["models"]),
            "tags": sorted(entry["tags"]),
        }
        for entry in tasks.values()
    ]
    task_index.sort(key=lambda item: item.get("label") or item.get("taskId") or "")
    return task_index


def _build_facets(runs: list[dict[str, Any]], executions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "platforms": _count_values(run.get("platform") for run in runs),
        "models": _count_values(run.get("modelId") for run in runs),
        "statuses": _count_values(run.get("status") for run in runs),
        "tasks": _count_values(run.get("taskId") for run in runs),
        "executions": _count_values(execution.get("name") for execution in executions),
    }


def _find_execution_dir(run_dir: Path) -> Path:
    return run_dir.parent.resolve()


def _find_runner_log(run_dir: Path) -> Path | None:
    candidate = run_dir / "runner.log"
    return candidate if candidate.exists() else None


def _resolve_artifact_path(raw_path: Any, run_dir: Path) -> Path | None:
    path = resolve_path(raw_path, run_dir)
    if path and path.exists():
        return path
    return None


def _sort_timestamp(ended_at: str | None, started_at: str | None, path: Path) -> float:
    for value in (ended_at, started_at):
        parsed = parse_datetime(value)
        if parsed is not None:
            return parsed.timestamp()
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _failure_message(result_payload: dict[str, Any]) -> str | None:
    for key in ("evaluation", "initializer", "episode_result"):
        section = result_payload.get(key)
        if isinstance(section, dict):
            message = section.get("message")
            if message:
                return str(message)
    return None


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _snapshot(section: dict[str, Any]) -> dict[str, Any]:
    value = section.get("snapshot")
    return value if isinstance(value, dict) else {}


def _path_from_section(section: dict[str, Any]) -> Path | None:
    raw_path = section.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    try:
        return Path(raw_path).resolve()
    except OSError:
        return None


def _execution_task_order(execution_snapshot: dict[str, Any], execution_path: Path | None, task_path: Path | None) -> int | None:
    raw_tasks = execution_snapshot.get("tasks")
    if not isinstance(raw_tasks, list) or task_path is None:
        return None
    normalized_task_path = str(task_path.resolve())
    for index, item in enumerate(raw_tasks):
        if not isinstance(item, str):
            continue
        candidate = Path(item)
        if not candidate.is_absolute() and execution_path is not None:
            candidate = (execution_path.parent / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if str(candidate) == normalized_task_path:
            return index
    return None


def _execution_model_order(execution_snapshot: dict[str, Any], model_id: str | None) -> int | None:
    raw_models = execution_snapshot.get("models")
    if not isinstance(raw_models, list) or model_id is None:
        return None
    for index, item in enumerate(raw_models):
        if item == model_id:
            return index
    return None


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("metadata")
    return value if isinstance(value, dict) else {}


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


def _count_values(values: Any) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        if value in (None, ""):
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return [{"value": key, "count": counts[key]} for key in sorted(counts)]


def _pick(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}, ()):
            return value
    return None


def _ratio(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _min_iso(left: str | None, right: str | None) -> str | None:
    left_dt = parse_datetime(left)
    right_dt = parse_datetime(right)
    if left_dt is None:
        return right
    if right_dt is None:
        return left
    return left if left_dt <= right_dt else right


def _max_iso(left: str | None, right: str | None) -> str | None:
    left_dt = parse_datetime(left)
    right_dt = parse_datetime(right)
    if left_dt is None:
        return right
    if right_dt is None:
        return left
    return left if left_dt >= right_dt else right
