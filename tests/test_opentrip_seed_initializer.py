import json
import sqlite3
from unittest.mock import patch

from evaluators.cua_review.initializers.ios.opentrip_seed_state import (
    ITEM_TABLE,
    SEED_BOOKING_IDS,
    _seeded_state,
    _write_seeded_state,
    _app_is_running,
)
from evaluators.cua_review.platforms.ios.webview_state import read_local_state


def _seed():
    return {
        "benchmarkAccount": {
            "id": "account-benchmark",
            "name": "Lucas Lin",
            "phone": "13900002026",
            "avatar": "/avatar.png",
            "password": "test-password",
        },
        "travelers": [{"id": "traveler-lucas", "name": "Lucas Lin"}],
        "paymentMethods": [{"id": "alipay"}],
        "defaultBookings": [{"id": value, "type": "flight"} for value in SEED_BOOKING_IDS],
    }


def test_seed_builder_restores_the_shared_open_trip_schema():
    seed = _seed()

    state = _seeded_state(seed)

    assert [row["id"] for row in state["bookings"]] == list(SEED_BOOKING_IDS)
    assert state["benchmarkEvents"] == []
    assert "password" not in state["session"]["user"]
    assert state["accounts"][0]["createdAt"] == "seed"
    assert state["accounts"][0]["voucherWallet"] == {
        "flight": 0,
        "hotel": 0,
        "baggage": 0,
    }
    assert state["travelers"] == seed["travelers"]
    assert state["paymentMethods"] == seed["paymentMethods"]


def test_seeded_local_storage_write_replaces_contaminated_runtime_state(tmp_path):
    path = tmp_path / "localstorage.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(f"CREATE TABLE {ITEM_TABLE} (key TEXT UNIQUE, value BLOB NOT NULL)")
        old = json.dumps({"bookings": [{"id": "OT1234567890123"}]}).encode("utf-16-le")
        connection.execute(
            f"INSERT INTO {ITEM_TABLE}(key, value) VALUES (?, ?)",
            ("opentrip.localState.v1", old),
        )

    state = _seeded_state(_seed())
    digest = _write_seeded_state(path, "opentrip.localState.v1", state)
    observed = read_local_state(path, "opentrip.localState.v1")

    assert len(digest) == 64
    assert observed == state
    assert [row["id"] for row in observed["bookings"]] == list(SEED_BOOKING_IDS)
    assert all(not row["id"].startswith("OT1") for row in observed["bookings"])


def test_simctl_process_query_failure_never_treats_app_as_stopped():
    failed = type("Result", (), {"returncode": 1, "stderr": "simctl unavailable", "stdout": ""})()
    with patch(
        "evaluators.cua_review.initializers.ios.opentrip_seed_state.subprocess.run",
        return_value=failed,
    ):
        try:
            _app_is_running("simulator-id", "com.killt.opentrip")
        except RuntimeError as exc:
            assert "could not query" in str(exc)
        else:
            raise AssertionError("simctl failure must not be treated as a stopped app")
