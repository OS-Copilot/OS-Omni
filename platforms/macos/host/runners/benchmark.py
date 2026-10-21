#!/usr/bin/env python3
"""
Benchmark runner for serial clone -> run -> delete macOS experiments.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from platforms.macos.host.runners.base_benchmark import BaseBenchmarkRunner

from platforms.macos.host.core.types import load_task_from_file
from platforms.macos.host.runtime_env.vm_manager import MacOSVMManager, create_macos_vm_manager

MACOS_PLATFORM_DIR = Path(__file__).resolve().parents[2]
V2_BASE_DIR = Path(__file__).resolve().parents[4]
MACOS_BENCHMARK_OUTPUT_ROOT = str(V2_BASE_DIR / "results" / "macos")
INTERNAL_BENCHMARK_TASK_COMMAND = "__benchmark_task"
MACOS_OUTPUT_DIR_ENV = "MACOS_OUTPUT_DIR"
MACOS_SKIP_VM_CLONE_ENV = "MACOS_SKIP_VM_CLONE"
MACOS_SKIP_GUEST_RUNTIME_SYNC_ENV = "MACOS_SKIP_GUEST_RUNTIME_SYNC"
MACOS_ENABLE_GUEST_RUNTIME_SYNC_ENV = "MACOS_ENABLE_GUEST_RUNTIME_SYNC"
MACOS_GUEST_SSH_IDENTITY_FILE_ENV = "HELLOWORLD_MACOS_GUEST_SSH_IDENTITY_FILE"
MACOS_DEFAULT_GUEST_SSH_IDENTITY_BASENAME = "helloworld_macos_bench"
CLONE_POST_BOOT_SETTLE_SECONDS = 1.0
GUEST_RUNTIME_INSTALL_PATH = "/Applications/MacUIBenchRuntime/runtime/runtime_server.py"
GUEST_REQUIREMENTS_INSTALL_PATH = "/Applications/MacUIBenchRuntime/runtime/requirements.txt"
GUEST_RUNTIME_VENV_PYTHON = "/Applications/MacUIBenchRuntime/runtime/.venv/bin/python"
GUEST_RUNTIME_VENV_PIP = "/Applications/MacUIBenchRuntime/runtime/.venv/bin/pip"
GUEST_RUNTIME_LABEL = "com.yourlab.macui.runtime"
GUEST_RUNTIME_SYNC_RETRIES = 20
GUEST_RUNTIME_SYNC_INTERVAL_SECONDS = 2.0

OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV = "OS_OMNI_CAPTURE_MACOS_FINAL_STATE"
MACOS_FINAL_STATE_DIRNAME = "final_state"
MACOS_FINAL_STATE_ARCHIVE_NAME = "final_state.tar.gz"
MACOS_FINAL_STATE_MANIFEST_NAME = "manifest.json"
MACOS_FINAL_STATE_SCREENSHOT_NAME = "final_screenshot.jpg"
MACOS_FINAL_STATE_MAX_FILE_BYTES = 32 * 1024 * 1024
MACOS_FINAL_STATE_MAX_TOTAL_BYTES = 128 * 1024 * 1024
MACOS_FINAL_STATE_MAX_FILES = 32
MACOS_FINAL_STATE_GUEST_TIMEOUT = 30

# File-name hints for secrets/credentials. Matching guest files are never
# fetched into the final-state archive; the exclusion is recorded instead.
_MACOS_FINAL_STATE_CREDENTIAL_HINTS = (
    "keychain",
    "credential",
    "password",
    "secret",
    "token",
    "auth",
    "id_rsa",
    "id_ed25519",
    ".pem",
    ".p12",
)
_MACOS_FINAL_STATE_EXACT_SECRET_BASENAMES = frozenset({".env"})

# Guest path components that are never collected (caches/cookies/keychains).
_MACOS_FINAL_STATE_EXCLUDED_COMPONENTS = frozenset(
    {"caches", "cache", "__pycache__", "cookies", "keychains"}
)

# Absolute guest roots under which task-bound evidence files may live.
# Anything outside these roots (notably ~Library keychains, ~/.ssh, /etc,
# and the VM home directory at large) is rejected without a guest call.
_MACOS_FINAL_STATE_ALLOWED_FILE_ROOTS = (
    "/Users/bench/Downloads",
    "/Users/bench/Documents",
    "/Users/bench/Desktop",
    "/tmp",
    "/private/tmp",
)

# Library roots readable only for explicitly task-bound native stores
# (Photos/Thunderbird/Contacts/Calendars/Reminders DBs resolved below).
_MACOS_FINAL_STATE_ALLOWED_LIBRARY_ROOTS = (
    "/Users/bench/Library/Thunderbird",
    "/Users/bench/Library/Calendars",
    "/Users/bench/Library/Reminders",
    "/Users/bench/Library/Application Support/AddressBook",
    "/Users/bench/Pictures",
)

_MACOS_FINAL_STATE_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

# Fixed guest-side stat probe. The guest path travels as subprocess argv
# (never interpolated into shell or into this code string).
_MACOS_FINAL_STATE_STAT_CODE = (
    "import json, os, stat, sys\n"
    "path = sys.argv[1] if len(sys.argv) > 1 else ''\n"
    "try:\n"
    "    info = os.lstat(path)\n"
    "    result = {\n"
    "        'exists': True,\n"
    "        'is_file': stat.S_ISREG(info.st_mode),\n"
    "        'is_symlink': stat.S_ISLNK(info.st_mode),\n"
    "        'size': int(info.st_size),\n"
    "    }\n"
    "except FileNotFoundError:\n"
    "    result = {'exists': False}\n"
    "except Exception as error:\n"
    "    result = {'exists': False, 'error': str(error)}\n"
    "print(json.dumps(result))\n"
)

# Fully static Thunderbird calendar-DB discovery probe: no caller input is
# interpolated. Bounded to direct profile children and a small result cap.
_MACOS_FINAL_STATE_THUNDERBIRD_DISCOVERY_CODE = (
    "import json;"
    "from pathlib import Path;"
    "root=Path('/Users/bench/Library/Thunderbird/Profiles');"
    "found=[];"
    "try:\n"
    "    entries=sorted(root.iterdir()) if root.is_dir() else [];"
    "except Exception:\n"
    "    entries=[];"
    "for _profile in entries:\n"
    "    try:\n"
    "        if not _profile.is_dir() or _profile.is_symlink():\n"
    "            continue;"
    "        _cand=_profile/'calendar-data'/'local.sqlite';"
    "        if _cand.is_file() and not _cand.is_symlink():\n"
    "            found.append(str(_cand));"
    "    except Exception:\n"
    "        continue;"
    "    if len(found)>=4:\n"
    "        break;"
    "print(json.dumps({'dbs':found}))"
)

logger = logging.getLogger(__name__)


def macos_final_state_capture_enabled() -> bool:
    """Return True only when the opt-in final-state capture env flag is set."""
    return (
        os.environ.get(OS_OMNI_CAPTURE_MACOS_FINAL_STATE_ENV, "").strip().lower()
        in {"1", "true", "yes"}
    )


def _macos_final_state_normalize_guest_path(raw: Any) -> Optional[str]:
    """Normalize a candidate guest path or return None when unusable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or "\x00" in text:
        return None
    if text.startswith("~"):
        # Only the bench user's home is addressable; anything else is unsafe.
        if text != "~" and not text.startswith("~/"):
            return None
        text = "/Users/bench" + text[1:]
    if not text.startswith("/"):
        return None
    normalized = os.path.normpath(text)
    if not normalized.startswith("/") or normalized == "/":
        return None
    return normalized


def _is_allowed_macos_evidence_path(
    normalized: str, *, library_scope: bool = False
) -> bool:
    roots = _MACOS_FINAL_STATE_ALLOWED_FILE_ROOTS
    if library_scope:
        roots = roots + _MACOS_FINAL_STATE_ALLOWED_LIBRARY_ROOTS
    for root in roots:
        if normalized == root or normalized.startswith(root + "/"):
            return True
    return False


def _macos_evidence_exclusion_reason(normalized: str) -> Optional[str]:
    lowered = normalized.lower()
    basename = os.path.basename(lowered)
    if basename in _MACOS_FINAL_STATE_EXACT_SECRET_BASENAMES:
        return "credential-name-excluded"
    if any(hint in basename for hint in _MACOS_FINAL_STATE_CREDENTIAL_HINTS):
        return "credential-name-excluded"
    components = [part.lower() for part in normalized.split("/") if part]
    if any(part in _MACOS_FINAL_STATE_EXCLUDED_COMPONENTS for part in components):
        return "cache-or-system-excluded"
    return None


def _collect_candidate_path_strings(node: Any, *, depth: int = 0) -> List[str]:
    """Collect absolute-looking guest path strings from task param mappings."""
    found: List[str] = []
    if depth > 6 or node is None:
        return found
    if isinstance(node, str):
        text = node.strip()
        if text.startswith(("/", "~")) and len(text) < 1024:
            found.append(text)
        return found
    if isinstance(node, dict):
        for key, value in node.items():
            key_lower = str(key or "").lower()
            if key_lower.endswith(("_path", "_file", "_dir", "_folder")) or key_lower in {
                "path",
                "open_file",
                "db_path",
            }:
                found.extend(_collect_candidate_path_strings(value, depth=depth + 1))
            elif isinstance(value, (dict, list)):
                found.extend(_collect_candidate_path_strings(value, depth=depth + 1))
        return found
    if isinstance(node, (list, tuple)):
        for item in node:
            found.extend(_collect_candidate_path_strings(item, depth=depth + 1))
        return found
    return found


def resolve_macos_task_evidence_paths(
    task_file: Any,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Resolve task-bound guest file paths without importing task semantics.

    Reads only the task YAML's ``evaluation.params``/``init.params`` string
    values that look like absolute guest paths. Returns
    ``(allowed_paths, skipped)`` where skipped entries carry explicit
    reasons. Never raises.
    """
    allowed: List[str] = []
    skipped: List[Dict[str, Any]] = []
    try:
        payload = yaml.safe_load(Path(task_file).read_text(encoding="utf-8")) or {}
    except Exception as exc:
        skipped.append({"path": str(task_file), "reason": f"task-file-unreadable: {exc}"})
        return allowed, skipped
    if not isinstance(payload, dict):
        return allowed, skipped
    candidates: List[str] = []
    for section in ("evaluation", "init"):
        section_node = payload.get(section)
        params = section_node.get("params") if isinstance(section_node, dict) else None
        if isinstance(params, dict):
            candidates.extend(_collect_candidate_path_strings(params))
    seen: set[str] = set()
    for raw in candidates:
        normalized = _macos_final_state_normalize_guest_path(raw)
        if normalized is None:
            skipped.append({"path": str(raw)[:256], "reason": "unsafe-or-relative-path"})
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        exclusion = _macos_evidence_exclusion_reason(normalized)
        if exclusion is not None:
            skipped.append({"path": normalized, "reason": exclusion})
            continue
        if not _is_allowed_macos_evidence_path(normalized):
            skipped.append({"path": normalized, "reason": "path-not-allowed"})
            continue
        allowed.append(normalized)
    return allowed, skipped


def _native_macos_state_candidates(
    *, task_id: str, task_file: Any
) -> Tuple[Dict[str, List[str]], List[Dict[str, Any]]]:
    """Map capture label to task-bound native store paths. Never raises.

    Contacts/Calendar/Reminders/Photos DBs (or task export paths) are
    returned ONLY when the task id, evaluator id, or explicit ``db_path``
    param binds them to this task.
    """
    wanted: Dict[str, List[str]] = {}
    skipped: List[Dict[str, Any]] = []
    tid = str(task_id or "").lower()
    evaluator_id = ""
    explicit_db: Optional[str] = None
    try:
        payload = yaml.safe_load(Path(task_file).read_text(encoding="utf-8")) or {}
        if isinstance(payload, dict):
            evaluation = payload.get("evaluation")
            if isinstance(evaluation, dict):
                evaluator_id = str(evaluation.get("evaluator_id") or "").lower()
                params = evaluation.get("params")
                if isinstance(params, dict) and isinstance(params.get("db_path"), str):
                    explicit_db = params["db_path"]
    except Exception as exc:
        skipped.append({"path": "native-discovery", "reason": f"task-file-unreadable: {exc}"})
    blob = f"{tid} {evaluator_id}"
    if "photo" in blob:
        wanted["photos"] = [
            "/Users/bench/Pictures/Photos Library.photoslibrary/database/Photos.sqlite"
        ]
    if "thunderbird" in blob and "calendar" in blob:
        wanted["thunderbird_calendar"] = ["__thunderbird_discovery__"]
    if "contact" in blob:
        wanted["contacts"] = [
            "/Users/bench/Library/Application Support/AddressBook/AddressBook-v22.abcddb"
        ]
    if "reminder" in blob or ("calendar" in blob and "thunderbird" not in blob):
        wanted["reminders"] = [
            "/Users/bench/Library/Reminders/Container_v1/Stores/Data.store.sqlitedb"
        ]
    if explicit_db:
        normalized = _macos_final_state_normalize_guest_path(explicit_db)
        if normalized is None:
            skipped.append({"path": str(explicit_db)[:256], "reason": "unsafe-or-relative-path"})
        elif _macos_evidence_exclusion_reason(normalized) is not None:
            skipped.append({"path": normalized, "reason": "credential-name-excluded"})
        elif not _is_allowed_macos_evidence_path(normalized, library_scope=True):
            skipped.append({"path": normalized, "reason": "path-not-allowed"})
        else:
            wanted.setdefault("task_db", []).append(normalized)
    return wanted, skipped


def _sha256_of_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_jsonable(value: Any, *, depth: int = 0) -> Any:
    """Convert guest payloads into JSON-serializable structures. Never raises."""
    if depth > 8:
        return str(value)[:512]
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return str(value)
        return value
    if isinstance(value, bytes):
        return {"bytes_sha256": _sha256_of_bytes(value), "size": len(value)}
    if isinstance(value, dict):
        safe: Dict[str, Any] = {}
        for key in list(value.keys())[:256]:
            try:
                safe[str(key)[:256]] = _safe_jsonable(value[key], depth=depth + 1)
            except Exception:
                safe[str(key)[:256]] = "<unserializable>"
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(item, depth=depth + 1) for item in list(value)[:256]]
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return str(value)[:2048]


def _guest_stat_file(controller: Any, guest_path: str) -> Dict[str, Any]:
    """Stat one guest path via argv-form /setup/execute (no shell)."""
    result = controller.execute_command(
        ["/usr/bin/python3", "-c", _MACOS_FINAL_STATE_STAT_CODE, guest_path],
        shell=False,
        timeout=MACOS_FINAL_STATE_GUEST_TIMEOUT,
    )
    output = str((result or {}).get("output") or "").strip()
    try:
        parsed = json.loads(output)
    except Exception as exc:
        raise RuntimeError(f"stat probe returned non-JSON output: {exc}")
    if not isinstance(parsed, dict):
        raise RuntimeError("stat probe returned unexpected payload")
    return parsed


def _guest_discover_thunderbird_calendar_dbs(controller: Any) -> List[str]:
    """Run the static Thunderbird discovery probe. Returns guest DB paths."""
    result = controller.run_python_script(
        _MACOS_FINAL_STATE_THUNDERBIRD_DISCOVERY_CODE,
        timeout=MACOS_FINAL_STATE_GUEST_TIMEOUT,
    )
    output = str((result or {}).get("output") or "").strip()
    try:
        parsed = json.loads(output)
    except Exception as exc:
        raise RuntimeError(f"thunderbird discovery returned non-JSON output: {exc}")
    dbs = (parsed or {}).get("dbs") if isinstance(parsed, dict) else None
    if not isinstance(dbs, list):
        raise RuntimeError("thunderbird discovery returned unexpected payload")
    cleaned: List[str] = []
    for entry in dbs[:4]:
        normalized = _macos_final_state_normalize_guest_path(entry)
        if normalized is None:
            continue
        if not _is_allowed_macos_evidence_path(normalized, library_scope=True):
            continue
        if _macos_evidence_exclusion_reason(normalized) is not None:
            continue
        cleaned.append(normalized)
    return cleaned


def _macos_stage_bytes(
    *,
    payload: bytes,
    arc_rel: str,
    staging_root: Path,
    files: List[Dict[str, Any]],
    skipped: List[Dict[str, Any]],
    budget_bytes: List[int],
    seen_arcs: set[str],
) -> None:
    size = len(payload)
    if size > MACOS_FINAL_STATE_MAX_FILE_BYTES:
        skipped.append({"path": arc_rel, "reason": "file-size-exceeded"})
        return
    if budget_bytes[0] + size > MACOS_FINAL_STATE_MAX_TOTAL_BYTES:
        skipped.append({"path": arc_rel, "reason": "total-budget-exceeded"})
        return
    if len(files) >= MACOS_FINAL_STATE_MAX_FILES:
        skipped.append({"path": arc_rel, "reason": "file-count-exceeded"})
        return
    unique_rel = arc_rel
    counter = 2
    while unique_rel in seen_arcs:
        unique_rel = f"{arc_rel}.{counter}"
        counter += 1
    seen_arcs.add(unique_rel)
    dest = staging_root / unique_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    budget_bytes[0] += size
    files.append(
        {
            "path": unique_rel,
            "guest_path": arc_rel,
            "size": size,
            "sha256": _sha256_of_bytes(payload),
        }
    )


def _macos_fetch_one_guest_file(
    *,
    controller: Any,
    guest_path: str,
    arc_rel: str,
    staging_root: Path,
    files: List[Dict[str, Any]],
    skipped: List[Dict[str, Any]],
    errors: List[str],
    budget_bytes: List[int],
    seen_arcs: set[str],
) -> None:
    try:
        stat = _guest_stat_file(controller, guest_path)
    except Exception as exc:
        errors.append(f"{arc_rel}: stat failed: {exc}")
        return
    if not stat.get("exists"):
        skipped.append({"path": arc_rel, "reason": "missing"})
        return
    if stat.get("is_symlink"):
        skipped.append({"path": arc_rel, "reason": "symlink-excluded"})
        return
    if not stat.get("is_file"):
        skipped.append({"path": arc_rel, "reason": "not-a-regular-file"})
        return
    try:
        size = int(stat.get("size", -1))
    except Exception:
        size = -1
    if size < 0:
        errors.append(f"{arc_rel}: stat returned invalid size")
        return
    if size > MACOS_FINAL_STATE_MAX_FILE_BYTES:
        skipped.append({"path": arc_rel, "reason": "file-size-exceeded"})
        return
    try:
        payload = bytes(controller.get_file(guest_path))
    except Exception as exc:
        message = str(exc)
        if "404" in message or "file not found" in message.lower():
            skipped.append({"path": arc_rel, "reason": "missing"})
        else:
            errors.append(f"{arc_rel}: download failed: {exc}")
        return
    _macos_stage_bytes(
        payload=payload,
        arc_rel=arc_rel,
        staging_root=staging_root,
        files=files,
        skipped=skipped,
        budget_bytes=budget_bytes,
        seen_arcs=seen_arcs,
    )


def _macos_arc_for_guest_path(guest_path: str) -> str:
    cleaned = guest_path.lstrip("/")
    if guest_path.startswith("/Users/bench/"):
        cleaned = "HOME/" + guest_path[len("/Users/bench/"):]
    return f"task_files/{cleaned}"


def capture_macos_final_state(
    *,
    runtime_url: str,
    token: str,
    task_id: str,
    task_file: Any,
    model_output_dir: Any,
    run_index: int,
    clone_name: Optional[str] = None,
    vm_ip: Optional[str] = None,
    model: Optional[str] = None,
    success: Optional[bool] = None,
    return_code: Optional[int] = None,
    controller: Any = None,
) -> Dict[str, Any]:
    """Archive post-run macOS state for later FAIL audits. Never raises.

    Administrative evidence only: the manifest is tagged as such and is
    never passed to the decision/scoring system; the child's PASS/FAIL
    outcome passes through untouched. Collection is read-only and bounded
    to task-relevant guest paths plus task-bound native stores, fetched
    through the supported guest APIs (``/health``, ``/version``,
    ``/device_info``, ``/screenshot``, ``/setup/execute``, ``/run_python``,
    ``/file``). Guest paths are validated before any guest call and are
    never interpolated into shell strings. Binary payloads are hashed, not
    embedded or logged.
    """
    manifest: Dict[str, Any] = {
        "evidence_kind": "administrative-final-state",
        "for_decision_system": False,
        "capture_notes": (
            "Administrative evidence only; never passed to DS/scoring. "
            "Live VM validation pending."
        ),
        "task_id": str(task_id),
        "task_file": str(task_file),
        "run_index": int(run_index),
        "model": str(model) if model is not None else None,
        "clone_name": str(clone_name) if clone_name else None,
        "vm_ip": str(vm_ip) if vm_ip else None,
        "runtime_url": str(runtime_url),
        "child_success": success,
        "child_return_code": return_code,
        "health": None,
        "version": None,
        "device_info": None,
        "screenshot": None,
        "archive": None,
        "archive_sha256": None,
        "archive_size": None,
        "archive_members": [],
        "files": [],
        "skipped": [],
        "errors": [],
    }
    final_state_dir = Path(model_output_dir) / MACOS_FINAL_STATE_DIRNAME
    errors: List[str] = manifest["errors"]
    files: List[Dict[str, Any]] = manifest["files"]
    skipped: List[Dict[str, Any]] = manifest["skipped"]
    budget_bytes = [0]
    seen_arcs: set[str] = set()
    try:
        final_state_dir.mkdir(parents=True, exist_ok=True)
        staging = final_state_dir / "_staging"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)

        if controller is None:
            from platforms.macos.host.runtime_env.vm_runtime_controller import (
                VMRuntimeController,
            )

            controller = VMRuntimeController(
                runtime_url=str(runtime_url), token=str(token), timeout=20.0
            )

        try:
            manifest["health"] = _safe_jsonable(controller.health())
        except Exception as exc:
            errors.append(f"health: {exc}")
        try:
            manifest["version"] = _safe_jsonable(
                controller._request_json("GET", "/version")
            )
        except Exception as exc:
            errors.append(f"version: {exc}")
        try:
            manifest["device_info"] = _safe_jsonable(controller.get_device_info())
        except Exception as exc:
            errors.append(f"device_info: {exc}")

        screenshot_path = final_state_dir / MACOS_FINAL_STATE_SCREENSHOT_NAME
        try:
            shot_bytes = bytes(controller._request_binary("GET", "/screenshot"))
            if not shot_bytes:
                errors.append("screenshot: guest returned empty payload")
            else:
                screenshot_path.write_bytes(shot_bytes)
                manifest["screenshot"] = {
                    "path": MACOS_FINAL_STATE_SCREENSHOT_NAME,
                    "size": len(shot_bytes),
                    "sha256": _sha256_of_bytes(shot_bytes),
                }
        except Exception as exc:
            errors.append(f"screenshot: {exc}")

        allowed_paths, path_skipped = resolve_macos_task_evidence_paths(task_file)
        skipped.extend(path_skipped)
        for guest_path in allowed_paths:
            arc_rel = _macos_arc_for_guest_path(guest_path)
            _macos_fetch_one_guest_file(
                controller=controller,
                guest_path=guest_path,
                arc_rel=arc_rel,
                staging_root=staging,
                files=files,
                skipped=skipped,
                errors=errors,
                budget_bytes=budget_bytes,
                seen_arcs=seen_arcs,
            )

        native_wanted, native_skipped = _native_macos_state_candidates(
            task_id=task_id, task_file=task_file
        )
        skipped.extend(native_skipped)
        for label, relpaths in native_wanted.items():
            for rel in relpaths:
                try:
                    if rel == "__thunderbird_discovery__":
                        try:
                            discovered = _guest_discover_thunderbird_calendar_dbs(
                                controller
                            )
                        except Exception as exc:
                            errors.append(f"native/{label}: discovery failed: {exc}")
                            continue
                        if not discovered:
                            skipped.append(
                                {
                                    "path": f"native/{label}/calendar-data/local.sqlite",
                                    "reason": "missing",
                                }
                            )
                            continue
                        for db_path in discovered:
                            _macos_fetch_one_guest_file(
                                controller=controller,
                                guest_path=db_path,
                                arc_rel=f"native/{label}/local.sqlite",
                                staging_root=staging,
                                files=files,
                                skipped=skipped,
                                errors=errors,
                                budget_bytes=budget_bytes,
                                seen_arcs=seen_arcs,
                            )
                            for suffix in _MACOS_FINAL_STATE_SQLITE_SIDECAR_SUFFIXES:
                                _macos_fetch_one_guest_file(
                                    controller=controller,
                                    guest_path=db_path + suffix,
                                    arc_rel=f"native/{label}/local.sqlite{suffix}",
                                    staging_root=staging,
                                    files=files,
                                    skipped=skipped,
                                    errors=errors,
                                    budget_bytes=budget_bytes,
                                    seen_arcs=seen_arcs,
                                )
                        continue
                    _macos_fetch_one_guest_file(
                        controller=controller,
                        guest_path=rel,
                        arc_rel=f"native/{label}/{os.path.basename(rel)}",
                        staging_root=staging,
                        files=files,
                        skipped=skipped,
                        errors=errors,
                        budget_bytes=budget_bytes,
                        seen_arcs=seen_arcs,
                    )
                    for suffix in _MACOS_FINAL_STATE_SQLITE_SIDECAR_SUFFIXES:
                        if rel.lower().endswith((".sqlite", ".sqlitedb", ".abcddb", ".store.sqlitedb")):
                            _macos_fetch_one_guest_file(
                                controller=controller,
                                guest_path=rel + suffix,
                                arc_rel=f"native/{label}/{os.path.basename(rel)}{suffix}",
                                staging_root=staging,
                                files=files,
                                skipped=skipped,
                                errors=errors,
                                budget_bytes=budget_bytes,
                                seen_arcs=seen_arcs,
                            )
                except Exception as exc:
                    errors.append(f"native/{label}: {exc}")

        archive_path = final_state_dir / MACOS_FINAL_STATE_ARCHIVE_NAME
        try:
            members: List[str] = []
            with tarfile.open(archive_path, "w:gz") as tar:
                for src in sorted(staging.rglob("*")):
                    if src.is_file():
                        arcname = src.relative_to(staging).as_posix()
                        tar.add(str(src), arcname=arcname)
                        members.append(arcname)
            manifest["archive"] = MACOS_FINAL_STATE_ARCHIVE_NAME
            manifest["archive_members"] = sorted(members)
            manifest["archive_sha256"] = _sha256_of_file(archive_path)
            manifest["archive_size"] = archive_path.stat().st_size
        except Exception as exc:
            errors.append(f"archive: {exc}")

        try:
            shutil.rmtree(staging, ignore_errors=False)
        except Exception as exc:
            errors.append(f"staging_cleanup: {exc}")
    except Exception as exc:
        errors.append(f"capture: {exc}")
    finally:
        try:
            (final_state_dir / MACOS_FINAL_STATE_MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
        except Exception:
            pass
    return manifest


class MacOSBenchmarkRunner(BaseBenchmarkRunner):
    def __init__(self) -> None:
        super().__init__(logger)
        self._manager: Optional[MacOSVMManager] = None

    @staticmethod
    def _skip_vm_clone_enabled() -> bool:
        return os.environ.get(MACOS_SKIP_VM_CLONE_ENV, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _env_truthy(name: str) -> bool:
        return os.environ.get(name, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _guest_runtime_sync_enabled() -> bool:
        if MacOSBenchmarkRunner._env_truthy(MACOS_SKIP_GUEST_RUNTIME_SYNC_ENV):
            return False
        return MacOSBenchmarkRunner._env_truthy(MACOS_ENABLE_GUEST_RUNTIME_SYNC_ENV)

    @staticmethod
    def _resolve_guest_ssh_identity_file() -> Optional[Path]:
        identity_file = os.environ.get(MACOS_GUEST_SSH_IDENTITY_FILE_ENV, "").strip()
        if identity_file:
            return Path(identity_file).expanduser()

        default_identity_file = Path.home() / ".ssh" / MACOS_DEFAULT_GUEST_SSH_IDENTITY_BASENAME
        if default_identity_file.exists():
            return default_identity_file
        return None

    @staticmethod
    def _guest_ssh_options() -> List[str]:
        options = [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "PreferredAuthentications=publickey",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "IdentityAgent=none",
        ]
        identity_file = MacOSBenchmarkRunner._resolve_guest_ssh_identity_file()
        if identity_file:
            options.extend(["-i", str(identity_file)])
        return options

    @staticmethod
    def _build_clone_name(run_index: int, model: str, task_id: str) -> str:
        timestamp_ms = int(time.time() * 1000)
        safe_model = BaseBenchmarkRunner.safe_name(model)
        safe_task = BaseBenchmarkRunner.safe_name(task_id)
        return f"{run_index:04d}_{safe_model}_{safe_task}_{timestamp_ms}"

    @staticmethod
    def _resolve_task_base_vm_name(task_file: str) -> Optional[str]:
        source_path = Path(task_file).resolve()
        try:
            payload = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.exception("Failed to resolve task-specific base_vm_name from %s", source_path)
            return None

        if not isinstance(payload, dict):
            return None

        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            candidate = metadata.get("base_vm_name")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        init = payload.get("init")
        if isinstance(init, dict):
            params = init.get("params")
            if isinstance(params, dict):
                candidate = params.get("base_vm_name")
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()

        return None

    @staticmethod
    def _resolve_execution_base_vm_name(execution_file: str | None) -> Optional[str]:
        if not execution_file:
            return None
        source_path = Path(execution_file).resolve()
        try:
            payload = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.exception("Failed to resolve execution-specific base_vm_name from %s", source_path)
            return None

        if not isinstance(payload, dict):
            return None

        candidate = payload.get("base_vm_name")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            candidate = metadata.get("base_vm_name")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        return None

    @staticmethod
    def _sync_guest_runtime(vm_ip: str) -> Tuple[bool, Optional[str]]:
        source_path = MACOS_PLATFORM_DIR / "guest" / "runtime_server.py"
        requirements_path = MACOS_PLATFORM_DIR / "guest" / "requirements.txt"
        if not source_path.exists():
            return False, f"runtime source not found: {source_path}"
        if not requirements_path.exists():
            return False, f"runtime requirements not found: {requirements_path}"

        ssh_options = MacOSBenchmarkRunner._guest_ssh_options()
        ssh_base = ["ssh", *ssh_options, f"bench@{vm_ip}"]
        scp_base = [
            "scp",
            *ssh_options,
            str(source_path),
            str(requirements_path),
            f"bench@{vm_ip}:/tmp/",
        ]

        remote_cmd = (
            "sudo cp /tmp/runtime_server.py "
            f"{GUEST_RUNTIME_INSTALL_PATH} && "
            "sudo cp /tmp/requirements.txt "
            f"{GUEST_REQUIREMENTS_INSTALL_PATH} && "
            f"{GUEST_RUNTIME_VENV_PIP} install -r {GUEST_REQUIREMENTS_INSTALL_PATH} >/tmp/helloworld_macos_pip_sync.log 2>&1 && "
            f"{GUEST_RUNTIME_VENV_PYTHON} -m py_compile {GUEST_RUNTIME_INSTALL_PATH} && "
            f"launchctl kickstart -k gui/$(id -u)/{GUEST_RUNTIME_LABEL}"
        )

        last_error: Optional[str] = None
        for _ in range(GUEST_RUNTIME_SYNC_RETRIES):
            try:
                scp_proc = subprocess.run(
                    scp_base,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if scp_proc.returncode != 0:
                    last_error = (scp_proc.stderr or scp_proc.stdout or "").strip() or "scp failed"
                    time.sleep(GUEST_RUNTIME_SYNC_INTERVAL_SECONDS)
                    continue

                ssh_proc = subprocess.run(
                    [*ssh_base, remote_cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=20,
                    check=False,
                )
                if ssh_proc.returncode == 0:
                    return True, None
                last_error = (ssh_proc.stderr or ssh_proc.stdout or "").strip() or "ssh remote command failed"
            except Exception as exc:
                last_error = str(exc)
            time.sleep(GUEST_RUNTIME_SYNC_INTERVAL_SECONDS)

        return False, last_error or "unknown guest runtime sync failure"

    @staticmethod
    def _make_run_record(
        *,
        run_index: int,
        model: str,
        task_id: str,
        task_file: str,
        args,
        success: bool = False,
        return_code: Optional[int] = None,
        duration_seconds: float = 0.0,
        reset_ok: bool = True,
        reset_error: Optional[str] = None,
        trajectory_path: Optional[str] = None,
        result_path: Optional[str] = None,
        artifact_dir: Optional[Path | str] = None,
        runner_log_path: Optional[Path] = None,
        clone_name: Optional[str] = None,
        vm_ip: Optional[str] = None,
        runtime_url: Optional[str] = None,
        cleanup_error: Optional[str] = None,
        base_vm_name: Optional[str] = None,
        final_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "run_index": run_index,
            "model": model,
            "task_id": task_id,
            "task_file": task_file,
            "success": success,
            "return_code": return_code,
            "duration_seconds": round(duration_seconds, 2) if duration_seconds else 0.0,
            "reset_ok": reset_ok,
            "reset_error": reset_error,
            "mode": args.action_mode,
            "trajectory_path": trajectory_path,
            "result_path": result_path,
            "artifact_dir": str(artifact_dir) if artifact_dir else None,
            "runner_log": str(runner_log_path) if runner_log_path else None,
            "stdout_log": str(runner_log_path) if runner_log_path else None,
            "stderr_log": None,
            "clone_name": clone_name,
            "vm_ip": vm_ip,
            "runtime_url": runtime_url,
            "cleanup_error": cleanup_error,
            "base_vm_name": base_vm_name,
            "final_state": final_state,
        }

    @staticmethod
    def _prepare_vm_for_run(
        args,
        context: Dict[str, Any],
        manager: Optional[MacOSVMManager],
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str], Optional[str]]:
        fallback_vm_ip = str(args.vm_ip)
        runtime_url = f"http://{fallback_vm_ip}:{int(args.runtime_port)}"
        if MacOSBenchmarkRunner._skip_vm_clone_enabled():
            return True, None, None, fallback_vm_ip, runtime_url
        if manager is None:
            return False, "VM manager is not initialized", None, None, None

        base_vm_name = context.get("base_vm_name") or args.base_vm_name
        clone_name = context.get("clone_name")
        if not base_vm_name:
            return False, "--base-vm-name is required", None, None, None

        prepared = manager.prepare_benchmark_environment(
            base_vm_name=base_vm_name,
            clone_name=str(clone_name).strip() if clone_name else None,
        )
        if not prepared:
            return False, f"prepare_benchmark_environment failed (base={base_vm_name})", None, None, None

        clone_name = prepared

        time.sleep(CLONE_POST_BOOT_SETTLE_SECONDS)
        vm_ip = manager.resolve_runtime_host(clone_name, fallback_host=fallback_vm_ip)
        if MacOSBenchmarkRunner._guest_runtime_sync_enabled():
            sync_ok, sync_error = MacOSBenchmarkRunner._sync_guest_runtime(vm_ip)
            if not sync_ok:
                manager.cleanup_benchmark_environment(clone_name)
                return False, f"guest runtime sync failed for {vm_ip}: {sync_error}", clone_name, vm_ip, None
        runtime_url = f"http://{vm_ip}:{int(args.runtime_port)}"

        return True, None, clone_name, vm_ip, runtime_url

    @staticmethod
    def _cleanup_ephemeral_vm(
        manager: MacOSVMManager,
        clone_name: Optional[str],
    ) -> Tuple[bool, Optional[str]]:
        if not clone_name:
            return True, None
        try:
            ok = manager.cleanup_benchmark_environment(clone_name)
            if ok:
                return True, None
            return False, f"cleanup_benchmark_environment failed for {clone_name}"
        except Exception as e:
            return False, f"cleanup_benchmark_environment exception for {clone_name}: {e}"

    def _validate_and_get_models(self, args: Any) -> List[str]:
        if str(args.action_mode).strip() != "code_adapter":
            raise ValueError("--action-mode must be code_adapter")

        raw_models = self.parse_csv_list(args.models)
        if not raw_models:
            raise ValueError("--models cannot be empty")
        return list(dict.fromkeys(raw_models))

    def _load_task_descriptor(self, args: Any) -> Dict[str, Any]:
        task_file = str(args.task_file)
        task = load_task_from_file(task_file)
        if not task.source_file:
            raise ValueError(f"Task file has no source path: {task_file}")
        resolved_task_file = str(Path(task.source_file).resolve())
        execution_base_vm_name = self._resolve_execution_base_vm_name(getattr(args, "execution_file", None))
        return {
            "task_id": task.id,
            "task_goal": task.goal,
            "task_file": resolved_task_file,
            "base_vm_name": self._resolve_task_base_vm_name(resolved_task_file) or execution_base_vm_name,
        }

    def _build_benchmark_jobs(
        self,
        task: Dict[str, Any],
        models: List[str],
        args: Any,
    ) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        for run_index, model in enumerate(models, start=1):
            jobs.append(
                {
                    "run_index": run_index,
                    "model": model,
                    "task_id": task["task_id"],
                    "task_goal": task["task_goal"],
                    "task_file": task["task_file"],
                    "base_vm_name": task.get("base_vm_name"),
                }
            )
        return jobs

    def _resolve_benchmark_name(self, args: Any) -> str:
        return self.safe_name(getattr(args, "benchmark_name", None) or "macos_benchmark")

    def _prepare_benchmark_dirs(
        self,
        *,
        args: Any,
        benchmark_name: str,
        timestamp: str,
    ) -> Tuple[Path, Path, Path]:
        output_root = Path(str(getattr(args, "output_root", MACOS_BENCHMARK_OUTPUT_ROOT)))
        benchmark_dir = output_root / f"{benchmark_name}_{timestamp}"
        run_root = benchmark_dir
        runner_log_path = benchmark_dir / "runner.log"
        benchmark_dir.mkdir(parents=True, exist_ok=True)
        run_root.mkdir(parents=True, exist_ok=True)
        return benchmark_dir, run_root, runner_log_path

    @staticmethod
    def _resolve_run_output_dir(
        run_root: Path,
        *,
        model: str,
        model_count: int,
    ) -> Path:
        if int(model_count) > 1:
            return run_root / BaseBenchmarkRunner.safe_name(model)
        return run_root

    def _log_benchmark_start(
        self,
        *,
        args: Any,
        benchmark_name: str,
        benchmark_dir: Path,
        run_root: Path,
        runner_log_path: Path,
        task: Dict[str, Any],
        models: List[str],
        jobs: List[Dict[str, Any]],
    ) -> None:
        effective_base_vm_name = str(task.get("base_vm_name") or args.base_vm_name or "").strip() or None
        logger.info("Benchmark Dir: %s", benchmark_dir)
        logger.info("Task: %s, Models: %s", task["task_id"], models)
        logger.info("Base VM Name: %s", effective_base_vm_name or args.base_vm_name)
        logger.info("Skip VM Clone: %s", "yes" if self._skip_vm_clone_enabled() else "no")
        logger.info("VM IP: %s", args.vm_ip)
        logger.info("Runtime Port: %d", int(args.runtime_port))
        self.append_runner_log(
            runner_log_path,
            (
                f"# Benchmark: {benchmark_name}\n"
                f"# Created: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
                f"# Task id: {task['task_id']}\n"
                f"# Task file: {task['task_file']}\n"
                f"# Models: {','.join(models)}\n"
                f"# Base VM Name: {effective_base_vm_name or args.base_vm_name}\n"
                f"# Skip VM Clone: {'yes' if self._skip_vm_clone_enabled() else 'no'}\n"
                f"# VM IP: {args.vm_ip}\n"
                f"# Runtime Port: {args.runtime_port}\n"
            ),
        )

    def _before_runs(
        self,
        args: Any,
        task: Dict[str, Any],
        models: List[str],
        benchmark_dir: Path,
        run_root: Path,
        runner_log_path: Path,
    ) -> None:
        if self._skip_vm_clone_enabled():
            self._manager = None
            return
        effective_base_vm_name = str(task.get("base_vm_name") or args.base_vm_name or "").strip()
        if not effective_base_vm_name:
            raise ValueError("--base-vm-name is required")
        manager = create_macos_vm_manager(getattr(args, "vm_provider", "tart"), tart_home=getattr(args, "tart_home", None))
        if not manager.vm_exists(effective_base_vm_name):
            raise ValueError(f"Base VM not found: {effective_base_vm_name}")
        self._manager = manager

    def _after_runs(
        self,
        args: Any,
        task: Dict[str, Any],
        models: List[str],
        benchmark_dir: Path,
        run_root: Path,
        runner_log_path: Path,
        run_records: List[Dict[str, Any]],
    ) -> None:
        self._manager = None

    def _resolve_cli_entry_path(self) -> str:
        return str(MACOS_PLATFORM_DIR / "host" / "cli.py")

    def _maybe_capture_macos_final_state(
        self,
        *,
        runtime_url: Optional[str],
        token: Optional[str],
        task_id: str,
        task_file: str,
        model_output_dir: Path,
        run_index: int,
        clone_name: Optional[str] = None,
        vm_ip: Optional[str] = None,
        model: Optional[str] = None,
        success: Optional[bool] = None,
        return_code: Optional[int] = None,
        runner_log_path: Optional[Path] = None,
        controller: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Opt-in post-run state archive. Returns manifest dict or None.

        Returns None when the ``OS_OMNI_CAPTURE_MACOS_FINAL_STATE=1`` flag
        is unset or no runtime URL is available. Never raises and never
        alters the run's PASS/FAIL outcome; per-step failures are recorded
        in the manifest and runner log only. The auth token is never logged
        or stored in the manifest.
        """
        if not macos_final_state_capture_enabled():
            return None
        if not str(runtime_url or "").strip():
            return None
        try:
            manifest = capture_macos_final_state(
                runtime_url=str(runtime_url),
                token=str(token or ""),
                task_id=task_id,
                task_file=task_file,
                model_output_dir=model_output_dir,
                run_index=run_index,
                clone_name=clone_name,
                vm_ip=vm_ip,
                model=model,
                success=success,
                return_code=return_code,
                controller=controller,
            )
        except Exception as exc:
            manifest = {
                "evidence_kind": "administrative-final-state",
                "for_decision_system": False,
                "task_id": str(task_id),
                "run_index": int(run_index),
                "errors": [f"capture: {exc}"],
            }
        if runner_log_path is not None:
            try:
                self.append_runner_log(
                    runner_log_path,
                    (
                        f"[Run {run_index}] final_state "
                        f"dir={Path(model_output_dir) / MACOS_FINAL_STATE_DIRNAME} "
                        f"archive={manifest.get('archive') or ''} "
                        f"errors={manifest.get('errors') or []}"
                    ),
                )
            except Exception:
                pass
        return manifest

    def _execute_single_run(
        self,
        *,
        args: Any,
        job: Dict[str, Any],
        cli_entry_path: str,
        run_root: Path,
        runner_log_path: Path,
    ) -> Dict[str, Any]:
        run_index = int(job["run_index"])
        model = str(job["model"])
        task_id = str(job["task_id"])
        task_file = str(job["task_file"])
        effective_base_vm_name = str(job.get("base_vm_name") or args.base_vm_name or "").strip() or None

        model_count = len(self.parse_csv_list(args.models))
        model_output_dir = self._resolve_run_output_dir(
            run_root,
            model=model,
            model_count=model_count,
        )
        model_output_dir.mkdir(parents=True, exist_ok=True)

        clone_name = self._build_clone_name(run_index, model, task_id)

        context = {
            "model": model,
            "task_id": task_id,
            "task_file": task_file,
            "run_index": run_index,
            "base_vm_name": effective_base_vm_name,
            "clone_name": clone_name,
        }

        logger.info("=" * 72)
        logger.info("[Run %d] model=%s task=%s", run_index, model, task_id)
        logger.info("=" * 72)
        self.append_runner_log(
            runner_log_path,
            (
                f"\n[Run {run_index}] model={model} task={task_id}\n"
                f"[Run {run_index}] task_file={task_file}\n"
                f"[Run {run_index}] effective_base_vm_name={effective_base_vm_name or ''}"
            ),
        )

        clone_name: Optional[str] = None
        vm_ip = str(args.vm_ip)
        runtime_url: Optional[str] = None
        cleanup_error: Optional[str] = None
        record: Optional[Dict[str, Any]] = None
        child_started = False
        child_success: Optional[bool] = None
        child_return_code: Optional[int] = None

        try:
            reset_ok, reset_error, clone_name, resolved_vm_ip, runtime_url = self._prepare_vm_for_run(
                args,
                context,
                self._manager,
            )
            if resolved_vm_ip:
                vm_ip = str(resolved_vm_ip)
            if not reset_ok:
                self.append_runner_log(runner_log_path, f"[Run {run_index}] reset_failed={reset_error}")
                record = self._make_run_record(
                    run_index=run_index,
                    model=model,
                    task_id=task_id,
                    task_file=task_file,
                    args=args,
                    success=False,
                    reset_ok=False,
                    reset_error=reset_error,
                    runner_log_path=runner_log_path,
                    artifact_dir=model_output_dir,
                    clone_name=clone_name,
                    vm_ip=vm_ip,
                    runtime_url=runtime_url,
                    base_vm_name=effective_base_vm_name,
                )
                return record

            assert runtime_url is not None
            cmd = [
                sys.executable,
                cli_entry_path,
                INTERNAL_BENCHMARK_TASK_COMMAND,
                "--task-file",
                task_file,
                "--model",
                model,
                "--action-mode",
                args.action_mode,
                "--observation-mode",
                str(getattr(args, "observation_mode", "screenshot_and_a11y_tree")),
                "--prompt-profile",
                str(getattr(args, "prompt_profile", "benchmark")),
                "--history-window",
                str(int(getattr(args, "history_window", 5))),
                "--vm-ip",
                vm_ip,
                "--runtime-port",
                str(args.runtime_port),
                "--vm-token",
                str(args.vm_token),
            ]
            if getattr(args, "execution_file", None):
                cmd.extend(["--execution-file", str(args.execution_file)])
            if args.max_steps is not None:
                cmd.extend(["--max-steps", str(args.max_steps)])
            if args.timeout is not None:
                cmd.extend(["--timeout", str(args.timeout)])
            child_env = os.environ.copy()
            child_env[MACOS_OUTPUT_DIR_ENV] = str(model_output_dir)
            child_env[MACOS_SKIP_VM_CLONE_ENV] = "1"

            logger.info("[Run %d] runtime_url=%s clone=%s", run_index, runtime_url, clone_name)
            self.append_runner_log(
                runner_log_path,
                f"[Run {run_index}] runtime_url={runtime_url} clone={clone_name} ip={vm_ip or ''}",
            )

            run_start = time.time()
            child_started = True
            return_code = self.run_command_streaming(
                cmd,
                runner_log_path,
                run_prefix=f"Run {run_index}",
                env=child_env,
                child_log_mode="logger",
            )
            duration_seconds = time.time() - run_start
            child_return_code = return_code
            child_success = return_code == 0

            artifact_paths = self.resolve_run_artifact_paths(model_output_dir)
            trajectory_path = artifact_paths["trajectory_path"]
            result_path = artifact_paths["result_path"]
            artifact_dir = artifact_paths["run_dir"]
            success = return_code == 0
            status = "SUCCESS" if success else "FAILED"
            logger.info("[Run %d] %s (%.1fs)", run_index, status, duration_seconds)
            if trajectory_path:
                logger.info("[Run %d] Trajectory: %s", run_index, trajectory_path)
            if result_path:
                logger.info("[Run %d] Result: %s", run_index, result_path)

            self.append_runner_log(
                runner_log_path,
                (
                    f"[Run {run_index}] status={status} duration={duration_seconds:.2f}s "
                    f"trajectory={trajectory_path or ''} result={result_path or ''}"
                ),
            )

            record = self._make_run_record(
                run_index=run_index,
                model=model,
                task_id=task_id,
                task_file=task_file,
                args=args,
                success=success,
                return_code=return_code,
                duration_seconds=duration_seconds,
                reset_ok=True,
                trajectory_path=trajectory_path,
                result_path=result_path,
                artifact_dir=artifact_dir,
                runner_log_path=runner_log_path,
                clone_name=clone_name,
                vm_ip=vm_ip,
                runtime_url=runtime_url,
                base_vm_name=effective_base_vm_name,
            )
            return record
        finally:
            # Opt-in final-state capture runs after the child stops and BEFORE
            # clone cleanup, so the clone's guest state still exists. Capture
            # failures are recorded in the manifest/runner log and never
            # change the run outcome.
            final_state_info: Optional[Dict[str, Any]] = None
            if child_started and runtime_url:
                try:
                    final_state_info = self._maybe_capture_macos_final_state(
                        runtime_url=runtime_url,
                        token=str(getattr(args, "vm_token", "") or ""),
                        task_id=task_id,
                        task_file=task_file,
                        model_output_dir=model_output_dir,
                        run_index=run_index,
                        clone_name=clone_name,
                        vm_ip=vm_ip,
                        model=model,
                        success=child_success,
                        return_code=child_return_code,
                        runner_log_path=runner_log_path,
                    )
                except Exception as capture_exc:
                    logger.warning(
                        "[Run %d] final-state capture warning: %s",
                        run_index,
                        capture_exc,
                    )
            if clone_name and self._manager is not None:
                _, cleanup_error = self._cleanup_ephemeral_vm(self._manager, clone_name)
                if cleanup_error:
                    logger.warning("[Run %d] clone cleanup warning: %s", run_index, cleanup_error)
                self.append_runner_log(
                    runner_log_path,
                    f"[Run {run_index}] cleanup_error={cleanup_error or ''}",
                )
            if record is not None:
                record["cleanup_error"] = cleanup_error
                record["final_state"] = final_state_info

    def _build_exception_record(
        self,
        *,
        args: Any,
        job: Dict[str, Any],
        error: Exception,
        runner_log_path: Path,
    ) -> Dict[str, Any]:
        run_index = int(job.get("run_index", 0))
        model = str(job.get("model", ""))
        task_id = str(job.get("task_id", ""))
        task_file = str(job.get("task_file", ""))
        err_text = self.format_uncaught_error(error)
        logger.error("[Run %d] UNCAUGHT ERROR: %s", run_index, error)
        self.append_runner_log(
            runner_log_path,
            f"[Run {run_index}] uncaught_error={err_text}",
        )
        return self._make_run_record(
            run_index=run_index,
            model=model,
            task_id=task_id,
            task_file=task_file,
            args=args,
            success=False,
            reset_ok=False,
            reset_error=str(error),
            runner_log_path=runner_log_path,
            vm_ip=str(args.vm_ip),
            runtime_url=f"http://{args.vm_ip}:{int(args.runtime_port)}",
            base_vm_name=str(job.get("base_vm_name") or args.base_vm_name or "").strip() or None,
        )

    def _log_completion(
        self,
        *,
        args: Any,
        run_records: List[Dict[str, Any]],
        runner_log_path: Path,
    ) -> None:
        total_runs = len(run_records)
        total_success = sum(1 for r in run_records if r["success"])
        logger.info("=" * 72)
        logger.info("BENCHMARK COMPLETE")
        if total_runs > 0:
            logger.info(
                "Runs: %d, Success: %d, Rate: %.1f%%",
                total_runs,
                total_success,
                (total_success / total_runs) * 100.0,
            )
        else:
            logger.info("Runs: 0")
        logger.info("Runner Log: %s", runner_log_path)
        logger.info("=" * 72)


def run_benchmark_command(args) -> int:
    return MacOSBenchmarkRunner().run(args)


__all__ = [
    "MACOS_BENCHMARK_OUTPUT_ROOT",
    "run_benchmark_command",
]
