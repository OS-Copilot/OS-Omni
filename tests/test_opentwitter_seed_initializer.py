import json
import sqlite3
from pathlib import Path

from evaluators.cua_review.initializers.ios.opentwitter_open_app import (
    ITEM_TABLE,
    _parse_seed_data_js,
    _seeded_logged_in_state,
    _write_seeded_state,
)
from evaluators.cua_review.platforms.ios.webview_state import read_local_state


def test_seeded_state_matches_the_installed_apps_create_state_contract():
    seed = {
        "account": {
            "username": "alex",
            "email": "alex@opentwitter.local",
            "password": "test-password",
        },
        "users": [
            {"handle": "alex", "displayName": "Alex Chen", "avatar": "/avatar.png"}
        ],
        "following": ["devon"],
        "followers": ["maya"],
        "messages": [{"id": "m-1"}],
        "notifications": [{"id": "n-1", "read": False}],
        "posts": [{"id": "p-1"}],
        "comments": {"p-1": [{"id": "c-1"}]},
    }

    state = _seeded_logged_in_state(seed, "alex")
    alex_state = state["userStateByHandle"]["alex"]

    assert state["session"] == {
        "loggedIn": True,
        "user": {
            "handle": "alex",
            "displayName": seed["users"][0]["displayName"],
            "email": seed["account"]["email"],
            "avatar": seed["users"][0]["avatar"],
        },
    }
    assert state["posts"] == seed["posts"]
    assert state["comments"] == seed["comments"]
    assert alex_state["notifications"] == seed["notifications"]
    assert alex_state["likedPostIds"] == ["p-1005"]
    assert alex_state["bookmarkedPostIds"] == ["p-1001"]
    assert alex_state["repostedPostIds"] == []
    assert state["evaluationEvents"] == []
    assert state["evaluationEventSeq"] == 0


def test_seed_data_parser_reads_the_embedded_app_seed():
    seed = {"account": {"username": "alex"}, "posts": []}
    parsed = _parse_seed_data_js(f"window.opentwitterSeed = {json.dumps(seed)};\n")

    assert parsed == seed


def test_seeded_local_state_write_is_exact_and_readable(tmp_path):
    path = tmp_path / "localstorage.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(f"CREATE TABLE {ITEM_TABLE} (key TEXT UNIQUE, value BLOB NOT NULL)")
        connection.execute(
            f"INSERT INTO {ITEM_TABLE}(key, value) VALUES (?, ?)",
            ("opentwitter.localState.v7", b"old"),
        )

    state = {"session": {"loggedIn": True, "user": {"handle": "alex"}}}
    digest = _write_seeded_state(path, "opentwitter.localState.v7", state)

    assert len(digest) == 64
    assert read_local_state(path, "opentwitter.localState.v7") == state
