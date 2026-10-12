"""Evaluator for single-screen Linux + Android tasks (phone mirrored with scrcpy).

Passes only when the phone-side evaluator (run from the host over adb), the Linux-side
evaluator, and the GUI-only rule all pass. The rule: the agent must use the phone
through its window, so any executed action that invokes or types ``adb``/``scrcpy``
fails the task.

params:
  android: {evaluator_id, params}
  linux:   {evaluator_id, params} or a list of them (all must pass)
  forbidden_patterns: regexes checked against each executed action (default: adb, scrcpy)
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from core.evaluation.loader import load_evaluator
from initializers.linux.android_companion import phone_controller
from platforms.linux.android_companion import CompanionSettings

DEFAULT_FORBIDDEN = [r"\badb\b", r"\bscrcpy\b"]


def _status(result: Any) -> str:
    return str(getattr(result.status, "value", result.status)).upper()


def forbidden_actions(trajectory_path: Any, patterns: list[str]) -> list[dict[str, Any]]:
    """Executed actions whose code matches a forbidden pattern."""
    hits: list[dict[str, Any]] = []
    if not trajectory_path:
        return hits
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    try:
        lines = open(str(trajectory_path), encoding="utf-8").read().splitlines()
    except OSError:
        return hits
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        action = record.get("action_parse") or {}
        code = str(action.get("code") or "") if isinstance(action, Mapping) else str(action)
        matched = [pattern.pattern for pattern in compiled if pattern.search(code)]
        if matched:
            hits.append({"step": record.get("step_index"), "patterns": matched, "code": code[:300]})
    return hits


class LinuxAndroidCompositeEvaluator(BaseEvaluator):
    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        checks: dict[str, Any] = {}

        hits = forbidden_actions(context.get("trajectory_path"), list(params.get("forbidden_patterns") or DEFAULT_FORBIDDEN))
        checks["gui_only"] = {"passed": not hits, "violations": hits}

        try:
            phone = phone_controller(CompanionSettings.from_env())
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Companion phone is not reachable: {exc}", metadata=checks)
        android = dict(params.get("android") or {})
        result = load_evaluator(android["evaluator_id"]).evaluate(
            {**context, "controller": phone, "params": dict(android.get("params") or {})})
        checks["android"] = {"status": _status(result), "message": result.message, "metadata": result.metadata}

        linux_specs = params.get("linux") or []
        linux_specs = [linux_specs] if isinstance(linux_specs, Mapping) else list(linux_specs)
        results = []
        for spec in linux_specs:
            result = load_evaluator(spec["evaluator_id"]).evaluate({**context, "params": dict(spec.get("params") or {})})
            results.append({"status": _status(result), "message": result.message, "metadata": result.metadata})
        statuses = [item["status"] for item in results]
        status = "ERROR" if "ERROR" in statuses else ("PASS" if results and all(s == "PASS" for s in statuses) else "FAIL")
        checks["linux"] = {"status": status, "message": "; ".join(item["message"] for item in results if item["status"] != "PASS"),
                           "checks": results}

        errors = [name for name in ("android", "linux") if checks[name]["status"] == "ERROR"]
        if errors:
            return EvalResult(status=EvalStatus.ERROR, message="Evaluator error: " + ", ".join(errors), metadata=checks)
        failed = [name for name in ("gui_only", "android", "linux")
                  if not (checks[name].get("passed") if name == "gui_only" else checks[name]["status"] == "PASS")]
        if failed:
            details = {"gui_only": "adb/scrcpy used by the agent", "android": checks["android"]["message"],
                       "linux": checks["linux"]["message"]}
            return EvalResult(status=EvalStatus.FAIL, message="; ".join(f"{name}: {details[name]}" for name in failed),
                              metadata=checks)
        return EvalResult(status=EvalStatus.PASS, message="Phone and desktop results verified", metadata=checks)
