"""Helpers for purging local iOS app state while keeping benchmark accounts."""

from __future__ import annotations

import plistlib
import shutil
import sqlite3
import subprocess
from pathlib import Path


MAILY_BUNDLE_ID = "de.enough.maily"
DELTACHAT_BUNDLE_ID = "chat.delta"
DELTACHAT_APP_GROUP_ID = "group.chat.delta.ios"
MAILY_NEXT_UIDS_KEY = "flutter.nextUidsInfo"


def purge_local_state_for_bundle(
    *,
    bundle_id: str,
    udid: str | None,
    app_data_container_path: str | None = None,
) -> dict[str, object]:
    """Purge local UI-visible state for supported communication apps."""

    if not udid and not app_data_container_path:
        return {"applied": False, "reason": "missing_udid"}

    if bundle_id == MAILY_BUNDLE_ID:
        app_data_root = _resolve_app_data_container_root(
            udid=udid,
            bundle_id=bundle_id,
            app_data_container_path=app_data_container_path,
        )
        cleared_paths = purge_maily_local_state(app_data_root)
        return {
            "applied": True,
            "strategy": "maily_local_state",
            "cleared_paths": [str(path) for path in cleared_paths],
        }

    if bundle_id == DELTACHAT_BUNDLE_ID:
        app_data_root = _resolve_app_data_container_root(
            udid=udid,
            bundle_id=bundle_id,
            app_data_container_path=app_data_container_path,
        )
        shared_group_root = _find_shared_app_group_root(udid=udid, group_id=DELTACHAT_APP_GROUP_ID)
        result = purge_deltachat_local_state(
            app_data_root=app_data_root,
            shared_group_root=shared_group_root,
        )
        result["applied"] = True
        result["strategy"] = "deltachat_local_state"
        return result

    return {"applied": False, "reason": "unsupported_bundle"}


def purge_maily_local_state(app_data_root: Path) -> list[Path]:
    """Clear Maily's local sync/snapshot state while preserving configured accounts."""

    cleared_paths: list[Path] = []

    preferences_path = app_data_root / "Library" / "Preferences" / f"{MAILY_BUNDLE_ID}.plist"
    if preferences_path.exists():
        with preferences_path.open("rb") as handle:
            preferences = plistlib.load(handle)
        if MAILY_NEXT_UIDS_KEY in preferences:
            preferences.pop(MAILY_NEXT_UIDS_KEY, None)
            with preferences_path.open("wb") as handle:
                plistlib.dump(preferences, handle)
            cleared_paths.append(preferences_path)

    for relative_path in (
        Path("Library/Saved Application State") / f"{MAILY_BUNDLE_ID}.savedState",
        Path("Library/SplashBoard/Snapshots") / f"{MAILY_BUNDLE_ID} - {{DEFAULT GROUP}}",
        Path("Library/SplashBoard/Snapshots") / f"sceneID:{MAILY_BUNDLE_ID}-default",
        Path("Library/Caches") / MAILY_BUNDLE_ID,
        Path("Library/WebKit") / MAILY_BUNDLE_ID / "WebsiteData" / "LocalStorage",
        Path("Library/WebKit") / MAILY_BUNDLE_ID / "WebsiteData" / "IndexedDB",
        Path("Library/WebKit") / MAILY_BUNDLE_ID / "WebsiteData" / "SearchHistory",
        Path("tmp") / MAILY_BUNDLE_ID,
    ):
        target = app_data_root / relative_path
        if target.exists():
            _remove_path(target)
            cleared_paths.append(target)

    return cleared_paths


def purge_deltachat_local_state(
    *,
    app_data_root: Path,
    shared_group_root: Path,
) -> dict[str, object]:
    """Delete Delta Chat message history while preserving the configured account."""

    cleared_paths: list[Path] = []
    account_roots = list((shared_group_root / "accounts").glob("*"))
    cleared_databases: list[str] = []

    for account_root in account_roots:
        database_path = account_root / "dc.db"
        if not database_path.exists():
            continue
        _purge_deltachat_database(database_path)
        cleared_databases.append(str(database_path))

        blob_directory = account_root / "dc.db-blobs"
        if blob_directory.exists():
            _remove_path(blob_directory)
            cleared_paths.append(blob_directory)

    for relative_path in (
        Path("Library/Saved Application State") / f"{DELTACHAT_BUNDLE_ID}.savedState",
        Path("Library/SplashBoard/Snapshots") / f"{DELTACHAT_BUNDLE_ID} - {{DEFAULT GROUP}}",
        Path("Library/SplashBoard/Snapshots") / f"sceneID:{DELTACHAT_BUNDLE_ID}-default",
    ):
        target = app_data_root / relative_path
        if target.exists():
            _remove_path(target)
            cleared_paths.append(target)

    return {
        "cleared_paths": [str(path) for path in cleared_paths],
        "cleared_databases": cleared_databases,
    }


def _purge_deltachat_database(database_path: Path) -> None:
    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM reactions")
        connection.execute("DELETE FROM msgs_mdns")
        connection.execute("DELETE FROM msgs_status_updates")
        connection.execute("DELETE FROM download")
        connection.execute("DELETE FROM locations")
        connection.execute("DELETE FROM available_post_msgs")
        connection.execute("DELETE FROM smtp_status_updates")
        connection.execute("DELETE FROM imap_markseen")
        connection.execute("DELETE FROM imap_send")
        connection.execute("DELETE FROM imap_sync")
        connection.execute("DELETE FROM acpeerstates")
        connection.execute("DELETE FROM msgs WHERE chat_id > 11")
        connection.execute("DELETE FROM chats_contacts WHERE chat_id > 11")
        connection.execute("DELETE FROM chats_descriptions WHERE chat_id > 11")
        connection.execute("DELETE FROM chats WHERE id > 11")
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()

    for suffix in ("-shm", "-wal"):
        sidecar_path = Path(f"{database_path}{suffix}")
        if sidecar_path.exists():
            sidecar_path.unlink()


def _resolve_app_data_container_root(
    *,
    udid: str | None,
    bundle_id: str,
    app_data_container_path: str | None,
) -> Path:
    if app_data_container_path:
        return Path(app_data_container_path).expanduser().resolve()
    if not udid:
        raise ValueError(f"Unable to resolve app data container for {bundle_id}: missing simulator UDID")

    result = subprocess.run(
        ["xcrun", "simctl", "get_app_container", udid, bundle_id, "data"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).expanduser().resolve()


def _find_shared_app_group_root(*, udid: str | None, group_id: str) -> Path:
    if not udid:
        raise ValueError(f"Unable to resolve app group {group_id}: missing simulator UDID")

    app_group_root = (
        Path.home()
        / "Library"
        / "Developer"
        / "CoreSimulator"
        / "Devices"
        / udid
        / "data"
        / "Containers"
        / "Shared"
        / "AppGroup"
    )
    for metadata_path in app_group_root.glob("*/.com.apple.mobile_container_manager.metadata.plist"):
        with metadata_path.open("rb") as handle:
            metadata = plistlib.load(handle)
        if str(metadata.get("MCMMetadataIdentifier") or "").strip() == group_id:
            return metadata_path.parent
    raise FileNotFoundError(f"Unable to resolve shared app group: {group_id}")


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
