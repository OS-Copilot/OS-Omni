"""Restore and verify the canonical seed shared by the current iOS OpenTrip tasks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evaluators.cua_review.platforms.ios.webview_state import (
    ITEM_TABLE,
    find_state_database,
    read_local_state,
    resolve_state_key,
    stored_value,
)

DEFAULT_BUNDLE_ID = "com.killt.opentrip"
LOCAL_STATE_KEY_PREFIX = "opentrip.localState."
EXPECTED_BASE_STATE_SHA256 = "f2e6ce37e0fa96ec73fba0be4a339bb3047e8552f688b50158e5f94924e9ff04"
SEED_BOOKING_IDS = (
    "OT-SEED-FLIGHT-1",
    "OT-SEED-HOTEL-1",
    "OT-SEED-FLIGHT-2",
    "OT-SEED-HOTEL-2",
)


def _seed_from_app_bundle(udid: str, bundle_id: str) -> tuple[dict[str, Any], str]:
    result = subprocess.run(
        ["xcrun", "simctl", "get_app_container", udid, bundle_id, "app"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("could not locate the installed OpenTrip app bundle")
    seed_path = Path(result.stdout.strip()) / "public" / "seed-data.js"
    raw = seed_path.read_bytes()
    source = raw.decode("utf-8")
    marker = "window.opentripSeed ="
    if marker not in source:
        raise ValueError("installed OpenTrip bundle has no window.opentripSeed")
    payload = source.split(marker, 1)[1].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    seed = json.loads(payload)
    if not isinstance(seed, dict) or not isinstance(seed.get("benchmarkAccount"), dict):
        raise ValueError("installed OpenTrip seed has an invalid structure")
    if not isinstance(seed.get("defaultBookings"), list) or len(seed["defaultBookings"]) != 4:
        raise ValueError("installed OpenTrip seed does not contain four baseline bookings")
    return seed, hashlib.sha256(raw).hexdigest()


def _seeded_state(seed: Mapping[str, Any]) -> dict[str, Any]:
    account = dict(seed["benchmarkAccount"])
    account.update(
        {
            "id": "account-benchmark",
            "voucherBalance": 0,
            "voucherWallet": {"flight": 0, "hotel": 0, "baggage": 0},
            "redeemedCodes": [],
            "createdAt": "seed",
        }
    )
    return {
        "session": {
            "loggedIn": True,
            "user": {
                key: value
                for key, value in account.items()
                if key not in {"password", "redeemedCodes", "createdAt"}
            },
        },
        "accounts": [account],
        "travelers": list(seed.get("travelers") or []),
        "paymentMethods": list(seed.get("paymentMethods") or []),
        "bookings": list(seed["defaultBookings"]),
        "benchmarkEvents": [],
    }


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_seeded_state(db_path: Path, state_key: str, state: Mapping[str, Any]) -> str:
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-16-le")
    with sqlite3.connect(db_path, timeout=10) as connection:
        connection.execute("PRAGMA busy_timeout = 10000")
        cursor = connection.execute(
            f"UPDATE {ITEM_TABLE} SET value = ? WHERE key = ?",
            (sqlite3.Binary(encoded), state_key),
        )
        if cursor.rowcount != 1:
            raise ValueError("OpenTrip local-storage state row was not updated")
        connection.commit()
    if stored_value(db_path, state_key) != encoded:
        raise ValueError("OpenTrip seed state did not persist exactly")
    return hashlib.sha256(encoded).hexdigest()


def _app_is_running(udid: str, bundle_id: str) -> bool:
    result = subprocess.run(
        ["xcrun", "simctl", "spawn", udid, "launchctl", "list"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"could not query simulator app processes: {detail}")
    return bundle_id in result.stdout


def _terminate_app(udid: str, bundle_id: str) -> None:
    if not _app_is_running(udid, bundle_id):
        return
    result = subprocess.run(
        ["xcrun", "simctl", "terminate", udid, bundle_id],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"could not stop OpenTrip before seed write: {detail}")


def _state_db(udid: str, bundle_id: str) -> tuple[Path, str]:
    from evaluators.cua_review.core.initialization import app_data_container

    container = app_data_container(udid, bundle_id)
    if container is None:
        raise RuntimeError("OpenTrip app data container was not found")
    db_path = find_state_database(container, LOCAL_STATE_KEY_PREFIX)
    state_key = resolve_state_key(db_path, LOCAL_STATE_KEY_PREFIX)
    return db_path, state_key


def verify_opentrip_seed_state(udid: str, bundle_id: str = DEFAULT_BUNDLE_ID) -> dict[str, Any]:
    """Read back the visible app's persisted seed after launch and settle."""
    db_path, state_key = _state_db(udid, bundle_id)
    state = read_local_state(db_path, state_key)
    state_sha256 = _canonical_sha256(state)
    booking_ids = [row.get("id") for row in state.get("bookings", [])]
    if state_sha256 != EXPECTED_BASE_STATE_SHA256:
        raise ValueError("OpenTrip state changed after launch; canonical baseline hash differs")
    if booking_ids != list(SEED_BOOKING_IDS):
        raise ValueError("OpenTrip state changed after launch; baseline booking IDs/order differ")
    return {"baseline_state_sha256": state_sha256, "baseline_booking_ids": booking_ids}


def restore_opentrip_seed_state(udid: str, bundle_id: str = DEFAULT_BUNDLE_ID) -> dict[str, Any]:
    """Rebuild the standard four-booking baseline before an OpenTrip task."""
    from evaluators.cua_review.core.initialization import (
        launch_app,
        simulator_is_booted,
        wait_until_running,
    )

    if bundle_id != DEFAULT_BUNDLE_ID:
        raise ValueError(f"unexpected OpenTrip bundle ID: {bundle_id}")
    if not simulator_is_booted(udid):
        raise RuntimeError(f"simulator {udid} is not booted")
    launch_app(udid, bundle_id)
    wait_until_running(udid, bundle_id)
    time.sleep(0.8)
    _terminate_app(udid, bundle_id)
    db_path, state_key = _state_db(udid, bundle_id)
    seed, seed_sha256 = _seed_from_app_bundle(udid, bundle_id)
    state = _seeded_state(seed)
    state_sha256 = _write_seeded_state(db_path, state_key, state)
    state_check = read_local_state(db_path, state_key)
    baseline_sha256 = _canonical_sha256(state_check)
    if baseline_sha256 != EXPECTED_BASE_STATE_SHA256:
        raise ValueError("installed OpenTrip seed does not match the evaluators' canonical baseline")
    booking_ids = [row.get("id") for row in state_check.get("bookings", [])]
    if booking_ids != list(SEED_BOOKING_IDS):
        raise ValueError("installed OpenTrip seed booking IDs/order do not match the baseline")
    return {
        "seed_source_sha256": seed_sha256,
        "seeded_state_sha256": state_sha256,
        "baseline_state_sha256": baseline_sha256,
        "baseline_booking_ids": booking_ids,
    }
