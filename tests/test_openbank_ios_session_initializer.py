import json
import sqlite3

import pytest

from evaluators.cua_review.initializers.ios.openbank_open_app import (
    _prepare_logged_in_session,
)
from evaluators.cua_review.platforms.ios.webview_state import ITEM_TABLE


def _database(path, state):
    encoded = json.dumps(state, ensure_ascii=False).encode("utf-16-le")
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"CREATE TABLE {ITEM_TABLE} (key TEXT PRIMARY KEY, value BLOB NOT NULL)"
        )
        connection.execute(
            f"INSERT INTO {ITEM_TABLE} (key, value) VALUES (?, ?)",
            ("openbank.localState.v7", sqlite3.Binary(encoded)),
        )


def test_openbank_initializer_prepares_only_the_signed_in_session(tmp_path):
    database = tmp_path / "localstorage.sqlite3"
    original = {
        "customer": {
            "id": "cust-jordan",
            "displayName": "Jordan Lee",
            "preferredName": "Jordan",
            "email": "jordan@openbank.local",
            "phone": "13900003026",
        },
        "session": {"loggedIn": False, "user": None},
        "transactions": [{"id": "seed-1"}],
    }
    _database(database, original)

    session = _prepare_logged_in_session(database, "openbank.localState.v7")

    assert session == {
        "loggedIn": True,
        "user": {
            "id": "cust-jordan",
            "displayName": "Jordan Lee",
            "preferredName": "Jordan",
            "email": "jordan@openbank.local",
            "phone": "13900003026",
        },
    }
    with sqlite3.connect(database) as connection:
        raw = connection.execute(
            f"SELECT value FROM {ITEM_TABLE} WHERE key = ?",
            ("openbank.localState.v7",),
        ).fetchone()[0]
    updated = json.loads(bytes(raw).decode("utf-16-le"))
    assert updated["transactions"] == original["transactions"]


def test_openbank_initializer_rejects_unrecognized_customer(tmp_path):
    database = tmp_path / "localstorage.sqlite3"
    _database(database, {"customer": {"id": "other"}, "session": {"loggedIn": False}})

    with pytest.raises(ValueError, match="seeded Jordan Lee customer"):
        _prepare_logged_in_session(database, "openbank.localState.v7")
