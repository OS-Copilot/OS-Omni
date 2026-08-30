#!/usr/bin/env python3
"""Migrate a VirtualBuddy macOS VM bundle into a Tart VM directory."""

from __future__ import annotations

import argparse
import base64
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VB_LIBRARY = Path.home() / "Library" / "Application Support" / "VirtualBuddy"
DEFAULT_TART_HOME = Path.home() / ".tart"


class MigrationError(RuntimeError):
    pass



def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["cp", "-c", str(src), str(dst)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return
    except Exception:
        shutil.copy2(src, dst)



def _build_tart_config(vb_bundle: Path) -> dict[str, Any]:
    config_plist_path = vb_bundle / ".vbdata" / "Config.plist"
    if not config_plist_path.exists():
        raise MigrationError(f"VirtualBuddy config missing: {config_plist_path}")

    config = plistlib.loads(config_plist_path.read_bytes())
    hardware = dict(config.get("hardware") or {})
    network_devices = list(hardware.get("networkDevices") or [])
    display_devices = list(hardware.get("displayDevices") or [])
    if not network_devices:
        raise MigrationError(f"VirtualBuddy config has no networkDevices: {config_plist_path}")
    if not display_devices:
        raise MigrationError(f"VirtualBuddy config has no displayDevices: {config_plist_path}")

    hardware_model_path = vb_bundle / "HardwareModel"
    machine_identifier_path = vb_bundle / "MachineIdentifier"
    if not hardware_model_path.exists():
        raise MigrationError(f"HardwareModel missing: {hardware_model_path}")
    if not machine_identifier_path.exists():
        raise MigrationError(f"MachineIdentifier missing: {machine_identifier_path}")

    display = display_devices[0]
    return {
        "version": 1,
        "os": "darwin",
        "arch": "arm64",
        "cpuCountMin": int(hardware.get("cpuCount") or 4),
        "cpuCount": int(hardware.get("cpuCount") or 4),
        "memorySizeMin": int(hardware.get("memorySize") or 8 * 1024 * 1024 * 1024),
        "memorySize": int(hardware.get("memorySize") or 8 * 1024 * 1024 * 1024),
        "macAddress": str(network_devices[0].get("macAddress") or "82:00:00:00:00:01"),
        "display": {
            "width": int(display.get("width") or 1920),
            "height": int(display.get("height") or 1080),
            "unit": "px",
        },
        "displayRefit": bool(display.get("automaticallyReconfiguresDisplay", False)),
        "diskFormat": "raw",
        "ecid": base64.b64encode(machine_identifier_path.read_bytes()).decode(),
        "hardwareModel": base64.b64encode(hardware_model_path.read_bytes()).decode(),
    }



def migrate_virtualbuddy_to_tart(
    *,
    source_bundle: Path,
    tart_home: Path,
    target_vm_name: str,
    overwrite: bool = False,
) -> Path:
    source_bundle = source_bundle.expanduser().resolve()
    tart_home = tart_home.expanduser().resolve()

    if not source_bundle.exists():
        raise MigrationError(f"VirtualBuddy VM bundle not found: {source_bundle}")

    disk_path = source_bundle / "Disk.img"
    nvram_path = source_bundle / "AuxiliaryStorage"
    if not disk_path.exists():
        raise MigrationError(f"VirtualBuddy disk missing: {disk_path}")
    if not nvram_path.exists():
        raise MigrationError(f"VirtualBuddy auxiliary storage missing: {nvram_path}")

    target_dir = tart_home / "vms" / target_vm_name
    if target_dir.exists():
        if not overwrite:
            raise MigrationError(f"Target Tart VM already exists: {target_dir}")
        shutil.rmtree(target_dir)

    target_dir.mkdir(parents=True, exist_ok=True)

    config = _build_tart_config(source_bundle)
    (target_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    _copy_file(disk_path, target_dir / "disk.img")
    _copy_file(nvram_path, target_dir / "nvram.bin")
    return target_dir



def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate a VirtualBuddy VM bundle into Tart storage.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-vm-name", help="VirtualBuddy VM name inside the default/current VirtualBuddy library.")
    source.add_argument("--source-bundle", help="Direct path to the .vbvm bundle.")
    parser.add_argument("--vb-library", default=str(DEFAULT_VB_LIBRARY), help="VirtualBuddy VM library path.")
    parser.add_argument("--tart-home", default=str(DEFAULT_TART_HOME), help="Destination TART_HOME path.")
    parser.add_argument("--target-vm-name", required=True, help="Destination Tart VM name.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing Tart VM with the same name.")
    return parser.parse_args(argv)



def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    vb_library = Path(args.vb_library)
    source_bundle = Path(args.source_bundle) if args.source_bundle else vb_library / f"{args.source_vm_name}.vbvm"

    try:
        target_dir = migrate_virtualbuddy_to_tart(
            source_bundle=source_bundle,
            tart_home=Path(args.tart_home),
            target_vm_name=str(args.target_vm_name).strip(),
            overwrite=bool(args.overwrite),
        )
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Migrated {source_bundle} -> {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
