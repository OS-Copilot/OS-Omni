#!/usr/bin/env python3
"""Retarget a VirtualBuddy VM install from one restore image to another."""

from __future__ import annotations

import argparse
import plistlib
from pathlib import Path
from typing import Any


def _load_plist(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"plist not found: {path}")
    with path.open("rb") as fh:
        payload = plistlib.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"plist must be a dictionary: {path}")
    return payload


def _write_plist(path: Path, payload: dict[str, Any]) -> None:
    with path.open("wb") as fh:
        plistlib.dump(payload, fh, sort_keys=False)


def retarget_virtualbuddy_restore(
    *,
    vm_bundle: Path,
    local_ipsw_path: Path,
    remote_ipsw_url: str,
    display_name: str,
    version: str,
    build: str,
    group: str,
    channel: str,
    mobile_device_min_version: str,
    download_size: int | None = None,
) -> tuple[Path, Path]:
    vbdata_dir = vm_bundle / ".vbdata"
    install_path = vbdata_dir / "Install.plist"
    metadata_path = vbdata_dir / "Metadata.plist"

    install_payload = _load_plist(install_path)
    metadata_payload = _load_plist(metadata_path)

    install_data = install_payload.setdefault("data", {})
    if not isinstance(install_data, dict):
        raise ValueError(f"Install.plist data must be a dictionary: {install_path}")

    install_method_selection = install_data.setdefault("installMethodSelection", {})
    if not isinstance(install_method_selection, dict):
        raise ValueError("Install.plist data.installMethodSelection must be a dictionary")

    remote_options = install_method_selection.setdefault("remoteOptions", {})
    if not isinstance(remote_options, dict):
        raise ValueError("Install.plist data.installMethodSelection.remoteOptions must be a dictionary")

    option = {
        "build": build,
        "channel": channel,
        "group": group,
        "id": build,
        "mobileDeviceMinVersion": mobile_device_min_version,
        "name": display_name,
        "requirements": "min_host_13",
        "url": {"relative": remote_ipsw_url},
        "version": version,
    }
    if download_size is not None:
        option["downloadSize"] = int(download_size)
    remote_options["_0"] = option

    local_url = local_ipsw_path.resolve().as_uri()
    install_data["localRestoreImageURL"] = {"relative": local_url}

    metadata_payload["installImageURL"] = {"relative": local_url}
    metadata_payload["remoteInstallImageURL"] = {"relative": remote_ipsw_url}

    _write_plist(install_path, install_payload)
    _write_plist(metadata_path, metadata_payload)
    return install_path, metadata_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retarget a VirtualBuddy VM install to a different restore image.",
    )
    parser.add_argument("--vm-bundle", required=True, help="Path to <name>.vbvm bundle")
    parser.add_argument("--local-ipsw-path", required=True, help="Path to the downloaded IPSW")
    parser.add_argument("--remote-ipsw-url", required=True, help="Original remote IPSW URL")
    parser.add_argument("--display-name", required=True, help="Release display name, e.g. macOS 15.2")
    parser.add_argument("--version", required=True, help="Release version, e.g. 15.2.0")
    parser.add_argument("--build", required=True, help="Build number, e.g. 24C101")
    parser.add_argument("--group", required=True, help="Catalog group, e.g. sequoia")
    parser.add_argument("--channel", default="regular", help="Catalog channel, default: regular")
    parser.add_argument(
        "--mobile-device-min-version",
        required=True,
        help="MobileDevice minimum version required by the IPSW catalog entry",
    )
    parser.add_argument(
        "--download-size",
        type=int,
        default=None,
        help="Optional download size in bytes for the catalog entry",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    install_path, metadata_path = retarget_virtualbuddy_restore(
        vm_bundle=Path(args.vm_bundle),
        local_ipsw_path=Path(args.local_ipsw_path),
        remote_ipsw_url=args.remote_ipsw_url,
        display_name=args.display_name,
        version=args.version,
        build=args.build,
        group=args.group,
        channel=args.channel,
        mobile_device_min_version=args.mobile_device_min_version,
        download_size=args.download_size,
    )
    print(f"Updated: {install_path}")
    print(f"Updated: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
