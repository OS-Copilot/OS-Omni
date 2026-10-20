"""Evaluator for single-screen Linux + Android tasks (phone mirrored with scrcpy).

Passes only when the phone-side evaluator (run from the host over adb), the Linux-side
evaluator, and the GUI-only rule all pass. The rule: the agent must use the phone
through its window, so any executed action that invokes or types ``adb``/``scrcpy``
fails the task.

params:
  android: {evaluator_id, params} or a list of them, run against the phone (all must pass)
  linux:   {evaluator_id, params} or a list of them, run against the desktop (all must pass)
  phone_copies: [{desktop_path, phone_path}] files the agent must copy from the desktop to the
           phone; each phone copy must have the desktop file's SHA-256
  forbidden_patterns: regexes checked against each executed action (default: adb, scrcpy)
"""

from __future__ import annotations

import ast
import io
import json
import re
import shlex
import tokenize
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from core.evaluation.loader import load_evaluator
from initializers.linux.android_companion import phone_controller
from platforms.linux.android_companion import CompanionSettings

DEFAULT_FORBIDDEN = [r"\badb\b", r"\bscrcpy\b"]


def _status(result: Any) -> str:
    return str(getattr(result.status, "value", result.status)).upper()


def action_code(action_parse: Any) -> str:
    """The code of an executed action. Episode trajectories store the parsed action as
    {"status", "action": <repr of the action dict>, "error"}; a plain {"code": ...} also works."""
    if not isinstance(action_parse, Mapping):
        return str(action_parse or "")
    if "code" in action_parse:
        return str(action_parse.get("code") or "")
    action = action_parse.get("action")
    if isinstance(action, str):
        try:
            action = ast.literal_eval(action)
        except (ValueError, SyntaxError):
            return action
    return str(action.get("code") or "") if isinstance(action, Mapping) else str(action or "")


def _strip_comments(code: str) -> str:
    """Drop Python comments, so a note such as "# focus the scrcpy window" is not a violation."""
    try:
        tokens = [token for token in tokenize.generate_tokens(io.StringIO(code).readline) if token.type != tokenize.COMMENT]
        return tokenize.untokenize(tokens)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return code


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
        code = _strip_comments(action_code(record.get("action_parse")))
        matched = [pattern.pattern for pattern in compiled if pattern.search(code)]
        if matched:
            hits.append({"step": record.get("step_index"), "patterns": matched, "code": code[:300]})
    return hits


def _run_all(specs: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    specs = [specs] if isinstance(specs, Mapping) else list(specs or [])
    results = []
    for spec in specs:
        result = load_evaluator(spec["evaluator_id"]).evaluate({**context, "params": dict(spec.get("params") or {})})
        results.append({"status": _status(result), "message": result.message, "metadata": result.metadata})
    statuses = [item["status"] for item in results]
    status = "ERROR" if "ERROR" in statuses else ("PASS" if results and all(s == "PASS" for s in statuses) else "FAIL")
    return {"status": status, "message": "; ".join(item["message"] for item in results if item["status"] != "PASS"),
            "checks": results}


def linux_file_sha256(desktop: Any, path: str) -> str:
    reply = desktop.run_bash_script(f"sha256sum {shlex.quote(path)} 2>/dev/null | cut -c1-64", timeout=30)
    return str(reply.get("output") or "").strip()


def _phone_copy(phone: Any, desktop: Any, item: dict[str, Any], desktop_sha256: Any = linux_file_sha256) -> dict[str, Any]:
    """The phone file must exist and have the desktop file's SHA-256."""
    desktop_path, phone_path = str(item["desktop_path"]), str(item["phone_path"])
    try:
        desktop_sha = desktop_sha256(desktop, desktop_path)
        phone_sha = str(phone.execute_adb(["shell", f"sha256sum {shlex.quote(phone_path)} 2>/dev/null | cut -c1-64"]) or "").strip()
    except Exception as exc:
        return {"status": "ERROR", "message": f"copy check failed: {exc}", "metadata": item}
    metadata = {**item, "desktop_sha256": desktop_sha, "phone_sha256": phone_sha}
    if len(desktop_sha) != 64:
        return {"status": "FAIL", "message": f"desktop file missing: {desktop_path}", "metadata": metadata}
    if phone_sha != desktop_sha:
        return {"status": "FAIL", "message": f"phone copy missing or different: {phone_path}", "metadata": metadata}
    return {"status": "PASS", "message": "phone copy matches", "metadata": metadata}


class LinuxAndroidCompositeEvaluator(BaseEvaluator):
    # The desktop half: params key and how a desktop file's SHA-256 is read.
    DESKTOP = "linux"

    def desktop_sha256(self, desktop: Any, path: str) -> str:
        return linux_file_sha256(desktop, path)

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        desk = self.DESKTOP
        params = dict(context.get("params") or {})
        checks: dict[str, Any] = {}

        hits = forbidden_actions(context.get("trajectory_path"), list(params.get("forbidden_patterns") or DEFAULT_FORBIDDEN))
        checks["gui_only"] = {"passed": not hits, "violations": hits}

        try:
            phone = phone_controller(CompanionSettings.from_env())
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Companion phone is not reachable: {exc}", metadata=checks)
        checks["android"] = _run_all(params.get("android"), {**context, "controller": phone})
        checks[desk] = _run_all(params.get(desk), context)
        copies = [_phone_copy(phone, context.get("controller"), dict(item), self.desktop_sha256)
                  for item in params.get("phone_copies") or []]
        if copies:
            statuses = [item["status"] for item in copies]
            checks["android"]["checks"].extend(copies)
            if "ERROR" in statuses:
                checks["android"]["status"] = "ERROR"
            elif "FAIL" in statuses and checks["android"]["status"] == "PASS":
                checks["android"]["status"] = "FAIL"
            checks["android"]["message"] = "; ".join(item["message"] for item in checks["android"]["checks"]
                                                     if item["status"] != "PASS")

        errors = [name for name in ("android", desk) if checks[name]["status"] == "ERROR"]
        if errors:
            return EvalResult(status=EvalStatus.ERROR, message="Evaluator error: " + ", ".join(errors), metadata=checks)
        failed = [name for name in ("gui_only", "android", desk)
                  if not (checks[name].get("passed") if name == "gui_only" else checks[name]["status"] == "PASS")]
        if failed:
            details = {"gui_only": "adb/scrcpy used by the agent", "android": checks["android"]["message"],
                       desk: checks[desk]["message"]}
            return EvalResult(status=EvalStatus.FAIL, message="; ".join(f"{name}: {details[name]}" for name in failed),
                              metadata=checks)
        return EvalResult(status=EvalStatus.PASS, message="Phone and desktop results verified", metadata=checks)
