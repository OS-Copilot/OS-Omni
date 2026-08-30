#!/usr/bin/env python3
"""
Android platform entrypoint.
Loads the execution YAML and runs each task × model on the Android emulator.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from platforms.android.host_env import android_tool_env  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

ANDROID_RUNTIME_CONFIG_PATH = repo_root / "configs" / "android.yaml"

logger = logging.getLogger(__name__)

_PACKAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "com.google.android.contacts": ("com.google.android.contacts", "com.android.contacts"),
    "com.android.contacts": ("com.android.contacts", "com.google.android.contacts"),
    "com.google.android.deskclock": ("com.google.android.deskclock", "com.android.deskclock"),
    "com.android.deskclock": ("com.android.deskclock", "com.google.android.deskclock"),
    "com.google.android.calculator": ("com.google.android.calculator", "com.android.calculator2", "org.fossify.math"),
    "com.android.calculator2": ("com.android.calculator2", "com.google.android.calculator", "org.fossify.math"),
    "org.fossify.math": ("org.fossify.math", "com.android.calculator2", "com.google.android.calculator"),
}
_APP_NAME_PACKAGE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "calculator": ("org.fossify.math", "com.android.calculator2", "com.google.android.calculator"),
    "clock": ("com.google.android.deskclock", "com.android.deskclock"),
    "contacts": ("com.google.android.contacts", "com.android.contacts"),
    "libreoffice": ("org.documentfoundation.libreoffice",),
    "markor": ("net.gsantner.markor",),
    "settings": ("com.android.settings",),
}


def _safe_name(raw: str) -> str:
    text = (raw or "").strip() or "unnamed"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text)


def _normalize_action_mode(action_mode_raw: str | None) -> str:
    if not action_mode_raw:
        return "code_adapter"
    normalized = action_mode_raw.strip().lower()
    if normalized != "code_adapter":
        raise ValueError(
            "execution.action_mode only supports code_adapter for Android."
        )
    return normalized


def _normalize_observation_mode(observation_mode_raw: str | None) -> str:
    if not observation_mode_raw:
        return "screenshot_and_a11y_tree"
    normalized = observation_mode_raw.strip().lower()
    valid = {"screenshot_only", "a11y_tree_only", "screenshot_and_a11y_tree"}
    if normalized not in valid:
        raise ValueError(
            "execution.observation_mode only supports screenshot_only/a11y_tree_only/screenshot_and_a11y_tree."
        )
    return normalized


def _normalize_history_window(history_window_raw: object) -> int:
    if history_window_raw is None:
        return 5
    if isinstance(history_window_raw, bool) or not isinstance(history_window_raw, int) or history_window_raw <= 0:
        raise ValueError("execution.history_window must be a positive integer for Android.")
    return int(history_window_raw)


def _android_tool_env() -> dict[str, str]:
    return android_tool_env(apply_to_process=True)


def _resolve_android_tool(tool_name: str) -> str | None:
    found = shutil.which(tool_name)
    if found:
        return found

    env = _android_tool_env()
    sdk_root = env.get("ANDROID_HOME") or env.get("ANDROID_SDK_ROOT")
    sdk_roots = [Path(sdk_root)] if sdk_root else []
    userprofile = env.get("USERPROFILE")
    if userprofile:
        sdk_roots.append(Path(userprofile) / ".helloworld-android" / "Sdk")

    for root in sdk_roots:
        if tool_name == "adb":
            candidate = root / "platform-tools" / "adb.exe"
        elif tool_name == "emulator":
            candidate = root / "emulator" / "emulator.exe"
        else:
            return None
        if candidate.exists():
            return str(candidate)
    return None


def _ensure_emulator_running(config) -> None:
    """Check if emulator is running; if not and auto_launch is on, start it."""
    tool_env = _android_tool_env()
    adb_path = _resolve_android_tool("adb") or "adb"

    # Check connected devices
    result = subprocess.run(
        [adb_path, "devices"],
        capture_output=True, text=True, timeout=10, env=tool_env,
    )
    lines = [line for line in result.stdout.strip().splitlines()[1:] if line.strip()]

    device_connected = any(
        config.adb_device in line or "device" in line
        for line in lines
    )

    if device_connected:
        logger.info("Device '%s' is connected.", config.adb_device)
        return

    if not config.auto_launch_emulator:
        raise RuntimeError(
            f"No device '{config.adb_device}' connected and auto_launch_emulator is disabled."
        )

    # Try to launch the emulator
    emulator_path = _resolve_android_tool("emulator")
    if not emulator_path:
        raise RuntimeError(
            "Cannot find 'emulator' in PATH. Make sure Android SDK is installed."
        )

    list_result = subprocess.run(
        [emulator_path, "-list-avds"],
        capture_output=True,
        text=True,
        timeout=10,
        env=tool_env,
    )
    avd_names = {line.strip() for line in list_result.stdout.splitlines() if line.strip()}
    if config.avd_name not in avd_names:
        raise RuntimeError(
            f"Cannot find AVD '{config.avd_name}'. "
            f"Visible AVDs: {sorted(avd_names) or 'none'}. "
            "Check configs/android.yaml or ANDROID_AVD_HOME."
        )

    logger.info("Launching emulator AVD '%s'...", config.avd_name)
    subprocess.Popen(
        [emulator_path, "-avd", config.avd_name, "-no-snapshot-load", "-no-snapshot-save"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=tool_env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    # Wait for device to boot
    logger.info("Waiting for emulator to boot (timeout: %ds)...", config.emulator_boot_timeout)
    start = time.time()
    while time.time() - start < config.emulator_boot_timeout:
        result = subprocess.run(
            [adb_path, "-s", config.adb_device, "get-state"],
            capture_output=True, text=True, timeout=10, env=tool_env,
        )
        if "device" in result.stdout:
            # Wait for boot animation to finish
            boot_result = subprocess.run(
                [adb_path, "-s", config.adb_device, "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True, timeout=10, env=tool_env,
            )
            if "1" in boot_result.stdout:
                logger.info("Emulator booted successfully.")
                return
        time.sleep(2)

    raise RuntimeError(f"Emulator failed to boot within {config.emulator_boot_timeout}s.")


def reset_android_emulator_snapshot(config, *, reason: str = "task") -> None:
    """Restore the configured AVD snapshot before a task run."""
    if not bool(getattr(config, "emulator_reset_between_tasks", False)):
        return
    snapshot_name = str(getattr(config, "emulator_snapshot_name", "") or "").strip()
    if not snapshot_name:
        raise RuntimeError(
            "Android emulator_reset_between_tasks is true but emulator_snapshot_name is empty."
        )

    _ensure_emulator_running(config)
    tool_env = _android_tool_env()
    adb_path = _resolve_android_tool("adb") or "adb"

    logger.info(
        "Restoring Android emulator snapshot '%s' before %s on %s...",
        snapshot_name,
        reason,
        config.adb_device,
    )
    result = subprocess.run(
        [adb_path, "-s", config.adb_device, "emu", "avd", "snapshot", "load", snapshot_name],
        capture_output=True,
        text=True,
        timeout=max(30, int(getattr(config, "emulator_boot_timeout", 120))),
        env=tool_env,
    )
    combined_output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode != 0 or "KO:" in combined_output:
        raise RuntimeError(
            f"Failed to restore Android emulator snapshot '{snapshot_name}' "
            f"for {config.adb_device}: returncode={result.returncode}, output={combined_output!r}"
        )

    _wait_for_android_boot(config, adb_path=adb_path, tool_env=tool_env)


def _wait_for_android_boot(config, *, adb_path: str, tool_env: dict[str, str]) -> None:
    start = time.time()
    timeout_seconds = int(getattr(config, "emulator_boot_timeout", 120))
    while time.time() - start < timeout_seconds:
        state = subprocess.run(
            [adb_path, "-s", config.adb_device, "get-state"],
            capture_output=True,
            text=True,
            timeout=10,
            env=tool_env,
        )
        if "device" in state.stdout:
            boot = subprocess.run(
                [adb_path, "-s", config.adb_device, "shell", "getprop", "sys.boot_completed"],
                capture_output=True,
                text=True,
                timeout=10,
                env=tool_env,
            )
            if "1" in boot.stdout:
                subprocess.run(
                    [adb_path, "-s", config.adb_device, "shell", "input", "keyevent", "KEYCODE_WAKEUP"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    env=tool_env,
                )
                subprocess.run(
                    [adb_path, "-s", config.adb_device, "shell", "wm", "dismiss-keyguard"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    env=tool_env,
                )
                logger.info("Android emulator is ready after snapshot restore.")
                return
        time.sleep(2)
    raise RuntimeError(
        f"Android emulator did not become ready within {timeout_seconds}s after snapshot restore."
    )


def _resolve_task_label(task_path: Path) -> str:
    with task_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"Task file is missing task_id: {task_path}")
    return task_id.strip()


def _load_task_payload(task_path: Path) -> dict[str, object]:
    with task_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Task payload must be an object: {task_path}")
    return payload


def _expand_package_candidates(package_name: str) -> tuple[str, ...]:
    package = str(package_name or "").strip()
    if not package:
        return ()
    return _PACKAGE_ALIASES.get(package, (package,))


def _append_requirement_group(
    groups: list[tuple[str, ...]],
    seen: set[tuple[str, ...]],
    raw_group: list[str] | tuple[str, ...],
) -> None:
    normalized: list[str] = []
    for item in raw_group:
        package = str(item or "").strip()
        if not package or package in normalized:
            continue
        normalized.append(package)
    if not normalized:
        return
    key = tuple(normalized)
    if key in seen:
        return
    seen.add(key)
    groups.append(key)


def _extract_required_package_groups(task_path: Path) -> list[tuple[str, ...]]:
    payload = _load_task_payload(task_path)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    init = payload.get("init") if isinstance(payload.get("init"), dict) else {}
    params = init.get("params") if isinstance(init.get("params"), dict) else {}
    initializer_id = str(init.get("initializer_id") or "").strip()

    groups: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()

    raw_any = metadata.get("required_packages_any")
    if isinstance(raw_any, list):
        for item in raw_any:
            if isinstance(item, list):
                _append_requirement_group(groups, seen, tuple(str(x).strip() for x in item if str(x).strip()))
            else:
                package = str(item or "").strip()
                if package:
                    _append_requirement_group(groups, seen, _expand_package_candidates(package))

    if initializer_id == "initializers.android.open_app:OpenAppInitializer":
        try:
            from initializers.android.open_app import _APP_LAUNCH_MAP
        except Exception:
            _APP_LAUNCH_MAP = {}
        app_name = str(params.get("app_name") or "").strip().lower()
        candidates = _APP_LAUNCH_MAP.get(app_name, []) if isinstance(_APP_LAUNCH_MAP, dict) else []
        if isinstance(candidates, list) and candidates:
            _append_requirement_group(
                groups,
                seen,
                tuple(
                    str(candidate.get("package") or "").strip()
                    for candidate in candidates
                    if isinstance(candidate, dict) and str(candidate.get("package") or "").strip()
                ),
            )

    app_name = str(params.get("app_name") or "").strip().lower()
    if app_name and app_name in _APP_NAME_PACKAGE_REQUIREMENTS:
        _append_requirement_group(groups, seen, _APP_NAME_PACKAGE_REQUIREMENTS[app_name])

    for key, value in params.items():
        if not str(key).endswith("_package"):
            continue
        package = str(value or "").strip()
        if not package:
            continue
        _append_requirement_group(groups, seen, _expand_package_candidates(package))

    app_bundle_id = str(metadata.get("app_bundle_id") or "").strip()
    if app_bundle_id and "+" not in app_bundle_id and "," not in app_bundle_id and " " not in app_bundle_id:
        _append_requirement_group(groups, seen, _expand_package_candidates(app_bundle_id))

    return groups


def _query_installed_packages(adb_path: str, adb_device: str, *, tool_env: dict[str, str]) -> set[str]:
    result = subprocess.run(
        [adb_path, "-s", adb_device, "shell", "pm", "list", "packages"],
        capture_output=True,
        text=True,
        timeout=20,
        env=tool_env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to query installed Android packages for {adb_device}: "
            f"returncode={result.returncode}, stderr={result.stderr.strip()!r}"
        )
    packages: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("package:"):
            line = line.split("package:", 1)[1].strip()
        packages.add(line)
    return packages


def _preflight_filter_task_paths(
    task_paths: list[Path],
    *,
    adb_path: str,
    adb_device: str,
    tool_env: dict[str, str],
) -> tuple[list[Path], list[tuple[str, list[tuple[str, ...]]]]]:
    installed_packages = _query_installed_packages(adb_path, adb_device, tool_env=tool_env)
    runnable: list[Path] = []
    skipped: list[tuple[str, list[tuple[str, ...]]]] = []

    for task_path in task_paths:
        task_label = _resolve_task_label(task_path)
        requirements = _extract_required_package_groups(task_path)
        missing_groups = [group for group in requirements if not any(pkg in installed_packages for pkg in group)]
        if missing_groups:
            skipped.append((task_label, missing_groups))
            continue
        runnable.append(task_path)

    return runnable, skipped


def _run_execution_command(args: argparse.Namespace) -> int:
    from platforms.android.runtime_config import load_execution_handoff, load_android_runtime_config
    from platforms.android.runners.benchmark import run_benchmark

    execution = load_execution_handoff(args.execution)
    config = load_android_runtime_config(ANDROID_RUNTIME_CONFIG_PATH)

    action_mode = _normalize_action_mode(execution.get("action_mode"))
    observation_mode = _normalize_observation_mode(execution.get("observation_mode"))
    history_window = _normalize_history_window(execution.get("history_window"))
    model_ids = list(dict.fromkeys(execution.get("models", [])))
    if not model_ids:
        raise ValueError("execution.models cannot be empty for Android.")

    task_paths = execution.get("task_paths", [])
    execution_base_name = _safe_name(execution["source_path"].stem)
    execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("Execution: %s", execution["source_path"])
    logger.info("Tasks: %d, Models: %d", len(task_paths), len(model_ids))
    logger.info("Config: %s", ANDROID_RUNTIME_CONFIG_PATH)
    logger.info("ADB device: %s, AVD: %s", config.adb_device, config.avd_name)

    # Ensure emulator is running
    _ensure_emulator_running(config)

    tool_env = _android_tool_env()
    adb_path = _resolve_android_tool("adb") or "adb"
    task_paths, skipped_tasks = _preflight_filter_task_paths(
        task_paths,
        adb_path=adb_path,
        adb_device=config.adb_device,
        tool_env=tool_env,
    )
    for task_label, missing_groups in skipped_tasks:
        missing_text = ", ".join(
            "any of [" + ", ".join(group) + "]"
            for group in missing_groups
        )
        logger.warning(
            "Skipping task %s during Android preflight because required app packages are unavailable: %s",
            task_label,
            missing_text,
        )
    if skipped_tasks:
        logger.info(
            "Android preflight kept %d tasks and skipped %d task(s) on device %s.",
            len(task_paths),
            len(skipped_tasks),
            config.adb_device,
        )
    if not task_paths:
        logger.error("Android preflight skipped every task in %s; nothing remains to run.", execution["source_path"])
        return 1

    failed_tasks: list[str] = []
    for model_id in model_ids:
        results_root = repo_root / "results" / _safe_name(model_id) / "android"
        execution_run_dir = results_root / f"{execution_base_name}_{execution_timestamp}"
        execution_run_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Output dir for model %s: %s", model_id, execution_run_dir)

        dedupe_counter: dict[str, int] = {}
        for task_path in task_paths:
            task_label = _resolve_task_label(task_path)
            dedupe_counter[task_label] = dedupe_counter.get(task_label, 0) + 1
            suffix = dedupe_counter[task_label]
            run_name = task_label if suffix == 1 else f"{task_label}_{suffix}"
            run_dir = execution_run_dir / _safe_name(run_name)

            logger.info("Running: %s × %s", task_label, model_id)
            reset_android_emulator_snapshot(config, reason=task_label)
            exit_code = run_benchmark(
                task_path=task_path,
                model_id=model_id,
                adb_device=config.adb_device,
                run_dir=run_dir,
                action_mode=action_mode,
                observation_mode=observation_mode,
                history_window=history_window,
            )
            if exit_code != 0:
                failed_tasks.append(f"{model_id}:{task_label}")

    if failed_tasks:
        logger.error("Finished with failures: %s", ", ".join(failed_tasks))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Android execution runner.",
    )
    parser.add_argument("--execution", required=True, help="Path to execution YAML file.")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    try:
        return _run_execution_command(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
