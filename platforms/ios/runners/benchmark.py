#!/usr/bin/env python3
"""
Benchmark runner for serial clone -> run -> delete experiments.
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
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from platforms.ios.runners.base_benchmark import BaseBenchmarkRunner

from platforms.ios.runtime_env.simulator_manager import (
    boot_simulator,
    clone_simulator,
    delete_simulator,
    find_simulator_udid_by_name,
    get_simulator_state,
    shutdown_simulator,
    shutdown_simulator_and_wait,
    simctl_udid_exists,
)

IOS_PLATFORM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
IOS_DEFAULT_BENCHMARK_DIR = str(REPO_ROOT / "results" / "ios")
INTERNAL_BENCHMARK_JOB_COMMAND = "__benchmark_job"
BENCHMARK_POST_RESET_WAIT_SECONDS = 1.5
BENCHMARK_CLONE_MAX_ATTEMPTS = 2
BENCHMARK_CLONE_RETRY_WAIT_SECONDS = 2.0
BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS = 30.0

OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV = "OS_OMNI_CAPTURE_IOS_FINAL_STATE"
IOS_FINAL_STATE_DIRNAME = "final_state"
IOS_FINAL_STATE_ARCHIVE_NAME = "final_state.tar.gz"
IOS_FINAL_STATE_MANIFEST_NAME = "manifest.json"
IOS_FINAL_STATE_SCREENSHOT_NAME = "final_screenshot.png"
IOS_FINAL_STATE_MAX_FILE_BYTES = 256 * 1024 * 1024
IOS_FINAL_STATE_MAX_TOTAL_BYTES = 512 * 1024 * 1024

IOS_CONTACTS_BUNDLE_ID = "com.apple.MobileAddressBook"
IOS_CALENDAR_BUNDLE_ID = "com.apple.mobilecal"
IOS_PHOTOS_BUNDLE_IDS = frozenset({"com.apple.mobileslideshow", "com.apple.Photos"})

# File-name hints for secrets/credentials. Matching files are never staged into
# the final-state archive; the exclusion is recorded in the manifest instead.
_IOS_FINAL_STATE_CREDENTIAL_HINTS = (
    "keychain",
    "credential",
    "password",
    "secret",
    "token",
    "auth",
)


def _child_pythonpath(repo_root: Path, inherited: Optional[str]) -> str:
    """Give direct CLI children an absolute repo path without relative shadows."""
    paths = [str(repo_root.resolve())]
    for item in str(inherited or "").split(os.pathsep):
        candidate = item.strip()
        if candidate and Path(candidate).is_absolute() and candidate not in paths:
            paths.append(candidate)
    return os.pathsep.join(paths)

logger = logging.getLogger(__name__)


def ios_final_state_capture_enabled() -> bool:
    """Return True only when the opt-in final-state capture env flag is set."""
    return (
        os.environ.get(OS_OMNI_CAPTURE_IOS_FINAL_STATE_ENV, "").strip().lower()
        in {"1", "true", "yes"}
    )


def resolve_ios_task_bundle_id(task_file: Any) -> Optional[str]:
    """Resolve the task app bundle ID without importing task semantics.

    Priority: ``task.metadata.app_bundle_id`` then ``init.params.bundle_id``
    (falling back to ``init.params.launch_app_bundle_id``). Returns None when
    the file cannot be read or carries no bundle ID. Never raises.
    """
    try:
        text = Path(task_file).read_text(encoding="utf-8")
    except Exception:
        return None

    data: Any = None
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except Exception:
        data = None

    if isinstance(data, dict):
        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            candidate = metadata.get("app_bundle_id")
            if str(candidate or "").strip():
                return str(candidate).strip()
        init = data.get("init")
        if isinstance(init, dict):
            params = init.get("params")
            if isinstance(params, dict):
                for key in ("bundle_id", "launch_app_bundle_id"):
                    candidate = params.get(key)
                    if str(candidate or "").strip():
                        return str(candidate).strip()
        return None

    match = None
    try:
        import re

        match = re.search(
            r"app_bundle_id\s*:\s*[\"']?([A-Za-z0-9_.~-]+)", text
        ) or re.search(r"bundle_id\s*:\s*[\"']?([A-Za-z0-9_.~-]+)", text)
    except Exception:
        match = None
    if match:
        return match.group(1).strip() or None
    return None


def _ios_device_data_dir(udid: str) -> Path:
    return (
        Path.home()
        / "Library"
        / "Developer"
        / "CoreSimulator"
        / "Devices"
        / str(udid)
        / "data"
    )


def _native_ios_state_relpaths(
    *,
    bundle_id: Optional[str],
    task_id: str,
) -> Dict[str, List[str]]:
    """Map capture label to device-data-relative SQLite paths when relevant."""
    bid = str(bundle_id or "").strip()
    tid = str(task_id or "").lower()
    wanted: Dict[str, List[str]] = {}
    if bid == IOS_CONTACTS_BUNDLE_ID or "contact" in tid:
        wanted["contacts"] = [
            "Library/AddressBook/AddressBook.sqlitedb",
            "Library/AddressBook/AddressBook.sqlitedb-wal",
            "Library/AddressBook/AddressBook.sqlitedb-shm",
            "Library/AddressBook/AddressBookImages.sqlitedb",
            "Library/AddressBook/AddressBookImages.sqlitedb-wal",
            "Library/AddressBook/AddressBookImages.sqlitedb-shm",
        ]
    if bid == IOS_CALENDAR_BUNDLE_ID or "calendar" in tid or "reminder" in tid:
        wanted["calendar"] = [
            "Library/Calendar/Calendar.sqlitedb",
            "Library/Calendar/Calendar.sqlitedb-wal",
            "Library/Calendar/Calendar.sqlitedb-shm",
        ]
    if bid in IOS_PHOTOS_BUNDLE_IDS or "photo" in tid:
        wanted["photos"] = [
            "Media/PhotoData/Photos.sqlite",
            "Media/PhotoData/Photos.sqlite-wal",
            "Media/PhotoData/Photos.sqlite-shm",
        ]
    return wanted


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_file_for_capture(
    *,
    src: Path,
    arc_rel: str,
    staging_root: Path,
    files: List[Dict[str, Any]],
    skipped: List[Dict[str, Any]],
    errors: List[str],
    budget_bytes: List[int],
) -> None:
    try:
        if not src.is_file():
            return
        lowered = src.name.lower()
        if any(hint in lowered for hint in _IOS_FINAL_STATE_CREDENTIAL_HINTS):
            skipped.append({"path": arc_rel, "reason": "credential-name-excluded"})
            return
        size = src.stat().st_size
        if size > IOS_FINAL_STATE_MAX_FILE_BYTES:
            skipped.append({"path": arc_rel, "reason": "file-size-exceeded"})
            return
        if budget_bytes[0] + size > IOS_FINAL_STATE_MAX_TOTAL_BYTES:
            skipped.append({"path": arc_rel, "reason": "total-budget-exceeded"})
            return
        dest = staging_root / arc_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        budget_bytes[0] += size
        files.append(
            {"path": arc_rel, "size": size, "sha256": _sha256_of_file(dest)}
        )
    except Exception as exc:
        errors.append(f"{arc_rel}: {exc}")


def _ios_shared_group_paths(udid: str, bundle_id: str) -> list[tuple[str, Path]]:
    result = subprocess.run(
        ["xcrun", "simctl", "get_app_container", udid, bundle_id, "groups"],
        capture_output=True, text=True, timeout=15, check=True,
    )
    from platforms.ios.runtime_env.simulator_manager import remap_simulator_container_path
    return [(line.split("\t", 1)[0], remap_simulator_container_path(line.split("\t", 1)[1], udid))
            for line in result.stdout.splitlines() if "\t" in line]


def capture_ios_final_state(
    *,
    udid: str,
    task_id: str,
    task_file: Any,
    model_output_dir: Any,
    run_index: int,
    model: Optional[str] = None,
    success: Optional[bool] = None,
    return_code: Optional[int] = None,
) -> Dict[str, Any]:
    """Archive post-run app/native state for later FAIL audits. Never raises.

    Stages (read-only) the task app data container resolved via
    ``simctl get_app_container``, the relevant native Contacts/Calendar/Photos
    SQLite files, and a simulator screenshot into
    ``<model_output_dir>/final_state``. Writes one gzip tar archive plus a
    manifest JSON listing archive contents, SHA256 digests, task/UDID
    metadata, and per-step errors. Never deletes pre-existing evidence and
    never reports PASS/FAIL itself.
    """
    manifest: Dict[str, Any] = {
        "task_id": str(task_id),
        "task_file": str(task_file),
        "udid": str(udid),
        "run_index": int(run_index),
        "model": str(model) if model is not None else None,
        "bundle_id": None,
        "child_success": success,
        "child_return_code": return_code,
        "archive": None,
        "archive_sha256": None,
        "archive_size": None,
        "archive_members": [],
        "screenshot": None,
        "files": [],
        "skipped": [],
        "photo_library_listing": [],
        "errors": [],
    }
    final_state_dir = Path(model_output_dir) / IOS_FINAL_STATE_DIRNAME
    errors: List[str] = manifest["errors"]
    files: List[Dict[str, Any]] = manifest["files"]
    skipped: List[Dict[str, Any]] = manifest["skipped"]
    budget_bytes = [0]
    try:
        final_state_dir.mkdir(parents=True, exist_ok=True)
        staging = final_state_dir / "_staging"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)

        bundle_id = resolve_ios_task_bundle_id(task_file)
        manifest["bundle_id"] = bundle_id

        if bundle_id:
            try:
                from platforms.ios.runtime_env import simulator_manager as sim_mgr

                container = Path(
                    sim_mgr.get_app_data_container_path(str(udid), bundle_id)
                ).expanduser()
                if container.is_dir():
                    for src in sorted(container.rglob("*")):
                        if src.is_file() and not src.is_symlink():
                            rel = src.relative_to(container).as_posix()
                            if rel.startswith(("Library/Caches/", "tmp/")):
                                continue
                            _stage_file_for_capture(
                                src=src,
                                arc_rel=f"app_container/{rel}",
                                staging_root=staging,
                                files=files,
                                skipped=skipped,
                                errors=errors,
                                budget_bytes=budget_bytes,
                            )
                else:
                    errors.append(
                        f"app_container: container is not a directory: {container}"
                    )
            except Exception as exc:
                errors.append(f"app_container: {exc}")
        else:
            skipped.append({"path": "app_container", "reason": "no-bundle-id"})

        # Cross-app task state and App Groups are authoritative for DeltaChat,
        # FSNotes and Reminders; their databases need not be in the main container.
        related_bundles = {bundle_id} if bundle_id else set()
        try:
            import yaml
            raw_task = yaml.safe_load(Path(task_file).read_text()) or {}
            params = (raw_task.get("evaluation") or {}).get("params") or {}
            related_bundles.update(str(v) for k, v in params.items()
                                   if k.endswith("bundle_id") and v)
        except Exception as exc:
            errors.append(f"related_bundles: {exc}")
        for related in sorted(related_bundles):
            try:
                roots = _ios_shared_group_paths(str(udid), related)
                if related != bundle_id:
                    from platforms.ios.runtime_env import simulator_manager as sim_mgr
                    roots.append(("companion", Path(sim_mgr.get_app_data_container_path(str(udid), related))))
                for group, folder in roots:
                    for src in sorted(folder.rglob("*")):
                        if src.is_file() and not src.is_symlink():
                            rel = src.relative_to(folder).as_posix()
                            if rel.startswith(("Library/Caches/", "tmp/")):
                                continue
                            _stage_file_for_capture(src=src,
                                arc_rel=f"related/{related}/{group}/{rel}",
                                staging_root=staging, files=files, skipped=skipped,
                                errors=errors, budget_bytes=budget_bytes)
            except Exception as exc:
                errors.append(f"related_state:{related}: {exc}")

        try:
            data_dir = _ios_device_data_dir(str(udid))
            wanted = _native_ios_state_relpaths(bundle_id=bundle_id, task_id=task_id)
            for _label, relpaths in wanted.items():
                for rel in relpaths:
                    _stage_file_for_capture(
                        src=data_dir / rel,
                        arc_rel=f"native/{rel}",
                        staging_root=staging,
                        files=files,
                        skipped=skipped,
                        errors=errors,
                        budget_bytes=budget_bytes,
                    )
            if "photos" in wanted:
                dcim = data_dir / "Media" / "DCIM"
                listing: List[Dict[str, Any]] = []
                try:
                    if dcim.is_dir():
                        for item in sorted(dcim.rglob("*")):
                            if item.is_file():
                                try:
                                    listing.append(
                                        {
                                            "path": item.relative_to(dcim).as_posix(),
                                            "size": item.stat().st_size,
                                        }
                                    )
                                except Exception as exc:
                                    errors.append(f"photo_library_listing: {exc}")
                except Exception as exc:
                    errors.append(f"photo_library_listing: {exc}")
                manifest["photo_library_listing"] = listing
        except Exception as exc:
            errors.append(f"native_state: {exc}")

        screenshot_path = final_state_dir / IOS_FINAL_STATE_SCREENSHOT_NAME
        try:
            from platforms.ios.runtime_env import simulator_manager as sim_mgr

            sim_mgr.take_screenshot(str(udid), screenshot_path)
            if screenshot_path.is_file():
                manifest["screenshot"] = {
                    "path": IOS_FINAL_STATE_SCREENSHOT_NAME,
                    "size": screenshot_path.stat().st_size,
                    "sha256": _sha256_of_file(screenshot_path),
                }
            else:
                errors.append("screenshot: simctl reported success but file is missing")
        except Exception as exc:
            errors.append(f"screenshot: {exc}")

        archive_path = final_state_dir / IOS_FINAL_STATE_ARCHIVE_NAME
        try:
            members: List[str] = []
            with tarfile.open(archive_path, "w:gz") as tar:
                for src in sorted(staging.rglob("*")):
                    if src.is_file():
                        arcname = src.relative_to(staging).as_posix()
                        tar.add(str(src), arcname=arcname)
                        members.append(arcname)
            manifest["archive"] = IOS_FINAL_STATE_ARCHIVE_NAME
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
            (final_state_dir / IOS_FINAL_STATE_MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
        except Exception:
            pass
    return manifest


class IOSBenchmarkRunner(BaseBenchmarkRunner):
    def __init__(self) -> None:
        super().__init__(logger)

    @staticmethod
    def _build_clone_name(run_index: int, model: str, task_id: str) -> str:
        timestamp_ms = int(time.time() * 1000)
        safe_model = BaseBenchmarkRunner.safe_name(model)
        safe_task = BaseBenchmarkRunner.safe_name(task_id)
        return f"{run_index:04d}_{safe_model}_{safe_task}_{timestamp_ms}"

    @staticmethod
    def _make_run_record(
        *,
        run_index,
        model,
        task_id,
        task_file,
        args,
        success=False,
        return_code=None,
        duration_seconds=0.0,
        reset_ok=True,
        reset_error=None,
        trajectory_path=None,
        result_path=None,
        artifact_dir=None,
        runner_log_path=None,
        run_udid=None,
        clone_udid=None,
        clone_kept=False,
        cleanup_error=None,
        final_state=None,
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
            "run_udid": run_udid,
            "clone_udid": clone_udid,
            "clone_kept": clone_kept,
            "cleanup_error": cleanup_error,
            "final_state": final_state,
        }

    @staticmethod
    def _run_reset(
        args,
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Reset environment before one benchmark run.

        Returns:
            (ok, error, run_udid, ephemeral_udid)
            - run_udid: udid for the child run
            - ephemeral_udid: temporary cloned simulator udid, caller should cleanup
        """
        run_index = context.get("run_index", "?")
        reset_label = f"[Run {run_index}][reset]"
        reset_start = time.time()

        clone_source_udid = context.get("clone_source_udid") or args.clone_source_udid
        if not clone_source_udid:
            return False, "--clone-source-udid is required", None, None
        if not simctl_udid_exists(clone_source_udid):
            return False, f"Clone source UDID not found: {clone_source_udid}", None, None

        source_shutdown_start = time.time()
        logger.info(
            "%s source shutdown wait start (timeout=%.1fs, source=%s)",
            reset_label,
            BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS,
            clone_source_udid,
        )
        if not shutdown_simulator_and_wait(
            clone_source_udid,
            timeout_seconds=BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS,
        ):
            return (
                False,
                (
                    f"Source simulator did not reach Shutdown state before clone "
                    f"(udid={clone_source_udid})"
                ),
                None,
                None,
            )
        logger.info(
            "%s source shutdown wait done (%.1fs)",
            reset_label,
            time.time() - source_shutdown_start,
        )

        clone_name = context.get("clone_name") or f"{run_index:04d}_{int(time.time() * 1000)}"
        clone_udid: Optional[str] = None
        last_error: Optional[Exception] = None
        for attempt in range(1, BENCHMARK_CLONE_MAX_ATTEMPTS + 1):
            attempt_start = time.time()
            logger.info(
                "%s clone attempt %d/%d start (name=%s)",
                reset_label,
                attempt,
                BENCHMARK_CLONE_MAX_ATTEMPTS,
                clone_name,
            )
            try:
                clone_create_start = time.time()
                clone_udid = clone_simulator(clone_source_udid, clone_name)
                logger.info(
                    "%s clone created (udid=%s, %.1fs)",
                    reset_label,
                    clone_udid,
                    time.time() - clone_create_start,
                )

                clone_shutdown_start = time.time()
                logger.info(
                    "%s clone shutdown wait start (udid=%s, timeout=10.0s)",
                    reset_label,
                    clone_udid,
                )
                shutdown_simulator_and_wait(clone_udid, timeout_seconds=10.0)
                logger.info(
                    "%s clone shutdown wait done (%.1fs)",
                    reset_label,
                    time.time() - clone_shutdown_start,
                )

                boot_start = time.time()
                logger.info("%s boot start (udid=%s)", reset_label, clone_udid)
                boot_simulator(clone_udid)
                logger.info(
                    "%s boot ready (%.1fs)",
                    reset_label,
                    time.time() - boot_start,
                )
                logger.info(
                    "%s clone attempt %d/%d done (%.1fs)",
                    reset_label,
                    attempt,
                    BENCHMARK_CLONE_MAX_ATTEMPTS,
                    time.time() - attempt_start,
                )
                last_error = None
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    "[Run %s] clone/reset attempt %d/%d failed: %s",
                    run_index,
                    attempt,
                    BENCHMARK_CLONE_MAX_ATTEMPTS,
                    e,
                )

                orphan_udid = clone_udid or find_simulator_udid_by_name(clone_name)
                if orphan_udid:
                    try:
                        shutdown_simulator(orphan_udid)
                    except Exception:
                        pass
                    try:
                        delete_simulator(orphan_udid)
                    except Exception:
                        pass
                    clone_udid = None

                if attempt < BENCHMARK_CLONE_MAX_ATTEMPTS:
                    logger.info(
                        "%s retrying after %.1fs",
                        reset_label,
                        BENCHMARK_CLONE_RETRY_WAIT_SECONDS,
                    )
                    time.sleep(BENCHMARK_CLONE_RETRY_WAIT_SECONDS)
                    logger.info(
                        "%s source shutdown wait before retry (timeout=%.1fs, source=%s)",
                        reset_label,
                        BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS,
                        clone_source_udid,
                    )
                    shutdown_simulator_and_wait(
                        clone_source_udid,
                        timeout_seconds=BENCHMARK_SOURCE_SHUTDOWN_WAIT_SECONDS,
                    )

        if last_error is not None:
            return (
                False,
                (
                    f"simctl clone/reset failed after {BENCHMARK_CLONE_MAX_ATTEMPTS} attempts "
                    f"(source={clone_source_udid}, name={clone_name}): {last_error}"
                ),
                clone_udid,
                clone_udid,
            )

        if BENCHMARK_POST_RESET_WAIT_SECONDS > 0:
            logger.info(
                "%s settle wait start (%.1fs)",
                reset_label,
                BENCHMARK_POST_RESET_WAIT_SECONDS,
            )
            time.sleep(BENCHMARK_POST_RESET_WAIT_SECONDS)
            logger.info("%s settle wait done", reset_label)

        logger.info("%s completed (%.1fs)", reset_label, time.time() - reset_start)

        return True, None, clone_udid, clone_udid

    @staticmethod
    def _cleanup_ephemeral_simulator(udid: str) -> Tuple[bool, Optional[str]]:
        if not udid:
            return True, None

        try:
            shutdown_simulator(udid)
        except Exception:
            pass

        try:
            delete_simulator(udid)
            return True, None
        except Exception as e:
            return False, f"simctl delete failed for {udid}: {e}"

    def _validate_and_get_models(self, args: Any) -> List[str]:
        if str(args.action_mode).strip() != "code_adapter":
            raise ValueError("--action-mode must be code_adapter")
        direct_udid = str(getattr(args, "direct_udid", "") or "").strip()
        clone_source_udid = str(getattr(args, "clone_source_udid", "") or "").strip()
        if bool(direct_udid) == bool(clone_source_udid):
            raise ValueError("provide exactly one of --direct-udid or --clone-source-udid")
        if direct_udid:
            state = get_simulator_state(direct_udid)
            if state != "Booted":
                raise ValueError(f"--direct-udid must already be Booted; {direct_udid} is {state}")
        if not str(args.appium_host).strip():
            raise ValueError("--appium-host must be a non-empty string")
        if int(args.appium_port) <= 0:
            raise ValueError("--appium-port must be a positive integer")

        raw_models = self.parse_csv_list(args.models)
        if not raw_models:
            raise ValueError("--models cannot be empty")
        return list(dict.fromkeys(raw_models))

    def _load_task_descriptor(self, args: Any) -> Dict[str, Any]:
        from platforms.ios.core.types import load_task_from_file

        task_file = str(args.task_file)
        task = load_task_from_file(task_file)
        if not task.source_file:
            raise ValueError(f"Task file has no source path: {task_file}")
        return {
            "task_id": task.id,
            "task_goal": task.goal,
            "task_file": str(Path(task.source_file).resolve()),
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
                }
            )
        return jobs

    def _resolve_benchmark_name(self, args: Any) -> str:
        return self.safe_name(getattr(args, "benchmark_name", None) or "benchmark")

    def _prepare_benchmark_dirs(
        self,
        *,
        args: Any,
        benchmark_name: str,
        timestamp: str,
    ) -> Tuple[Path, Path, Path]:
        benchmark_dir = Path(args.output_root) / f"{benchmark_name}_{timestamp}"
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
        logger.info("Benchmark Dir: %s", benchmark_dir)
        logger.info("Task: %s, Models: %s", task["task_id"], models)
        direct_udid = str(getattr(args, "direct_udid", "") or "").strip()
        if direct_udid:
            logger.info("Direct Simulator UDID: %s", direct_udid)
        else:
            logger.info("Clone Source UDID: %s", args.clone_source_udid)
        logger.info("Appium Host: %s", str(args.appium_host).strip())
        logger.info("Appium Port: %d", int(args.appium_port))
        simulator_line = (
            f"# Direct simulator udid: {direct_udid}\n"
            if direct_udid
            else f"# Clone source udid: {args.clone_source_udid}\n"
        )
        self.append_runner_log(
            runner_log_path,
            (
                f"# Benchmark: {benchmark_name}\n"
                f"# Created: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
                f"# Task count: 1\n"
                f"# Task id: {task['task_id']}\n"
                f"# Models: {','.join(models)}\n"
                + simulator_line
                + f"# Appium host: {str(args.appium_host).strip()}\n"
                f"# Appium port: {int(args.appium_port)}\n"
            ),
        )

    def _resolve_cli_entry_path(self) -> str:
        return str(IOS_PLATFORM_DIR / "cli.py")

    def _maybe_capture_ios_final_state(
        self,
        *,
        udid: str,
        task_id: str,
        task_file: str,
        model_output_dir: Path,
        run_index: int,
        model: Optional[str] = None,
        success: Optional[bool] = None,
        return_code: Optional[int] = None,
        runner_log_path: Optional[Path] = None,
    ) -> Optional[Dict[str, Any]]:
        """Opt-in post-run state archive. Returns manifest dict or None.

        Returns None when the ``OS_OMNI_CAPTURE_IOS_FINAL_STATE=1`` flag is
        unset or no device UDID is available. Never raises and never alters
        the run's PASS/FAIL outcome; per-step failures are recorded in the
        manifest and runner log only.
        """
        if not ios_final_state_capture_enabled():
            return None
        if not str(udid or "").strip():
            return None
        try:
            manifest = capture_ios_final_state(
                udid=str(udid),
                task_id=task_id,
                task_file=task_file,
                model_output_dir=model_output_dir,
                run_index=run_index,
                model=model,
                success=success,
                return_code=return_code,
            )
        except Exception as exc:
            manifest = {
                "task_id": str(task_id),
                "udid": str(udid),
                "run_index": int(run_index),
                "errors": [f"capture: {exc}"],
            }
        # Host mail is not part of the simulator archive. Preserve its raw
        # MIME records before any subsequent initializer purges the service.
        # This administrative evidence is never supplied to the model.
        try:
            from core.evidence.local_mail import capture_task_local_mail_evidence

            mail_manifest = capture_task_local_mail_evidence(
                task_file=task_file, output_dir=model_output_dir
            )
            if mail_manifest is not None:
                manifest["local_mail_evidence"] = mail_manifest
        except Exception as mail_exc:
            manifest["local_mail_evidence"] = {
                "errors": [type(mail_exc).__name__],
                "for_decision_system": False,
            }
        if runner_log_path is not None:
            try:
                self.append_runner_log(
                    runner_log_path,
                    (
                        f"[Run {run_index}] final_state "
                        f"dir={Path(model_output_dir) / IOS_FINAL_STATE_DIRNAME} "
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
        model_count = len(self.parse_csv_list(args.models))
        model_output_dir = self._resolve_run_output_dir(
            run_root,
            model=model,
            model_count=model_count,
        )
        model_output_dir.mkdir(parents=True, exist_ok=True)

        direct_udid = str(getattr(args, "direct_udid", "") or "").strip()
        clone_name = self._build_clone_name(run_index, model, task_id)
        context = {
            "model": model,
            "task_id": task_id,
            "task_file": task_file,
            "run_index": run_index,
            "clone_source_udid": args.clone_source_udid,
            "clone_name": clone_name,
        }

        print("\n" + "=" * 72)
        logger.info("[Run %d] model=%s task=%s", run_index, model, task_id)
        print("=" * 72)
        self.append_runner_log(
            runner_log_path,
            (
                f"\n[Run {run_index}] model={model} task={task_id}\n"
                f"[Run {run_index}] task_file={task_file}"
            ),
        )

        ephemeral_udid: Optional[str] = None
        run_udid: Optional[str] = None
        child_started = False
        cleanup_error: Optional[str] = None
        record: Optional[Dict[str, Any]] = None
        try:
            if direct_udid:
                state = get_simulator_state(direct_udid)
                reset_ok = state == "Booted"
                reset_error = None if reset_ok else f"direct simulator is not Booted: {state}"
                run_udid = direct_udid if reset_ok else None
                ephemeral_udid = None
            else:
                reset_ok, reset_error, run_udid, ephemeral_udid = self._run_reset(args, context)
            if not reset_ok:
                logger.error("[Run %d] reset failed: %s", run_index, reset_error)
                self.append_runner_log(
                    runner_log_path,
                    f"[Run {run_index}] reset_failed={reset_error}",
                )
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
                    run_udid=run_udid,
                    clone_udid=ephemeral_udid,
                )
                return record

            cmd = [
                sys.executable,
                cli_entry_path,
                INTERNAL_BENCHMARK_JOB_COMMAND,
                "--task-file",
                task_file,
                "--model",
                model,
                "--action-mode",
                args.action_mode,
                "--observation-mode",
                str(getattr(args, "observation_mode", "screenshot_and_a11y_tree")),
                "--history-window",
                str(int(getattr(args, "history_window", 5))),
                "--appium-host",
                str(args.appium_host).strip(),
                "--appium-port",
                str(args.appium_port),
            ]
            if getattr(args, "execution_file", None):
                cmd.extend(["--execution-file", str(args.execution_file)])
            if args.max_steps is not None:
                cmd.extend(["--max-steps", str(args.max_steps)])
            if args.timeout is not None:
                cmd.extend(["--timeout", str(args.timeout)])
            if run_udid:
                cmd.extend(["--udid", str(run_udid)])
            child_env = os.environ.copy()
            child_env["PYTHONPATH"] = _child_pythonpath(
                REPO_ROOT, child_env.get("PYTHONPATH")
            )
            child_env["IOSWORLD_OUTPUT_DIR"] = str(model_output_dir)
            if os.environ.get("OS_OMNI_DEEPSEEK_REQUEST_AUDIT"):
                child_env["OS_OMNI_DEEPSEEK_REQUEST_AUDIT"] = str(model_output_dir / "deepseek_request_audit.jsonl")

            logger.info("[Run %d] device=%s", run_index, run_udid or "default")
            self.append_runner_log(
                runner_log_path,
                f"[Run {run_index}] device={run_udid or 'default'}",
            )
            run_start = time.time()
            child_started = True
            return_code = self.run_command_streaming(
                cmd,
                runner_log_path,
                run_prefix=f"Run {run_index}",
                env=child_env,
                child_log_mode="print",
            )
            duration_seconds = time.time() - run_start

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
                run_udid=run_udid,
                clone_udid=ephemeral_udid,
            )
            return record
        finally:
            # Opt-in final-state capture runs after the child stops and BEFORE
            # clone cleanup, so the ephemeral simulator's app container and
            # native SQLite state still exist. Capture failures are recorded
            # in the manifest/runner log and never change the run outcome.
            final_state_info: Optional[Dict[str, Any]] = None
            if child_started and (run_udid or ephemeral_udid):
                try:
                    final_state_info = self._maybe_capture_ios_final_state(
                        udid=str(run_udid or ephemeral_udid),
                        task_id=task_id,
                        task_file=task_file,
                        model_output_dir=model_output_dir,
                        run_index=run_index,
                        model=model,
                        success=(
                            record.get("success")
                            if isinstance(record, dict)
                            else None
                        ),
                        return_code=(
                            record.get("return_code")
                            if isinstance(record, dict)
                            else None
                        ),
                        runner_log_path=runner_log_path,
                    )
                except Exception as capture_exc:
                    logger.warning(
                        "[Run %d] final-state capture warning: %s",
                        run_index,
                        capture_exc,
                    )
            if ephemeral_udid:
                _, cleanup_error = self._cleanup_ephemeral_simulator(ephemeral_udid)
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
        print("\n" + "=" * 72)
        print("BENCHMARK COMPLETE")
        if total_runs > 0:
            print(f"Runs: {total_runs}, Success: {total_success}, Rate: {total_success / total_runs:.1%}")
        else:
            print("Runs: 0")
        print(f"Runner Log: {runner_log_path}")
        print("=" * 72)


def run_benchmark_command(args) -> int:
    if not hasattr(args, "appium_host"):
        args = Namespace(**vars(args), appium_host="127.0.0.1")
    if not hasattr(args, "output_root"):
        args = Namespace(**vars(args), output_root=IOS_DEFAULT_BENCHMARK_DIR)
    return IOSBenchmarkRunner().run(args)


__all__ = [
    "IOS_DEFAULT_BENCHMARK_DIR",
    "run_benchmark_command",
]
