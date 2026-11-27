#!/usr/bin/env python3
"""macOS / iOS formal-evaluation resumable serial queue.

Only macOS and iOS are supported. Each task reuses the platform's existing
``run_benchmark_command`` (which owns the clone -> run -> cleanup lifecycle);
this module never reimplements cloning, never touches committed default
configs, never auto-creates a gate file, never auto-releases a pause on a
timer, and never hands model trajectories to any oracle adapter.

This module only implements audit-record constraints; it never changes task
semantics or judging. Every attempt keeps its own evidence directory.

Layout (independent from Android ``local_eval``)::

    results/author_eval/<platform>/
        queue.json            serial queue state (resumable, atomically written)
        queue.lock            lock against duplicate runners (atomic + flock)
        <safe_task_id>/
            run_meta.json     original task / model / step-limit / version hash + run metadata
            verdict.json      {"status": ..., "valid": ...} cache of the latest outcome
            attempt_001/      per-attempt evidence (result.json lives here)
            attempt_002/

Gate file (external, explicit -- this module never creates it)::

    {"platform": "ios", "formal_run_approved": true,
     "clone_state": "fresh", "approved_by": "<who>",
     "env_preflight_passed": true,
     "env_preflight_report": "/path/to/preflight-report.json",
     "initial_fail_evidence": "/path/to/initial-fail-evidence.json",
     "manifest_sha256": "<sha256 of tasks/v1/manifest.json>",
     "code_version": "<code version hash for the platform>"}

A formal run is allowed only when the gate file approves this platform AND
the platform environment preflight passes. A fresh clone state of
``audit_complete`` is always rejected.
"""

from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.platform_shared.benchmark_runner import BaseBenchmarkRunner

MODEL_ID = "deepseek_flash"
ACTION_MODE = "code_adapter"
OBSERVATION_MODE = "screenshot_only"
HISTORY_WINDOW = 3
MAX_STEP_CAP = 180
AUDIT_PAUSE_EVERY_N_SUCCESS = 3
AUDIT_PAUSE_EVERY_N_COMPLETIONS = 3
SUPPORTED_PLATFORMS = ("ios", "macos")
MANIFEST_PATH = REPO_ROOT / "tasks" / "v1" / "manifest.json"
RESULTS_ROOT = REPO_ROOT / "results" / "author_eval"
QUEUE_FILENAME = "queue.json"
LOCK_FILENAME = "queue.lock"
META_FILENAME = "run_meta.json"
VERDICT_FILENAME = "verdict.json"
ATTEMPT_PREFIX = "attempt_"
QUEUE_VERSION = 1
SCRIPT_VERSION = "2.0.0"

FORBIDDEN_CLONE_STATES = {"audit_complete", "audit-complete", "audited"}
RETESTABLE_STATUS = "environment_excluded"
CONFIRMED_MODEL_FAIL = "confirmed_model_fail"
TERMINAL_AUDITED = (CONFIRMED_MODEL_FAIL,)
VALID_REUSABLE_STATUS = "PASS"


class QueueError(RuntimeError):
    """Raised for queue / gate / lock / preflight refusals."""


class GateError(QueueError):
    """Raised when the external gate file refuses a formal run."""


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def effective_max_steps(original_max_steps: int, cap: int = MAX_STEP_CAP) -> int:
    """Return ``min(original, cap)``; a lower original limit is preserved."""
    original = int(original_max_steps)
    if original <= 0:
        raise ValueError(f"original_max_steps must be positive, got {original}")
    return min(original, int(cap))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_task_dir(task_id: str) -> str:
    return BaseBenchmarkRunner.safe_name(task_id)


def load_manifest_tasks(
    manifest_path: str | Path = MANIFEST_PATH,
    platform: str = "ios",
) -> List[Dict[str, str]]:
    """Parse the real manifest and return entries for ``platform``."""
    if platform not in SUPPORTED_PLATFORMS:
        raise QueueError(f"unsupported platform: {platform}")
    with Path(manifest_path).open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    entries: List[Dict[str, str]] = []
    for item in manifest.get("tasks", []):
        if str(item.get("platform", "")).strip() != platform:
            continue
        entries.append(
            {
                "task_id": str(item.get("task_id", "")).strip(),
                "task_path": str(item.get("task_path", "")).strip(),
            }
        )
    entries = [e for e in entries if e["task_id"] and e["task_path"]]
    entries.sort(key=lambda e: e["task_id"])
    return entries


def read_original_max_steps(task_path: str | Path, platform: str) -> int:
    """Read the original per-task step limit via the real task loader."""
    resolved = Path(task_path)
    if not resolved.is_absolute():
        resolved = (REPO_ROOT / resolved).resolve()
    if platform == "ios":
        from platforms.ios.core.types import load_task_from_file
    elif platform == "macos":
        from platforms.macos.host.core.types import load_task_from_file
    else:
        raise QueueError(f"unsupported platform: {platform}")
    try:
        task = load_task_from_file(str(resolved))
        return int(task.max_steps)
    except Exception:
        text = resolved.read_text(encoding="utf-8")
        match = re.search(r"max_steps:\s*(\d+)", text)
        if not match:
            raise QueueError(f"cannot resolve max_steps from {resolved}")
        return int(match.group(1))


def _resolve_task_file(task_path: str | Path) -> Path:
    resolved = Path(task_path)
    if not resolved.is_absolute():
        resolved = (REPO_ROOT / resolved).resolve()
    return resolved


def manifest_hash(manifest_path: str | Path = MANIFEST_PATH) -> str:
    """sha256 of the manifest file the plan was built from."""
    return sha256_file(Path(manifest_path))


def git_revision() -> str:
    """Current Git HEAD revision for metadata only (never cache identity)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).stdout.decode().strip()
    except Exception:
        return ""
    return out


def platform_code_files(platform: str) -> List[Path]:
    """Conservative content closure for the platform's common code version.

    Covers this queue module, the platform's runner / core-execution /
    runtime tree, and the shared core execution + model-config packages.
    The two platforms' file sets are disjoint except for the shared core
    files, so an unrelated fix on one platform never invalidates the
    other's cached verdicts. Only files that exist are returned.
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise QueueError(f"unsupported platform: {platform}")
    shared_dirs = [
        REPO_ROOT / "core" / "platform_shared",
        REPO_ROOT / "core" / "evaluation",
        REPO_ROOT / "core" / "init",
        REPO_ROOT / "core" / "llm",
    ]
    if platform == "ios":
        platform_dirs = [
            REPO_ROOT / "platforms" / "ios" / "runners",
            REPO_ROOT / "platforms" / "ios" / "core",
            REPO_ROOT / "platforms" / "ios" / "runtime_env",
        ]
        platform_files = [REPO_ROOT / "platforms" / "ios" / "runtime_config.py"]
    else:
        platform_dirs = [
            REPO_ROOT / "platforms" / "macos" / "host" / "runners",
            REPO_ROOT / "platforms" / "macos" / "host" / "core",
            REPO_ROOT / "platforms" / "macos" / "host" / "runtime_env",
        ]
        platform_files = [REPO_ROOT / "platforms" / "macos" / "runtime_config.py"]
    seen: set[str] = set()
    ordered: List[Path] = []
    self_path = Path(__file__).resolve()
    seen.add(str(self_path))
    ordered.append(self_path)
    for extra in platform_files:
        if extra.is_file() and str(extra) not in seen:
            seen.add(str(extra))
            ordered.append(extra)
    for directory in shared_dirs + platform_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            key = str(path)
            if key not in seen and path.is_file():
                seen.add(key)
                ordered.append(path)
    return ordered


def relevant_sources(platform: str) -> List[Path]:
    """Legacy alias: the platform's common content closure."""
    return platform_code_files(platform)


def code_version_hash(platform: str) -> str:
    """Content-only hash of the platform's common runtime/runner/core/model code.

    Git HEAD is deliberately excluded: unrelated commits must not
    invalidate valid results. Use :func:`git_revision` for metadata.
    """
    digest = hashlib.sha256()
    for src in platform_code_files(platform):
        try:
            rel = src.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = src.name
        digest.update(rel.encode() + b"\0" + sha256_file(src).encode() + b"\n")
    return digest.hexdigest()


_TASK_ID_RE = re.compile(
    r"(?m)^\s*(initializer_id|evaluator_id)\s*:\s*([A-Za-z0-9_.\-]+)"
)


def _module_to_path(dotted: str) -> Optional[Path]:
    """Resolve a repo-local dotted module to its .py file, if present."""
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return None
    candidate = REPO_ROOT.joinpath(*parts).with_suffix(".py")
    if candidate.is_file():
        return candidate
    init_candidate = REPO_ROOT.joinpath(*parts, "__init__.py")
    if init_candidate.is_file():
        return init_candidate
    return None


def _package_of(path: Path) -> str:
    """Dotted package containing ``path`` (empty for the repo root)."""
    try:
        rel = path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return ""
    parent = rel.parent
    if str(parent) in (".", ""):
        return ""
    return ".".join(parent.parts)


def _iter_local_imports(source_path: Path) -> List[str]:
    """Dotted module names imported by ``source_path`` (AST, best effort)."""
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    package = _package_of(source_path)
    found: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                pkg_parts = package.split(".") if package else []
                up = node.level - 1
                base = pkg_parts[: len(pkg_parts) - up] if up <= len(pkg_parts) else []
                if node.module:
                    found.append(".".join(base + [node.module]))
                else:
                    for alias in node.names:
                        if alias.name and alias.name != "*":
                            found.append(".".join(base + [alias.name]))
            elif node.module:
                found.append(node.module)
    return found


def task_dependency_files(task_path: str | Path) -> List[Path]:
    """Repo-local transitive Python closure for a task YAML's modules.

    Seeds are the ``initializer_id`` / ``evaluator_id`` modules named in
    the YAML file; the closure follows their AST imports to repo-local
    files (bounded at 500 files). Returns the task file plus every
    resolved dependency, sorted.
    """
    task_file = _resolve_task_file(task_path)
    try:
        text = task_file.read_text(encoding="utf-8")
    except Exception as exc:
        raise QueueError(f"cannot read task file {task_file}: {exc}")
    seeds: List[str] = []
    for kind, dotted in _TASK_ID_RE.findall(text):
        _ = kind
        module = dotted.split(":")[0].strip()
        if module:
            seeds.append(module)
    ordered: List[Path] = []
    seen: set[str] = set()
    queue_paths: List[Path] = []
    for seed in seeds:
        resolved = _module_to_path(seed)
        if resolved is None:
            raise QueueError(
                f"task module not found in repository: {seed!r} "
                f"(from {task_file})"
            )
        queue_paths.append(resolved)
    while queue_paths and len(seen) < 500:
        current = queue_paths.pop(0)
        key = str(current.resolve())
        if key in seen:
            continue
        seen.add(key)
        ordered.append(current)
        for imported in _iter_local_imports(current):
            target = _module_to_path(imported)
            if target is not None and str(target.resolve()) not in seen:
                queue_paths.append(target)
            else:
                # Try progressively shorter prefixes (e.g. a.b.c -> a.b).
                parts = imported.split(".")
                for width in range(len(parts) - 1, 0, -1):
                    prefix = ".".join(parts[:width])
                    target = _module_to_path(prefix)
                    if target is not None and str(target.resolve()) not in seen:
                        queue_paths.append(target)
                        break
    ordered.sort(key=lambda p: p.resolve().as_posix())
    return [task_file, *ordered]


TASK_IMPLEMENTATION_MISSING_PREFIX = "missing:"


def task_implementation_hash(task_path: str | Path) -> str:
    """Content hash of the task file plus its initializer/evaluator closure.

    Returns a ``missing:<module>`` marker when a named module has no
    repo-local file; such markers never match cached evidence.
    """
    task_file = _resolve_task_file(task_path)
    try:
        files = task_dependency_files(task_file)
    except QueueError as exc:
        message = str(exc)
        marker = message.split("task module not found in repository:")[-1].strip()
        return f"{TASK_IMPLEMENTATION_MISSING_PREFIX}{marker or task_file.name}"
    digest = hashlib.sha256()
    for path in files:
        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = path.name
        try:
            content_hash = sha256_file(path)
        except OSError:
            return f"{TASK_IMPLEMENTATION_MISSING_PREFIX}{rel}"
        digest.update(rel.encode() + b"\0" + content_hash.encode() + b"\n")
    return digest.hexdigest()


def expected_evidence(
    entry: Dict[str, Any],
    platform: str,
) -> Dict[str, Any]:
    """Fingerprint a cached verdict must carry to be reusable."""
    task_file = _resolve_task_file(entry["task_path"])
    return {
        "task_sha256": sha256_file(task_file),
        "task_implementation_sha256": task_implementation_hash(task_file),
        "model": entry.get("model", MODEL_ID),
        "action_mode": entry.get("action_mode", ACTION_MODE),
        "observation_mode": entry.get("observation_mode", OBSERVATION_MODE),
        "history_window": int(entry.get("history_window", HISTORY_WINDOW)),
        "original_max_steps": int(entry["original_max_steps"]),
        "effective_max_steps": int(entry["effective_max_steps"]),
        "code_version": code_version_hash(platform),
    }


def _evidence_matches(verdict: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    # Verdicts written before the per-task implementation hash existed
    # are never reusable: the missing hash is rejected, not defaulted.
    for key in (
        "task_sha256",
        "task_implementation_sha256",
        "model",
        "action_mode",
        "observation_mode",
        "history_window",
        "original_max_steps",
        "effective_max_steps",
        "code_version",
    ):
        if key not in verdict or key not in expected:
            return False
        if verdict.get(key) != expected.get(key):
            return False
    for key in ("task_implementation_sha256",):
        value = str(verdict.get(key, ""))
        if value.startswith(TASK_IMPLEMENTATION_MISSING_PREFIX):
            return False
        if str(expected.get(key, "")).startswith(
            TASK_IMPLEMENTATION_MISSING_PREFIX
        ):
            return False
    return True


def read_gate(
    gate_path: str | Path,
    platform: str,
    manifest_path: str | Path = MANIFEST_PATH,
) -> Dict[str, Any]:
    """Explicitly read and validate the external gate file.

    This module never creates the gate file. Besides the string approval,
    the gate must bind the real environment preflight record, the manifest
    hash and the current code version hash. Raises GateError on any problem.
    """
    path = Path(gate_path)
    if not path.exists():
        raise GateError(f"gate file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateError(f"gate file is not valid JSON: {path} ({exc})")
    if not isinstance(payload, dict):
        raise GateError(f"gate file must contain an object: {path}")
    gate_platform = str(payload.get("platform", "")).strip()
    if gate_platform != platform:
        raise GateError(
            f"gate platform mismatch: gate={gate_platform!r} queue={platform!r}"
        )
    if payload.get("formal_run_approved") is not True:
        raise GateError(f"gate does not approve a formal run: {path}")
    clone_state = str(payload.get("clone_state", "")).strip().lower()
    if not clone_state:
        raise GateError(f"gate is missing clone_state: {path}")
    if clone_state in FORBIDDEN_CLONE_STATES:
        raise GateError(
            f"fresh clone state must not be audit-complete: {clone_state!r}"
        )
    if not str(payload.get("approved_by", "")).strip():
        raise GateError(f"gate is missing approved_by: {path}")
    if payload.get("env_preflight_passed") is not True:
        raise GateError(f"gate lacks an explicit env_preflight_passed:true: {path}")
    report_ref = str(payload.get("env_preflight_report", "")).strip()
    if not report_ref:
        raise GateError(f"gate is missing env_preflight_report path: {path}")
    report_path = Path(report_ref)
    if not report_path.is_absolute():
        report_path = (path.parent / report_path).resolve()
    if not report_path.is_file():
        raise GateError(f"gate preflight report not found: {report_path}")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateError(f"preflight report is not valid JSON: {report_path} ({exc})")
    if not isinstance(report, dict) or report.get("passed") is not True:
        raise GateError(f"preflight report does not record a pass: {report_path}")
    if str(report.get("platform", "")).strip() != platform:
        raise GateError(f"preflight report platform mismatch: {report_path}")
    if not isinstance(report.get("checks"), dict) or not report["checks"]:
        raise GateError(f"preflight report has no recorded checks: {report_path}")
    evidence_ref = str(payload.get("initial_fail_evidence", "")).strip()
    if not evidence_ref:
        raise GateError(f"gate is missing initial_fail_evidence path: {path}")
    evidence_path = Path(evidence_ref)
    if not evidence_path.is_absolute():
        evidence_path = (path.parent / evidence_path).resolve()
    if not evidence_path.is_file():
        raise GateError(f"gate initial-fail evidence not found: {evidence_path}")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateError(
            f"initial-fail evidence is not valid JSON: {evidence_path} ({exc})"
        )
    if not isinstance(evidence, dict) or not evidence:
        raise GateError(
            f"initial-fail evidence must be a non-empty task_id->status map: "
            f"{evidence_path}"
        )
    expected_manifest = manifest_hash(manifest_path)
    if str(payload.get("manifest_sha256", "")).strip() != expected_manifest:
        raise GateError(
            f"gate manifest_sha256 does not match {manifest_path}: {path}"
        )
    expected_code = code_version_hash(platform)
    if str(payload.get("code_version", "")).strip() != expected_code:
        raise GateError(f"gate code_version does not match current sources: {path}")
    payload["_preflight_report_path"] = str(report_path)
    payload["_initial_fail_evidence_path"] = str(evidence_path)
    return payload


def check_initial_fail_evidence(
    gate: Dict[str, Any],
    task_ids: List[str],
    *,
    task_paths: Optional[Dict[str, str]] = None,
) -> None:
    """Every selected task must have a hashed initial FAIL record.

    Each evidence entry must be an object ``{"status": "FAIL",
    "task_sha256": ..., "task_implementation_sha256": ..., "evidence":
    <path>}`` whose hashes match the current task file and its
    initializer/evaluator closure. Bare ``"FAIL"`` strings are rejected
    for formal runs: without source hashes a stale precheck cannot be
    detected. Only the tasks selected for execution are checked, so a
    first formal run need not precheck all 48 tasks.
    """
    evidence_path = Path(str(gate["_initial_fail_evidence_path"]))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise GateError(
            f"initial-fail evidence must be a task_id->entry map: {evidence_path}"
        )
    problems: List[str] = []
    for task_id in task_ids:
        record = evidence.get(task_id)
        if isinstance(record, str):
            problems.append(
                f"{task_id}: unhashed string evidence; re-record the "
                "initial FAIL with task hashes"
            )
            continue
        if not isinstance(record, dict):
            problems.append(f"{task_id}: missing initial-fail entry")
            continue
        if str(record.get("status", "")).strip() != "FAIL":
            problems.append(f"{task_id}: initial-fail status is not FAIL")
            continue
        task_ref = (task_paths or {}).get(task_id)
        if task_ref is not None:
            task_file = _resolve_task_file(task_ref)
            try:
                current_task_hash = sha256_file(task_file)
            except OSError as exc:
                raise GateError(f"cannot hash task file {task_file}: {exc}")
            current_impl_hash = task_implementation_hash(task_file)
            if record.get("task_sha256") != current_task_hash:
                problems.append(f"{task_id}: stale task_sha256 in precheck")
                continue
            if record.get("task_implementation_sha256") != current_impl_hash:
                problems.append(
                    f"{task_id}: stale task_implementation_sha256 in precheck"
                )
                continue
            if str(current_impl_hash).startswith(
                TASK_IMPLEMENTATION_MISSING_PREFIX
            ):
                problems.append(f"{task_id}: task modules are missing")
                continue
        if not str(record.get("evidence", "")).strip():
            problems.append(f"{task_id}: initial-fail entry lacks evidence path")
            continue
        evidence_ref = Path(str(record["evidence"]))
        if not evidence_ref.is_absolute():
            evidence_ref = (evidence_path.parent / evidence_ref).resolve()
        if not evidence_ref.exists():
            problems.append(f"{task_id}: initial-fail evidence file missing")
            continue
    if problems:
        preview = "; ".join(problems[:3])
        raise GateError(
            f"initial-fail evidence invalid for {len(problems)} task(s) "
            f"({preview}): {evidence_path}"
        )


def _run_cmd(
    argv: List[str], timeout: int = 20, env: Optional[Dict[str, str]] = None
) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=env,
        )
        return proc.returncode == 0, proc.stdout.decode(errors="replace")
    except Exception as exc:
        return False, str(exc)


def _appium_healthy(host: str, port: int, timeout: float = 4.0) -> Tuple[bool, str]:
    url = f"http://{host}:{port}/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(4096).decode(errors="replace")
        try:
            data = json.loads(body)
        except Exception:
            return False, f"appium {url} returned non-JSON status"
        value = data.get("value", data) if isinstance(data, dict) else None
        ready = isinstance(value, dict) and value.get("ready") is True
        if ready or (isinstance(data, dict) and "value" in data):
            return True, f"appium {url} healthy"
        return False, f"appium {url} unhealthy: {body[:200]}"
    except Exception as exc:
        return False, f"appium {url} unreachable: {exc}"


def preflight_evidence(
    platform: str,
    *,
    ios_clone_source_udid: Optional[str] = None,
    ios_direct_udid: Optional[str] = None,
    macos_base_vm_name: Optional[str] = None,
    macos_vm_provider: Optional[str] = None,
    macos_storage_dir: Optional[str] = None,
    appium_host: str = "127.0.0.1",
    appium_port: int = 4723,
) -> Dict[str, Any]:
    """Probe the real environment without starting any runtime.

    iOS: requires xcrun, a listed available simctl device AND runtime, plus a
    healthy Appium server. macOS/tart: requires tart, an existing TART_HOME
    holding the named base VM. macOS/virtualbuddy: requires the app bundle.
    """
    checks: Dict[str, Any] = {}
    if platform == "ios":
        udid = (ios_direct_udid or ios_clone_source_udid or "").strip()
        if not udid:
            return {"passed": False, "platform": platform, "checks": {},
                    "detail": "iOS clone-source UDID is required"}
        if not re.fullmatch(r"[0-9A-Fa-f-]{8,}", udid):
            return {"passed": False, "platform": platform, "checks": {},
                    "detail": f"iOS clone-source UDID looks invalid: {udid!r}"}
        if shutil.which("xcrun") is None:
            return {"passed": False, "platform": platform, "checks": {},
                    "detail": "xcrun not found; iOS simctl preflight failed"}
        checks["xcrun"] = "found"
        ok, devices_out = _run_cmd(["xcrun", "simctl", "list", "devices", "available"])
        if not ok:
            return {"passed": False, "platform": platform, "checks": checks,
                    "detail": f"simctl devices probe failed: {devices_out[:200]}"}
        checks["simctl_devices"] = "listed"
        has_device = bool(re.search(r"\([0-9A-Fa-f-]{8,}\)\s*\(", devices_out))
        if not has_device:
            return {"passed": False, "platform": platform, "checks": checks,
                    "detail": "simctl lists no available device"}
        ok, runtimes_out = _run_cmd(["xcrun", "simctl", "list", "runtimes"])
        if not ok or not runtimes_out.strip():
            return {"passed": False, "platform": platform, "checks": checks,
                    "detail": "simctl lists no runtimes"}
        checks["simctl_runtimes"] = "listed"
        healthy, appium_detail = _appium_healthy(appium_host, appium_port)
        checks["appium"] = appium_detail
        if not healthy:
            return {"passed": False, "platform": platform, "checks": checks,
                    "detail": appium_detail}
        return {"passed": True, "platform": platform, "checks": checks,
                "detail": f"ios simctl device+runtime available; {appium_detail}; "
                          f"{'direct device' if ios_direct_udid else 'clone source'}={udid}"}
    if platform == "macos":
        base_vm = (macos_base_vm_name or "").strip()
        if not base_vm:
            return {"passed": False, "platform": platform, "checks": {},
                    "detail": "macOS base VM name is required"}
        provider = (macos_vm_provider or "tart").strip().lower()
        if provider == "tart":
            if shutil.which("tart") is None:
                return {"passed": False, "platform": platform, "checks": {},
                        "detail": "tart not found; macOS preflight failed"}
            checks["tart"] = "found"
            tart_home = (macos_storage_dir or os.environ.get("TART_HOME", "")).strip()
            if not tart_home:
                return {"passed": False, "platform": platform, "checks": checks,
                        "detail": "TART_HOME is not set; macOS preflight failed"}
            home = Path(tart_home).expanduser()
            if not home.is_dir():
                return {"passed": False, "platform": platform, "checks": checks,
                        "detail": f"TART_HOME does not exist: {home}"}
            checks["tart_home"] = str(home)
            tart_env = os.environ.copy()
            tart_env["TART_HOME"] = str(home)
            ok, listed = _run_cmd(["tart", "list"], env=tart_env)
            if ok and base_vm in listed:
                checks["base_vm"] = base_vm
            elif (home / "vms" / base_vm).is_dir() or (home / base_vm).exists():
                checks["base_vm"] = str(home / "vms" / base_vm)
            else:
                return {"passed": False, "platform": platform, "checks": checks,
                        "detail": f"tart base VM not found: {base_vm!r}"}
        elif provider == "virtualbuddy":
            if not Path("/Applications/VirtualBuddy.app").exists():
                return {"passed": False, "platform": platform, "checks": {},
                        "detail": "VirtualBuddy.app not found; macOS preflight failed"}
            checks["virtualbuddy"] = "found"
        else:
            return {"passed": False, "platform": platform, "checks": {},
                    "detail": f"unknown macOS vm_provider: {provider!r}"}
        return {"passed": True, "platform": platform, "checks": checks,
                "detail": f"macos provider={provider} base_vm={base_vm}"}
    return {"passed": False, "platform": platform, "checks": {},
            "detail": f"unsupported platform: {platform}"}


def preflight_check(
    platform: str,
    *,
    ios_clone_source_udid: Optional[str] = None,
    ios_direct_udid: Optional[str] = None,
    macos_base_vm_name: Optional[str] = None,
    macos_vm_provider: Optional[str] = None,
    **kwargs: Any,
) -> Tuple[bool, str]:
    """Verify the platform environment with real probes (no runtime started).

    A bare ``which`` lookup never counts as a pass: iOS requires a listed
    simctl device/runtime plus Appium health, macOS/tart requires the base VM
    under a real TART_HOME. Returns (ok, detail).
    """
    evidence = preflight_evidence(
        platform,
        ios_clone_source_udid=ios_clone_source_udid,
        ios_direct_udid=ios_direct_udid,
        macos_base_vm_name=macos_base_vm_name,
        macos_vm_provider=macos_vm_provider,
        macos_storage_dir=kwargs.get("macos_storage_dir"),
        appium_host=str(kwargs.get("appium_host", "127.0.0.1")),
        appium_port=int(kwargs.get("appium_port", 4723)),
    )
    return bool(evidence["passed"]), str(evidence["detail"])


# --------------------------------------------------------------------------
# Results, verdicts, audit markers (task semantics untouched)
# --------------------------------------------------------------------------

def read_result_status(search_dir: str | Path) -> Optional[str]:
    """Read the episode ``result.json`` status scoped to one directory.

    Only the given directory is consulted (its own ``result.json`` first,
    then nested files *within* it). Callers must pass the current attempt
    directory so stale results from older attempts can never leak in.
    """
    base = Path(search_dir)
    candidates: List[Path] = []
    direct = base / "result.json"
    if direct.is_file():
        candidates.append(direct)
    try:
        nested = sorted(
            p for p in base.rglob("result.json") if p != direct and p.is_file()
        )
    except Exception:
        nested = []
    candidates.extend(nested)
    if not candidates:
        return None
    for result_path in candidates:
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        status = payload.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
        evaluation = payload.get("evaluation")
        if isinstance(evaluation, dict) and evaluation.get("environment_excluded") is True:
            return RETESTABLE_STATUS
    return None


def read_verdict(task_dir: str | Path) -> Optional[Dict[str, Any]]:
    """Read the cached verdict.json marker, if present."""
    verdict_path = Path(task_dir) / VERDICT_FILENAME
    if not verdict_path.is_file():
        return None
    try:
        payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def is_valid_result(task_dir: str | Path, expected: Optional[Dict[str, Any]] = None) -> bool:
    """A result is reusable only when explicitly marked valid for this evidence.

    Requires status PASS, ``valid: true``, and a fingerprint match against
    the current task hash, model/steps and evaluator/initializer code
    version. Without ``expected`` (or on any mismatch) the cache is
    explicitly refused.
    """
    if expected is None:
        return False
    verdict = read_verdict(task_dir)
    if verdict is None:
        return False
    if verdict.get("valid") is not True:
        return False
    if str(verdict.get("status", "")).strip() != VALID_REUSABLE_STATUS:
        return False
    return _evidence_matches(verdict, expected)


def is_confirmed_model_fail(
    task_dir: str | Path, expected: Optional[Dict[str, Any]] = None
) -> bool:
    """A confirmed model failure is final: never retested once valid.

    Requires status ``confirmed_model_fail``, ``valid: true``, an explicit
    audit marker (``audit_approved_by``), and -- when ``expected`` is given
    -- a fingerprint match. Without ``expected`` the claim is refused.
    """
    if expected is None:
        return False
    verdict = read_verdict(task_dir)
    if verdict is None:
        return False
    if str(verdict.get("status", "")).strip() != CONFIRMED_MODEL_FAIL:
        return False
    if verdict.get("valid") is not True:
        return False
    if not str(verdict.get("audit_approved_by", "")).strip():
        return False
    return _evidence_matches(verdict, expected)


def is_excluded_result(
    task_dir: str | Path, expected: Optional[Dict[str, Any]] = None
) -> bool:
    """``environment_excluded`` may be retested only with an explicit audit mark.

    Requires verdict status ``environment_excluded`` plus
    ``audit_excluded: true`` and ``audit_approved_by``. A bare
    ``result.json`` marker without that audit record never qualifies.
    """
    verdict = read_verdict(task_dir)
    if verdict is None:
        return False
    if str(verdict.get("status", "")).strip() != RETESTABLE_STATUS:
        return False
    if verdict.get("audit_excluded") is not True:
        return False
    if not str(verdict.get("audit_approved_by", "")).strip():
        return False
    if expected is not None and not _evidence_matches(verdict, expected):
        return False
    return True


def write_verdict(
    task_dir: str | Path,
    *,
    status: str,
    valid: bool,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    task_path = Path(task_dir)
    task_path.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "status": status,
        "valid": bool(valid),
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if extra:
        payload.update(extra)
    (task_path / VERDICT_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def audit_confirm_pass(
    task_dir: str | Path,
    expected: Dict[str, Any],
    approved_by: str,
) -> Dict[str, Any]:
    """Explicitly audit a PASS so future runs may reuse it (no auto-pass)."""
    if not str(approved_by).strip():
        raise QueueError("audit_confirm_pass requires an explicit approver")
    extra = dict(expected)
    extra.update(
        {
            "audit_approved_by": str(approved_by).strip(),
            "audit_decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return write_verdict(task_dir, status="PASS", valid=True, extra=extra)


def confirm_model_fail(
    task_dir: str | Path,
    expected: Dict[str, Any],
    approved_by: str,
) -> Dict[str, Any]:
    """Explicitly mark a confirmed model failure as final (never retested)."""
    if not str(approved_by).strip():
        raise QueueError("confirm_model_fail requires an explicit approver")
    extra = dict(expected)
    extra.update(
        {
            "audit_approved_by": str(approved_by).strip(),
            "audit_decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return write_verdict(
        task_dir, status=CONFIRMED_MODEL_FAIL, valid=True, extra=extra
    )


def audit_exclude_for_retest(
    task_dir: str | Path,
    expected: Dict[str, Any],
    approved_by: str,
) -> Dict[str, Any]:
    """Explicitly allow one ``environment_excluded`` outcome to be retested."""
    if not str(approved_by).strip():
        raise QueueError("audit_exclude_for_retest requires an explicit approver")
    extra = dict(expected)
    extra.update(
        {
            "audit_excluded": True,
            "audit_approved_by": str(approved_by).strip(),
            "audit_decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return write_verdict(
        task_dir, status=RETESTABLE_STATUS, valid=False, extra=extra
    )


def write_run_meta(
    task_dir: str | Path,
    *,
    platform: str,
    task_id: str,
    task_path: str,
    original_max_steps: int,
    effective_steps: int,
    run_record: Optional[Dict[str, Any]] = None,
    attempt_index: Optional[int] = None,
    attempt_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    task_file = _resolve_task_file(task_path)
    meta: Dict[str, Any] = {
        "platform": platform,
        "task_id": task_id,
        "task_path": str(task_file),
        "task_sha256": sha256_file(task_file),
        "task_implementation_sha256": task_implementation_hash(task_file),
        "model": MODEL_ID,
        "action_mode": ACTION_MODE,
        "observation_mode": OBSERVATION_MODE,
        "history_window": HISTORY_WINDOW,
        "original_max_steps": int(original_max_steps),
        "effective_max_steps": int(effective_steps),
        "step_cap": MAX_STEP_CAP,
        "script_version": SCRIPT_VERSION,
        "code_version": code_version_hash(platform),
        "git_revision": git_revision(),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": dict(run_record or {}),
    }
    if attempt_index is not None:
        meta["attempt_index"] = int(attempt_index)
    if attempt_dir is not None:
        meta["attempt_dir"] = str(attempt_dir)
    task_path_obj = Path(task_dir)
    task_path_obj.mkdir(parents=True, exist_ok=True)
    (task_path_obj / META_FILENAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def attempt_dir_for(task_dir: str | Path, attempt_index: int) -> Path:
    return Path(task_dir) / f"{ATTEMPT_PREFIX}{int(attempt_index):03d}"


def next_attempt_index(task_dir: str | Path, recorded_attempts: int) -> int:
    """Allocate above historical on-disk attempts, including manual runs."""
    highest = max(0, int(recorded_attempts))
    directory = Path(task_dir)
    if directory.exists():
        for path in directory.glob(f"{ATTEMPT_PREFIX}*"):
            match = re.fullmatch(re.escape(ATTEMPT_PREFIX) + r"(\d+)", path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def write_attempt_record(
    attempt_dir: str | Path,
    *,
    attempt_index: int,
    status: str,
    run_record: Dict[str, Any],
) -> Dict[str, Any]:
    path = Path(attempt_dir)
    path.mkdir(parents=True, exist_ok=True)
    record = {
        "attempt_index": int(attempt_index),
        "status": status,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": dict(run_record),
    }
    (path / "attempt_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


# --------------------------------------------------------------------------
# Queue state + atomic lock (covers run_queue, not just the CLI)
# --------------------------------------------------------------------------

def platform_results_root(platform: str, root: Optional[str | Path] = None) -> Path:
    base = Path(root) if root else RESULTS_ROOT
    return (base / platform).resolve()


def queue_file_for(platform: str, root: Optional[str | Path] = None) -> Path:
    return platform_results_root(platform, root) / QUEUE_FILENAME


def lock_file_for(platform: str, root: Optional[str | Path] = None) -> Path:
    return platform_results_root(platform, root) / LOCK_FILENAME


_HELD_LOCK_FDS: Dict[str, int] = {}


def _process_start_time(pid: int) -> Optional[str]:
    """Best-effort process start time used to defeat PID reuse confusion."""
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as fh:
            parts = fh.read().rsplit(")", 1)[1].split()
            return f"proc-start-{parts[19]}"
    except Exception:
        pass
    try:
        proc = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        out = proc.stdout.decode(errors="replace").strip()
        if out:
            return f"ps-{out}"
    except Exception:
        pass
    return None


def _lock_identity() -> str:
    return f"{os.getpid()} {_process_start_time(os.getpid()) or 'unknown-start'}"


def _read_lock_content(path: Path) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return text or None


def _split_lock_content(content: str) -> Tuple[int, Optional[str]]:
    """Split ``pid starttime`` without mangling space-bearing timestamps."""
    head, _, start = content.strip().partition(" ")
    return int(head.strip()), (start.strip() or None)


def _holder_alive(content: str) -> bool:
    try:
        holder, recorded_start = _split_lock_content(content)
    except ValueError:
        return True  # unparsable lock: treat as held, refuse
    if holder <= 0:
        return True
    try:
        os.kill(holder, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except Exception:
        return False
    if recorded_start and recorded_start != "unknown-start":
        if holder == os.getpid():
            # Same PID: only treat as live self-holder when start time matches.
            mine = _process_start_time(os.getpid())
            if mine is not None and recorded_start != mine:
                return False
            return True
        start = _process_start_time(holder)
        if start is not None and recorded_start != start:
            return False  # PID was reused by an unrelated process
    return True


def _flock_held_by_other(path: Path) -> Optional[bool]:
    """Probe whether another live process holds an flock on ``path``.

    Returns True (held elsewhere), False (no holder -- stale), or None
    (cannot probe; fall back to the PID heuristic).
    """
    try:
        fd = os.open(str(path), os.O_RDWR)
    except Exception:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        return False
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


def _lock_owned_by_self(path: Path) -> bool:
    if str(path) in _HELD_LOCK_FDS:
        return True
    content = _read_lock_content(path)
    if content is None:
        return False
    try:
        holder, recorded_start = _split_lock_content(content)
    except ValueError:
        return False
    if holder != os.getpid():
        return False
    if not recorded_start or recorded_start == "unknown-start":
        return True
    mine = _process_start_time(os.getpid())
    return mine is None or recorded_start == mine


def acquire_lock(lock_path: str | Path) -> int:
    """Atomically create the lock file; refuse when a live holder exists.

    Uses O_CREAT|O_EXCL so two racers cannot both believe they hold the
    lock (no read-then-write TOCTOU), then holds an flock(LOCK_EX|LOCK_NB)
    descriptor for the lock lifetime so a stale PID can never be mistaken
    for a live holder while the owner runs. Records ``pid starttime`` to
    defeat PID-reuse confusion.
    """
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path)
    if key in _HELD_LOCK_FDS:
        return os.getpid()
    identity = _lock_identity()
    for _ in range(50):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            content = _read_lock_content(path)
            if content is not None and _holder_alive(content):
                try:
                    holder_pid, _ = _split_lock_content(content)
                except ValueError:
                    holder_pid = -1
                if holder_pid == os.getpid():
                    # Same process re-entering without the held fd (e.g. a
                    # bare-PID file): never grant a second queue.
                    raise QueueError(
                        f"queue is already locked: {path} holder={content!r}"
                    )
                # A live PID is recorded. Break the tie with flock: a real
                # holder keeps LOCK_EX for its whole lifetime, so a free
                # flock means the PID was recycled and the lock is stale.
                # A held flock (or an unprobable file) means refuse.
                if _flock_held_by_other(path) is False:
                    pass  # stale despite the PID: reclaim below
                else:
                    raise QueueError(
                        f"queue is already locked: {path} holder={content!r}"
                    )
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                raise QueueError(f"queue is already locked: {path}")
            time.sleep(0.02)
            continue
        try:
            os.write(fd, identity.encode())
            os.fsync(fd)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            raise
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            raise QueueError(f"queue is already locked (flock held): {path}")
        _HELD_LOCK_FDS[key] = fd
        return os.getpid()
    raise QueueError(f"queue lock is contended, refusing: {path}")


def release_lock(lock_path: str | Path) -> None:
    path = Path(lock_path)
    key = str(path)
    fd = _HELD_LOCK_FDS.pop(key, None)
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass
        try:
            content = _read_lock_content(path)
            if content is not None and content.split()[:1] == [str(os.getpid())]:
                path.unlink()
        except Exception:
            pass
        return
    try:
        content = _read_lock_content(path)
        if content is not None and content.split()[:1] == [str(os.getpid())]:
            path.unlink()
    except Exception:
        pass


def build_plan_entries(
    platform: str,
    manifest_path: str | Path = MANIFEST_PATH,
) -> List[Dict[str, Any]]:
    """Build the 48-task plan from the real manifest (no runtime started)."""
    manifest_tasks = load_manifest_tasks(manifest_path, platform)
    entries: List[Dict[str, Any]] = []
    for item in manifest_tasks:
        original = read_original_max_steps(item["task_path"], platform)
        entries.append(
            {
                "task_id": item["task_id"],
                "task_path": item["task_path"],
                "model": MODEL_ID,
                "action_mode": ACTION_MODE,
                "observation_mode": OBSERVATION_MODE,
                "history_window": HISTORY_WINDOW,
                "original_max_steps": original,
                "effective_max_steps": effective_max_steps(original),
                "status": "pending",
                "attempts": 0,
            }
        )
    return entries


def load_queue(queue_path: str | Path) -> Optional[Dict[str, Any]]:
    path = Path(queue_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise QueueError(f"queue file is corrupt: {path} ({exc})")
    return payload if isinstance(payload, dict) else None


def save_queue(queue_path: str | Path, payload: Dict[str, Any]) -> None:
    """Atomically persist queue state (tmp file + fsync + os.replace)."""
    path = Path(queue_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
    except Exception:
        return
    try:
        os.fsync(dir_fd)
    except Exception:
        pass
    finally:
        try:
            os.close(dir_fd)
        except Exception:
            pass


def init_or_resume_queue(
    *,
    platform: str,
    results_root: Path,
    manifest_path: str | Path = MANIFEST_PATH,
) -> Tuple[Dict[str, Any], bool]:
    """Return (queue_payload, resumed). Old fingerprints are refreshed.

    Resumed entries never keep stale hashes or statuses: each stored entry
    is reconciled against the current manifest (task hash, model, step
    limits); any drift resets that entry to ``pending`` so old evidence
    cannot be reused silently.
    """
    queue_path = results_root / QUEUE_FILENAME
    current = build_plan_entries(platform, manifest_path)
    by_id = {e["task_id"]: e for e in current}
    current_code = code_version_hash(platform)
    current_manifest = manifest_hash(manifest_path)
    existing = load_queue(queue_path)
    if existing is not None:
        if existing.get("platform") != platform:
            raise QueueError(f"queue platform mismatch in {queue_path}")
        refreshed: List[Dict[str, Any]] = []
        for stored in existing.get("entries", []):
            task_id = stored.get("task_id")
            fresh = by_id.get(str(task_id))
            if fresh is None:
                continue  # task retired from the manifest: drop it
            merged = dict(stored)
            drift = (
                merged.get("task_path") != fresh["task_path"]
                or int(merged.get("original_max_steps", -1)) != fresh["original_max_steps"]
                or int(merged.get("effective_max_steps", -2)) != fresh["effective_max_steps"]
                or merged.get("model") != fresh["model"]
                or merged.get("action_mode") != fresh["action_mode"]
                or merged.get("observation_mode") != fresh["observation_mode"]
                or int(merged.get("history_window", -3)) != fresh["history_window"]
            )
            merged.update(
                {
                    "task_path": fresh["task_path"],
                    "model": fresh["model"],
                    "action_mode": fresh["action_mode"],
                    "observation_mode": fresh["observation_mode"],
                    "history_window": fresh["history_window"],
                    "original_max_steps": fresh["original_max_steps"],
                    "effective_max_steps": fresh["effective_max_steps"],
                }
            )
            if drift:
                merged["status"] = "pending"  # expire stale hash/status
            refreshed.append(merged)
        for fresh in current:
            if fresh["task_id"] not in {e.get("task_id") for e in refreshed}:
                refreshed.append(dict(fresh))
        existing["entries"] = refreshed
        existing["code_version"] = current_code
        existing["manifest_sha256"] = current_manifest
        existing.setdefault("completed_since_audit", 0)
        save_queue(queue_path, existing)
        return existing, True
    payload: Dict[str, Any] = {
        "version": QUEUE_VERSION,
        "platform": platform,
        "model": MODEL_ID,
        "action_mode": ACTION_MODE,
        "observation_mode": OBSERVATION_MODE,
        "step_cap": MAX_STEP_CAP,
        "code_version": current_code,
        "manifest_sha256": current_manifest,
        "completed_since_audit": 0,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": current,
    }
    save_queue(queue_path, payload)
    return payload, False


# --------------------------------------------------------------------------
# Default runner: reuse each platform's existing run_benchmark_command
# --------------------------------------------------------------------------

def _load_committed_runtime_defaults(platform: str) -> Dict[str, Any]:
    """Read committed configs for display/defaults only; never writes them."""
    if platform == "ios":
        from platforms.ios.runtime_config import load_ios_runtime_config

        try:
            config = load_ios_runtime_config()
        except Exception as exc:
            raise QueueError(f"cannot load committed iOS runtime config: {exc}")
        return {
            "appium_host": config.appium_host,
            "appium_port": config.appium_port,
            "clone_source_udid": config.source_simulator_udid,
        }
    from platforms.macos.runtime_config import (
        MACOS_RUNTIME_CONFIG_PATH,
        load_macos_runtime_config,
    )

    try:
        config = load_macos_runtime_config(MACOS_RUNTIME_CONFIG_PATH)
    except Exception as exc:
        raise QueueError(f"cannot load committed macOS runtime config: {exc}")
    return {
        "vm_ip": config.vm_ip,
        "runtime_port": config.runtime_port,
        "vm_token": config.vm_token,
        "base_vm_name": config.base_vm_name,
        "vm_provider": config.vm_provider,
        "tart_home": config.tart_home,
    }


def _resolve_tart_vm_ip(vm_name: str, tart_home: Optional[str] = None) -> str:
    """Resolve the active Tart guest address for single-VM runs."""
    env = os.environ.copy()
    if tart_home:
        env["TART_HOME"] = str(tart_home)
    try:
        result = subprocess.run(
            ["tart", "ip", vm_name], env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=30, check=False,
        )
    except Exception as exc:
        raise QueueError(f"cannot resolve IP for Tart VM {vm_name}: {exc}") from exc
    address = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
    if result.returncode != 0 or not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", address):
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise QueueError(f"cannot resolve IP for Tart VM {vm_name}: {detail}")
    return address


def default_runner(
    entry: Dict[str, Any],
    task_dir: Path,
    *,
    platform: str,
    ios_clone_source_udid: Optional[str] = None,
    ios_direct_udid: Optional[str] = None,
    macos_base_vm_name: Optional[str] = None,
    macos_storage_dir: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Run one task via the platform's run_benchmark_command.

    ``task_dir`` must be the current unique attempt directory; the status is
    read back from that directory only. A missing ``result.json`` is always
    ERROR -- an exit code of 0 never counts as PASS by itself.

    Returns (status, run_record). ``status`` is one of
    PASS / FAIL / ERROR / environment_excluded.
    """
    task_dir = Path(task_dir)
    # Author-eval results are only auditable when the actual wire request and
    # the post-run native app state are captured before the ephemeral runtime
    # is deleted. The platform runners already implement these opt-in hooks;
    # make them mandatory for this queue so callers cannot accidentally omit
    # either piece of evidence.
    os.environ["OS_OMNI_DEEPSEEK_REQUEST_AUDIT"] = "1"
    os.environ[
        "OS_OMNI_CAPTURE_IOS_FINAL_STATE"
        if platform == "ios"
        else "OS_OMNI_CAPTURE_MACOS_FINAL_STATE"
    ] = "1"
    if platform == "ios":
        # WDA's simulator build products are device-independent and this
        # queue permits only one iOS session at a time. Keep its build cache
        # outside the source tree so fresh clones use an incremental build.
        wda_cache = REPO_ROOT.parent / "ios" / "wda-derived-data"
        wda_cache.mkdir(parents=True, exist_ok=True)
        os.environ["OS_OMNI_WDA_DERIVED_DATA"] = str(wda_cache)
    task_file = str((REPO_ROOT / entry["task_path"]).resolve())
    benchmark_name = safe_task_dir(entry["task_id"])
    if platform == "ios":
        from platforms.ios.runners.benchmark import run_benchmark_command

        defaults = _load_committed_runtime_defaults("ios")
        args = Namespace(
            task_file=task_file,
            execution_file=None,
            models=MODEL_ID,
            benchmark_name=benchmark_name,
            output_root=str(task_dir),
            action_mode=ACTION_MODE,
            observation_mode=OBSERVATION_MODE,
            history_window=HISTORY_WINDOW,
            max_steps=int(entry["effective_max_steps"]),
            timeout=None,
            clone_source_udid=(None if ios_direct_udid else (ios_clone_source_udid or defaults["clone_source_udid"])),
            direct_udid=ios_direct_udid,
            appium_host=defaults["appium_host"],
            appium_port=defaults["appium_port"],
        )
        exit_code = run_benchmark_command(args)
    else:
        from platforms.macos.host.runners.benchmark import run_benchmark_command

        defaults = _load_committed_runtime_defaults("macos")
        if os.environ.get("MACOS_SKIP_VM_CLONE", "").strip().lower() in {
            "1", "true", "yes", "on"
        }:
            defaults["vm_ip"] = _resolve_tart_vm_ip(
                macos_base_vm_name or defaults["base_vm_name"],
                macos_storage_dir or defaults.get("tart_home"),
            )
        args = Namespace(
            task_file=task_file,
            execution_file=None,
            models=MODEL_ID,
            benchmark_name=benchmark_name,
            output_root=str(task_dir),
            action_mode=ACTION_MODE,
            observation_mode=OBSERVATION_MODE,
            history_window=HISTORY_WINDOW,
            prompt_profile="benchmark",
            max_steps=int(entry["effective_max_steps"]),
            timeout=None,
            vm_ip=defaults["vm_ip"],
            runtime_port=defaults["runtime_port"],
            vm_token=defaults["vm_token"],
            base_vm_name=(macos_base_vm_name or defaults["base_vm_name"]),
            vm_provider=defaults["vm_provider"],
            tart_home=(macos_storage_dir or defaults["tart_home"]),
        )
        exit_code = run_benchmark_command(args)
    status = read_result_status(task_dir)
    if status is None:
        status = "ERROR"
    run_record = {"exit_code": exit_code, "output_dir": str(task_dir)}
    return status, run_record


RunnerFn = Callable[..., Tuple[str, Dict[str, Any]]]
PreflightFn = Callable[..., Tuple[bool, str]]


def run_queue(
    *,
    platform: str,
    results_root: Path,
    gate_path: str | Path,
    resume_after_audit: bool = False,
    audit_approval_file: Optional[str | Path] = None,
    limit: Optional[int] = None,
    ios_clone_source_udid: Optional[str] = None,
    ios_direct_udid: Optional[str] = None,
    macos_base_vm_name: Optional[str] = None,
    macos_storage_dir: Optional[str] = None,
    macos_vm_provider: Optional[str] = None,
    appium_host: str = "127.0.0.1",
    appium_port: int = 4723,
    manifest_path: str | Path = MANIFEST_PATH,
    runner: Optional[RunnerFn] = None,
    preflight_fn: Optional[PreflightFn] = None,
    task_ids: Optional[List[str]] = None,
    batch_until_environment_error: bool = False,
) -> Dict[str, Any]:
    """Execute the serial queue. Returns a summary dict.

    Reuse rule: an ``entry["status"]`` value alone (``passed`` /
    ``skipped_valid``) never skips a task. Only an explicitly valid verdict
    whose fingerprint matches the current task hash, per-task
    implementation hash, model/steps and code version is reused, and only
    a valid ``confirmed_model_fail`` verdict with an explicit audit marker
    is skipped as final.

    ``task_ids`` selects a subset of the full inventory for execution;
    the queue still records all manifest tasks. ``None`` runs everything.

    By default FAIL/ERROR and every 3rd completion pause for audit. Batch mode
    continues past completed PASS/FAIL records (which remain audit-pending),
    but still pauses on environment exclusions and execution errors.
    """
    gate = read_gate(gate_path, platform, manifest_path)
    check = (preflight_fn or preflight_check)(
        platform,
        ios_clone_source_udid=ios_clone_source_udid,
        ios_direct_udid=ios_direct_udid,
        macos_base_vm_name=macos_base_vm_name,
        macos_vm_provider=macos_vm_provider,
        macos_storage_dir=macos_storage_dir,
        appium_host=appium_host,
        appium_port=appium_port,
    )
    ok, detail = check[0], check[1]
    if not ok:
        raise QueueError(f"platform preflight failed for {platform}: {detail}")

    results_root = Path(results_root)
    lock_path = results_root / LOCK_FILENAME
    own_lock = _lock_owned_by_self(lock_path) or str(lock_path) in _HELD_LOCK_FDS
    if not own_lock:
        acquire_lock(lock_path)
        own_lock = True
        release_on_exit = True
    else:
        release_on_exit = False
    try:
        return _run_queue_locked(
            platform=platform,
            results_root=results_root,
            gate=gate,
            resume_after_audit=resume_after_audit,
            audit_approval_file=audit_approval_file,
            limit=limit,
            ios_clone_source_udid=ios_clone_source_udid,
            ios_direct_udid=ios_direct_udid,
            macos_base_vm_name=macos_base_vm_name,
            macos_storage_dir=macos_storage_dir,
            manifest_path=manifest_path,
            runner=runner,
            task_ids=task_ids,
            batch_until_environment_error=batch_until_environment_error,
        )
    finally:
        if release_on_exit:
            release_lock(lock_path)


def _run_queue_locked(
    *,
    platform: str,
    results_root: Path,
    gate: Dict[str, Any],
    resume_after_audit: bool,
    audit_approval_file: Optional[str | Path],
    limit: Optional[int],
    ios_clone_source_udid: Optional[str],
    ios_direct_udid: Optional[str],
    macos_base_vm_name: Optional[str],
    macos_storage_dir: Optional[str],
    manifest_path: str | Path,
    runner: Optional[RunnerFn],
    task_ids: Optional[List[str]] = None,
    batch_until_environment_error: bool = False,
) -> Dict[str, Any]:
    queue, resumed = init_or_resume_queue(
        platform=platform, results_root=results_root, manifest_path=manifest_path
    )
    queue_path = results_root / QUEUE_FILENAME
    inventory_ids = [str(e.get("task_id")) for e in queue.get("entries", [])]
    if task_ids is not None:
        selected = [str(t) for t in task_ids]
        unknown = [t for t in selected if t not in set(inventory_ids)]
        if unknown:
            raise QueueError(
                f"unknown task_id(s) for platform {platform}: {unknown}"
            )
        if len(set(selected)) != len(selected):
            raise QueueError("duplicate --task-id values are not allowed")
    else:
        selected = list(inventory_ids)
    selected_set = set(selected)
    check_initial_fail_evidence(
        gate,
        selected,
        task_paths={
            str(e.get("task_id")): str(e.get("task_path"))
            for e in queue.get("entries", [])
            if str(e.get("task_id")) in selected_set
        },
    )
    paused_reason = queue.get("paused_reason")
    if paused_reason and not resume_after_audit:
        return {
            "platform": platform,
            "resumed": resumed,
            "selected_task_ids": list(selected),
            "paused": True,
            "paused_reason": paused_reason,
            "note": "queue is paused for main-agent audit; resume explicitly with "
            "--resume-after-audit plus --audit-approval-file",
        }
    if paused_reason and resume_after_audit:
        if not audit_approval_file:
            raise QueueError("resuming requires --audit-approval-file")
        approval = read_approval(audit_approval_file)
        queue.setdefault("audit_trail", []).append(
            {
                "resumed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "paused_reason": paused_reason,
                "approved_by": approval.get("by"),
            }
        )
        queue["paused_reason"] = None
        save_queue(queue_path, queue)

    active_runner: RunnerFn = runner or default_runner
    summary: Dict[str, Any] = {
        "platform": platform,
        "resumed": resumed,
        "gate_approved_by": gate.get("approved_by"),
        "preflight_report": gate.get("_preflight_report_path"),
        "processed": 0,
        "passed": 0,
        "reused": 0,
        "skipped_confirmed": 0,
        "retested_excluded": 0,
        "awaiting_audit": 0,
        "completed_since_audit": int(queue.get("completed_since_audit", 0)),
        "paused": False,
        "paused_reason": None,
        "selected_task_ids": list(selected),
    }
    processed_this_run = 0

    for entry in queue.get("entries", []):
        if str(entry.get("task_id")) not in selected_set:
            continue
        if limit is not None and processed_this_run >= limit:
            break
        expected = expected_evidence(entry, platform)
        task_dir = results_root / safe_task_dir(entry["task_id"])
        # Only explicitly valid, version-matching evidence is reusable.
        # entry["status"] alone never skips a task.
        if is_valid_result(task_dir, expected):
            entry["status"] = "skipped_valid"
            summary["reused"] += 1
            save_queue(queue_path, queue)
            continue
        if is_confirmed_model_fail(task_dir, expected):
            entry["status"] = "skipped_confirmed"
            summary["skipped_confirmed"] += 1
            save_queue(queue_path, queue)
            continue
        verdict = read_verdict(task_dir)
        if batch_until_environment_error and verdict is not None and str(verdict.get("status", "")) in (
            "PASS", "FAIL"
        ) and verdict.get("audit_pending") is True:
            entry["status"] = "pending_audit" if verdict["status"] == "PASS" else "failed_pending_audit"
            summary["awaiting_audit"] += 1
            save_queue(queue_path, queue)
            continue
        if (
            verdict is not None
            and str(verdict.get("status", "")).strip() == RETESTABLE_STATUS
            and not is_excluded_result(task_dir, expected)
        ):
            queue["paused_reason"] = (
                f"task {entry['task_id']} environment_excluded without explicit "
                "audit exclusion; paused for main-agent audit"
            )
            save_queue(queue_path, queue)
            summary["paused"] = True
            summary["paused_reason"] = queue["paused_reason"]
            break
        excluded_before = is_excluded_result(task_dir, expected)
        entry["status"] = "running"
        entry["attempts"] = next_attempt_index(task_dir, int(entry.get("attempts", 0)))
        attempt_index = int(entry["attempts"])
        attempt_dir = attempt_dir_for(task_dir, attempt_index)
        attempt_dir.mkdir(parents=True, exist_ok=False)
        save_queue(queue_path, queue)
        status, run_record = active_runner(
            entry,
            attempt_dir,
            platform=platform,
            ios_clone_source_udid=ios_clone_source_udid,
            ios_direct_udid=ios_direct_udid,
            macos_base_vm_name=macos_base_vm_name,
            macos_storage_dir=macos_storage_dir,
        )
        if status not in ("PASS", "FAIL", "ERROR", RETESTABLE_STATUS):
            status = "ERROR"
        run_record = dict(run_record)
        run_record.setdefault("attempt_index", attempt_index)
        run_record.setdefault("attempt_dir", str(attempt_dir))
        write_attempt_record(
            attempt_dir,
            attempt_index=attempt_index,
            status=status,
            run_record=run_record,
        )
        write_run_meta(
            task_dir,
            platform=platform,
            task_id=entry["task_id"],
            task_path=entry["task_path"],
            original_max_steps=entry["original_max_steps"],
            effective_steps=entry["effective_max_steps"],
            run_record=run_record,
            attempt_index=attempt_index,
            attempt_dir=attempt_dir,
        )
        processed_this_run += 1
        summary["processed"] += 1
        if excluded_before:
            summary["retested_excluded"] += 1
        if status == RETESTABLE_STATUS:
            # Fresh exclusions wait for an explicit audit mark; they are not
            # auto-retestable.
            write_verdict(
                task_dir,
                status=status,
                valid=False,
                extra={"run": run_record, "attempt_dir": str(attempt_dir),
                       "audit_pending": True, **expected},
            )
            entry["status"] = "pending"
            queue["paused_reason"] = (
                f"task {entry['task_id']} environment exclusion; paused for audit"
            )
            save_queue(queue_path, queue)
            summary["paused"] = True
            summary["paused_reason"] = queue["paused_reason"]
            break
        if status == "PASS":
            # Unaudited PASS is never reusable: valid stays False until an
            # explicit audit confirms it.
            write_verdict(
                task_dir,
                status=status,
                valid=False,
                extra={"run": run_record, "attempt_dir": str(attempt_dir),
                       "audit_pending": True, **expected},
            )
            entry["status"] = "pending_audit"
            summary["passed"] += 1
            queue["completed_since_audit"] = int(queue.get("completed_since_audit", 0)) + 1
            summary["completed_since_audit"] = queue["completed_since_audit"]
            save_queue(queue_path, queue)
            if (not batch_until_environment_error and
                    queue["completed_since_audit"] % AUDIT_PAUSE_EVERY_N_COMPLETIONS == 0):
                queue["paused_reason"] = (
                    f"{queue['completed_since_audit']} new completions; "
                    "paused for main-agent link audit"
                )
                save_queue(queue_path, queue)
                summary["paused"] = True
                summary["paused_reason"] = queue["paused_reason"]
                break
            continue
        if status == "FAIL":
            write_verdict(
                task_dir,
                status=status,
                valid=False,
                extra={"run": run_record, "attempt_dir": str(attempt_dir),
                       "audit_pending": True, **expected},
            )
            entry["status"] = "failed_pending_audit"
            summary["awaiting_audit"] += 1
            if batch_until_environment_error:
                save_queue(queue_path, queue)
                continue
            queue["paused_reason"] = (
                f"task {entry['task_id']} FAIL; whole queue paused for main-agent audit"
            )
            save_queue(queue_path, queue)
            summary["paused"] = True
            summary["paused_reason"] = queue["paused_reason"]
            break
        write_verdict(
            task_dir,
            status="ERROR",
            valid=False,
            extra={"run": run_record, "attempt_dir": str(attempt_dir),
                   "audit_pending": True, **expected},
        )
        entry["status"] = "error_pending_audit"
        queue["paused_reason"] = (
            f"task {entry['task_id']} ERROR; whole queue paused for main-agent audit"
        )
        save_queue(queue_path, queue)
        summary["paused"] = True
        summary["paused_reason"] = queue["paused_reason"]
        break

    save_queue(queue_path, queue)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="macOS/iOS formal-eval resumable serial queue (model deepseek_flash)."
    )
    parser.add_argument("--platform", choices=SUPPORTED_PLATFORMS, required=True)
    parser.add_argument("--plan", action="store_true",
                        help="only print the task plan; do not start any runtime")
    parser.add_argument("--run", action="store_true",
                        help="execute the serial queue (requires --gate-file)")
    parser.add_argument("--gate-file", type=str, default=None)
    parser.add_argument("--results-root", type=str, default=None,
                        help="override results root (default results/author_eval)")
    parser.add_argument("--manifest", type=str, default=str(MANIFEST_PATH))
    parser.add_argument("--task-id", dest="task_ids", action="append", default=None,
                        help="run only the given task_id; repeatable; "
                             "full inventory stays in the queue")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ios-clone-source-udid", type=str, default=None,
                        help="iOS baseline UDID override; committed config is not modified")
    parser.add_argument("--ios-direct-udid", type=str, default=None,
                        help="run serially on an already-booted iOS simulator without cloning")
    parser.add_argument("--macos-base-vm-name", type=str, default=None,
                        help="macOS baseline VM name override; committed config is not modified")
    parser.add_argument("--macos-storage-dir", type=str, default=None,
                        help="macOS tart storage dir override (maps to tart_home)")
    parser.add_argument("--resume-after-audit", action="store_true",
                        help="explicitly resume a paused queue after main-agent audit")
    parser.add_argument("--audit-approval-file", type=str, default=None,
                        help="explicit audit-approval JSON required to resume")
    parser.add_argument("--batch-until-environment-error", action="store_true",
                        help="continue serially past PASS/FAIL outcomes; pause only for environment exclusions/errors")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    results_root = platform_results_root(args.platform, args.results_root)
    if results_root.as_posix().endswith("local_eval") or "local_eval" in results_root.parts:
        print("refusing: results must not live under Android local_eval", file=sys.stderr)
        return 2
    if args.plan:
        entries = build_plan_entries(args.platform, args.manifest)
        if args.task_ids:
            wanted = set(args.task_ids)
            entries = [e for e in entries if e["task_id"] in wanted]
        print(f"platform={args.platform} model={MODEL_ID} "
              f"action_mode={ACTION_MODE} observation_mode={OBSERVATION_MODE} "
              f"tasks={len(entries)}")
        for entry in entries:
            print(f"{entry['task_id']} original={entry['original_max_steps']} "
                  f"effective={entry['effective_max_steps']} {entry['task_path']}")
        return 0
    if not args.run:
        print("specify --plan or --run", file=sys.stderr)
        return 2
    if not args.gate_file:
        print("formal run requires --gate-file", file=sys.stderr)
        return 2
    # The gate file is external and explicit: it is read, never created here,
    # and no code path below auto-approves an audit or starts a formal run
    # without it.
    lock_path = lock_file_for(args.platform, args.results_root)
    try:
        acquire_lock(lock_path)
    except QueueError as exc:
        print(f"lock refused: {exc}", file=sys.stderr)
        return 3
    try:
        summary = run_queue(
            platform=args.platform,
            results_root=results_root,
            gate_path=args.gate_file,
            resume_after_audit=args.resume_after_audit,
            audit_approval_file=args.audit_approval_file,
            limit=args.limit,
            ios_clone_source_udid=args.ios_clone_source_udid,
            ios_direct_udid=args.ios_direct_udid,
            macos_base_vm_name=args.macos_base_vm_name,
            macos_storage_dir=args.macos_storage_dir,
            manifest_path=args.manifest,
            task_ids=args.task_ids,
            batch_until_environment_error=args.batch_until_environment_error,
        )
    except (GateError, QueueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 4
    finally:
        release_lock(lock_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary.get("paused") else 10


def read_approval(approval_path: str | Path) -> Dict[str, Any]:
    """Validate the explicit audit-approval file needed to resume."""
    path = Path(approval_path)
    if not path.exists():
        raise QueueError(f"audit approval file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise QueueError(f"audit approval file is not valid JSON: {path} ({exc})")
    if not isinstance(payload, dict) or payload.get("approved") is not True:
        raise QueueError(f"audit approval file does not approve: {path}")
    if not str(payload.get("by", "")).strip():
        raise QueueError(f"audit approval file is missing approver: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
