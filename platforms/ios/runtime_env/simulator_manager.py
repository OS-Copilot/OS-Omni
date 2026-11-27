#!/usr/bin/env python3
"""
Shared iOS Simulator utilities based on `xcrun simctl`.
"""

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


_UDID_RE = re.compile(
    r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b"
)


def run_cmd(
    cmd: Sequence[str],
    *,
    check: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{detail}")
    return proc


def extract_first_udid(text: str) -> Optional[str]:
    m = _UDID_RE.search(text or "")
    return m.group(0) if m else None


def simctl_devices_json() -> Dict[str, Any]:
    proc = run_cmd(["xcrun", "simctl", "list", "devices", "--json"], timeout=120)
    return json.loads(proc.stdout)


def list_available_ios_simulators() -> List[Dict[str, str]]:
    payload = simctl_devices_json()
    devices_map = payload.get("devices", {})
    simulators: List[Dict[str, str]] = []

    for runtime, devices in devices_map.items():
        if "SimRuntime.iOS" not in runtime:
            continue
        for device in devices:
            if not device.get("isAvailable", True):
                continue
            simulators.append(
                {
                    "runtime": str(runtime),
                    "name": str(device.get("name", "")),
                    "udid": str(device.get("udid", "")),
                    "state": str(device.get("state", "")),
                }
            )
    return simulators


def resolve_simulator(udid: Optional[str], device_name: Optional[str]) -> Dict[str, str]:
    simulators = list_available_ios_simulators()
    if not simulators:
        raise RuntimeError("No available iOS simulators found. Check Xcode Simulator installation.")

    if udid:
        for sim in simulators:
            if sim["udid"] == udid:
                return sim
        raise RuntimeError(f"Simulator UDID not found or unavailable: {udid}")

    if device_name:
        for sim in simulators:
            if device_name.lower() in sim["name"].lower():
                return sim
        raise RuntimeError(f"No available simulator matches device name: {device_name}")

    for sim in simulators:
        if sim["state"] == "Booted":
            return sim

    return simulators[0]


def find_simulator_udid_by_name(device_name: str) -> Optional[str]:
    payload = simctl_devices_json()
    devices_map = payload.get("devices", {})
    for runtime, devices in devices_map.items():
        if "SimRuntime.iOS" not in runtime:
            continue
        for device in devices:
            if str(device.get("name", "")) == device_name and device.get("isAvailable", True):
                udid = str(device.get("udid", "")).strip()
                if udid:
                    return udid
    return None


def simctl_udid_exists(udid: str) -> bool:
    if not udid:
        return False
    payload = simctl_devices_json()
    devices_map = payload.get("devices", {})
    for devices in devices_map.values():
        for device in devices:
            if str(device.get("udid", "")).strip() == udid:
                return True
    return False


def get_simulator_state(udid: str) -> Optional[str]:
    """Return simulator state for UDID, or None when UDID is not found."""
    if not udid:
        return None
    payload = simctl_devices_json()
    devices_map = payload.get("devices", {})
    for devices in devices_map.values():
        for device in devices:
            if str(device.get("udid", "")).strip() == udid:
                return str(device.get("state", "")).strip() or None
    return None


def wait_for_simulator_state(
    udid: str,
    desired_state: str,
    *,
    timeout_seconds: float = 20.0,
    poll_interval_seconds: float = 0.5,
) -> bool:
    """Poll simctl until simulator reaches desired state, or timeout."""
    desired = str(desired_state).strip().lower()
    deadline = time.time() + float(timeout_seconds)
    while time.time() < deadline:
        state = get_simulator_state(udid)
        if state and state.lower() == desired:
            return True
        time.sleep(float(poll_interval_seconds))
    return False


def shutdown_simulator_and_wait(
    udid: str,
    *,
    timeout_seconds: float = 20.0,
    poll_interval_seconds: float = 0.5,
) -> bool:
    """Shutdown simulator and wait until state becomes Shutdown."""
    shutdown_simulator(udid)
    return wait_for_simulator_state(
        udid,
        "Shutdown",
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


def clone_simulator(source_udid: str, clone_name: str) -> str:
    proc = run_cmd(
        ["xcrun", "simctl", "clone", source_udid, clone_name],
        check=True,
        timeout=240,
    )
    udid = (
        extract_first_udid(proc.stdout)
        or extract_first_udid(proc.stderr)
        or find_simulator_udid_by_name(clone_name)
    )
    if udid:
        return udid
    raise RuntimeError(f"Clone created but UDID cannot be resolved for clone name: {clone_name}")


def shutdown_simulator(udid: str):
    run_cmd(["xcrun", "simctl", "shutdown", udid], check=False, timeout=120)


def erase_simulator(udid: str):
    run_cmd(["xcrun", "simctl", "erase", udid], check=True, timeout=180)


def boot_simulator(udid: str):
    run_cmd(["xcrun", "simctl", "boot", udid], check=False, timeout=120)
    run_cmd(["xcrun", "simctl", "bootstatus", udid, "-b"], check=True, timeout=240)


def delete_simulator(udid: str):
    run_cmd(["xcrun", "simctl", "delete", udid], check=False, timeout=120)


def open_simulator_app(udid: str):
    run_cmd(["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", udid], check=False, timeout=30)


def get_app_data_container_path(udid: str, bundle_id: str) -> str:
    return str(get_app_container_path(udid, bundle_id, "data"))


def get_app_container_path(udid: str, bundle_id: str, kind: str = "data") -> Path:
    """Resolve an app container under the requested simulator's data root.

    On current CoreSimulator, ``simctl get_app_container`` can report the
    source simulator's host path when queried for an app installed in a clone.
    The cloned device still has an independent container with the same
    container UUID under its own device root. Rebase that stale host path to
    the requested UDID, and fail closed if the clone-local container is absent.
    """
    resolved_udid = str(udid or "").strip()
    if not resolved_udid:
        raise ValueError("Simulator UDID is required")

    resolved_bundle_id = str(bundle_id or "").strip()
    if not resolved_bundle_id:
        raise ValueError("App bundle_id is required")

    resolved_kind = str(kind or "").strip()
    if not resolved_kind:
        raise ValueError("App container kind is required")

    proc = run_cmd(
        ["xcrun", "simctl", "get_app_container", resolved_udid, resolved_bundle_id, resolved_kind],
        check=True,
        timeout=60,
    )
    raw_path = (proc.stdout or "").strip()
    if not raw_path:
        raise RuntimeError(
            f"simctl returned an empty {resolved_kind} container for {resolved_bundle_id}"
        )
    return remap_simulator_container_path(raw_path, resolved_udid)


def remap_simulator_container_path(container_path: str | Path, udid: str) -> Path:
    """Rebase a CoreSimulator container path to the active device, if needed."""
    resolved_udid = str(udid or "").strip()
    if not resolved_udid:
        raise ValueError("Simulator UDID is required")

    path = Path(container_path).expanduser()
    devices_root = (
        Path.home() / "Library" / "Developer" / "CoreSimulator" / "Devices"
    )
    try:
        relative = path.relative_to(devices_root)
    except ValueError:
        return path.resolve()

    if len(relative.parts) < 3 or relative.parts[1] != "data":
        return path.resolve()

    reported_udid = relative.parts[0]
    if reported_udid.lower() == resolved_udid.lower():
        return path.resolve()

    rebased = devices_root / resolved_udid / "data" / Path(*relative.parts[2:])
    if not rebased.exists():
        raise FileNotFoundError(
            "simctl returned an app container under a different simulator "
            f"({reported_udid}); the corresponding container is missing from "
            f"active simulator {resolved_udid}: {rebased}"
        )
    return rebased.resolve()


def launch_app(udid: str, bundle_id: str):
    run_cmd(["xcrun", "simctl", "launch", udid, bundle_id], check=True, timeout=60)


def terminate_app(udid: str, bundle_id: str):
    run_cmd(["xcrun", "simctl", "terminate", udid, bundle_id], check=False, timeout=60)


def take_screenshot(udid: str, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(["xcrun", "simctl", "io", udid, "screenshot", str(output_path)], check=True, timeout=60)
