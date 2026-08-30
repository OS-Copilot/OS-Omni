"""Shared Spotube Android helpers for oracle seeding and evaluator fallback."""

from __future__ import annotations

import contextlib
import json
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from platforms.android.bootstrap import AndroidBootstrapDriver


DEFAULT_APP_PACKAGE = "oss.krtirtho.spotube"
DEFAULT_APP_ACTIVITY = "com.ryanheise.audioservice.AudioServiceActivity"
DEFAULT_DATABASE_CANDIDATES = (
    "/data/user/0/{app_package}/files/db.sqlite",
    "/data/user/0/{app_package}/app_flutter/db.sqlite",
    "/data/data/{app_package}/files/db.sqlite",
    "/data/data/{app_package}/app_flutter/db.sqlite",
)


def ensure_adb_root(controller: Any) -> None:
    output = str(controller.execute_adb(["root"]) or "").strip().lower()
    if "cannot run as root" in output or "production builds" in output:
        raise RuntimeError(output)
    if "restarting adbd as root" in output:
        controller.execute_adb(["wait-for-device"])
        time.sleep(1.0)


def candidate_database_paths(app_package: str = DEFAULT_APP_PACKAGE) -> list[str]:
    package = str(app_package or DEFAULT_APP_PACKAGE).strip() or DEFAULT_APP_PACKAGE
    return [template.format(app_package=package) for template in DEFAULT_DATABASE_CANDIDATES]


def locate_database_path(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    create_if_missing: bool = False,
) -> str:
    for remote_path in candidate_database_paths(app_package):
        output = str(controller.execute_adb(["shell", "test", "-f", remote_path, "&&", "echo", "present"]) or "")
        if "present" in output:
            return remote_path

    fallback = candidate_database_paths(app_package)[0]
    if create_if_missing:
        parent = str(PurePosixPath(fallback).parent)
        controller.execute_adb(["shell", "mkdir", "-p", parent])
        return fallback
    return ""


def read_spotube_state(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    database_path: str | None = None,
) -> dict[str, Any]:
    ensure_adb_root(controller)
    db_path = str(database_path or locate_database_path(controller, app_package=app_package)).strip()
    if not db_path:
        raise RuntimeError(f"Spotube database not found for package {app_package}")

    with _temporary_directory_ignore_errors(prefix="spotube-db-") as tmpdir:
        local_db = Path(tmpdir) / "db.sqlite"
        local_wal = Path(tmpdir) / "db.sqlite-wal"
        local_shm = Path(tmpdir) / "db.sqlite-shm"
        controller.execute_adb(["pull", db_path, str(local_db)])
        local_db = _resolve_pulled_sqlite_path(local_db, db_path)
        controller.execute_adb(["pull", f"{db_path}-wal", str(local_wal)])
        controller.execute_adb(["pull", f"{db_path}-shm", str(local_shm)])
        if not local_db.exists():
            raise RuntimeError(f"Database pull failed: {db_path}")

        with sqlite3.connect(local_db) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            preferences = _read_single_row(connection, "preferences_table")
            plugins = _read_rows(
                connection,
                "plugins_table",
                columns=("id", "name", "selected_for_audio_source", "selected_for_metadata", "author"),
            )
            audio_player_state = _read_single_row(connection, "audio_player_state_table")

    parsed_tracks = _parse_tracks(audio_player_state.get("tracks")) if audio_player_state else []
    return {
        "database_path": db_path,
        "tables": sorted(tables),
        "preferences": preferences,
        "plugins": plugins,
        "audio_player_state": audio_player_state,
        "parsed_tracks": parsed_tracks,
    }


def mutate_spotube_state(
    controller: Any,
    *,
    mutator: Callable[[sqlite3.Connection], dict[str, Any]],
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    database_path: str | None = None,
) -> dict[str, Any]:
    ensure_adb_root(controller)
    db_path = str(
        database_path or locate_database_path(controller, app_package=app_package, create_if_missing=True)
    ).strip()
    if not db_path:
        raise RuntimeError(f"Could not resolve Spotube database path for package {app_package}")

    controller.execute_adb(["shell", "am", "force-stop", app_package])
    time.sleep(0.5)
    _grant_runtime_permissions(controller, app_package=app_package)

    with _temporary_directory_ignore_errors(prefix="spotube-db-edit-") as tmpdir:
        local_db = Path(tmpdir) / "db.sqlite"
        pull_output = str(controller.execute_adb(["pull", db_path, str(local_db)]) or "")
        local_db = _resolve_pulled_sqlite_path(local_db, db_path)
        if not local_db.exists() or local_db.stat().st_size <= 0:
            local_db.parent.mkdir(parents=True, exist_ok=True)
            sqlite3.connect(local_db).close()

        with sqlite3.connect(local_db) as connection:
            _ensure_minimal_schema(connection)
            metadata = mutator(connection)
            connection.commit()

        remote_parent = str(PurePosixPath(db_path).parent)
        controller.execute_adb(["shell", "mkdir", "-p", remote_parent])
        controller.execute_adb(["push", str(local_db), db_path])
        controller.execute_adb(["shell", "rm", "-f", f"{db_path}-wal", f"{db_path}-shm"])

    start_output = str(controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{app_activity}"]) or "")
    if "Error type" in start_output or "does not exist" in start_output:
        controller.execute_adb(
            [
                "shell",
                "monkey",
                "-p",
                app_package,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ]
        )
    time.sleep(1.5)
    _allow_permission_prompts(controller)
    _dismiss_spotube_onboarding(controller)
    _dismiss_spotube_prompts(controller)
    return {
        "database_path": db_path,
        "pull_output": pull_output,
        **metadata,
    }


def apply_profile_state(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    language_code: str = "en",
    market: str = "AT",
    theme_mode: str = "light",
    accent_color_scheme: str = "rose:0xfff43f5e",
    normalize_audio: bool = True,
    audio_source_plugin_name: str = "Jiosaavn Audio",
) -> dict[str, Any]:
    def _mutator(connection: sqlite3.Connection) -> dict[str, Any]:
        preference_columns = set(_table_columns(connection, "preferences_table"))
        plugin_columns = set(_table_columns(connection, "plugins_table"))
        _ensure_preferences_row(connection)

        assignments: dict[str, Any] = {}
        if "market" in preference_columns:
            assignments["market"] = market
        if "locale" in preference_columns:
            assignments["locale"] = json.dumps({"languageCode": language_code, "countryCode": None}, separators=(",", ":"))
        if "theme_mode" in preference_columns:
            assignments["theme_mode"] = theme_mode
        if "accent_color_scheme" in preference_columns:
            assignments["accent_color_scheme"] = accent_color_scheme
        if "normalize_audio" in preference_columns:
            assignments["normalize_audio"] = 1 if normalize_audio else 0
        if "endless_playback" in preference_columns:
            assignments.setdefault("endless_playback", 1)

        plugin_id = None
        if plugin_columns:
            rows = connection.execute("SELECT id, name FROM plugins_table ORDER BY id ASC").fetchall()
            for row in rows:
                if str(row[1] or "").strip() == audio_source_plugin_name:
                    plugin_id = int(row[0])
                    break
            if plugin_id is None:
                plugin_id = int(time.time())
                insert_columns = ["id", "name", "selected_for_audio_source", "selected_for_metadata"]
                insert_values: list[Any] = [plugin_id, audio_source_plugin_name, 1, 0]
                if "author" in plugin_columns:
                    insert_columns.append("author")
                    insert_values.append("Oracle")
                for optional in ("description", "version", "entry_point", "apis", "abilities", "plugin_api_version"):
                    if optional in plugin_columns:
                        insert_columns.append(optional)
                        insert_values.append("[]" if optional in {"apis", "abilities"} else ("1.0.0" if optional == "version" else ("2.0.0" if optional == "plugin_api_version" else f"oracle_{audio_source_plugin_name.lower().replace(' ', '_')}")))
                placeholders = ", ".join("?" for _ in insert_columns)
                connection.execute(
                    f"INSERT INTO plugins_table ({', '.join(insert_columns)}) VALUES ({placeholders})",
                    insert_values,
                )
            if "selected_for_audio_source" in plugin_columns:
                connection.execute("UPDATE plugins_table SET selected_for_audio_source=0")
                connection.execute(
                    "UPDATE plugins_table SET selected_for_audio_source=1 WHERE id=?",
                    (plugin_id,),
                )

        if "audio_source_id" in preference_columns:
            assignments["audio_source_id"] = str(plugin_id) if plugin_id is not None else audio_source_plugin_name
        if "audio_source" in preference_columns:
            assignments["audio_source"] = "youtube"

        _update_row(connection, "preferences_table", assignments, row_id=0)
        return {
            "updated_preferences": assignments,
            "audio_source_plugin_name": audio_source_plugin_name,
            "audio_source_plugin_id": plugin_id,
        }

    return mutate_spotube_state(
        controller,
        mutator=_mutator,
        app_package=app_package,
        app_activity=app_activity,
    )


def apply_queue_state(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    primary_track_name: str = "Naina",
    queued_track_name: str = "Zara Zara",
    track_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    resolved_track_names = [
        str(name).strip()
        for name in (track_names or [primary_track_name, queued_track_name])
        if str(name).strip()
    ]
    if not resolved_track_names:
        resolved_track_names = ["Naina", "Zara Zara"]

    def _mutator(connection: sqlite3.Connection) -> dict[str, Any]:
        _ensure_audio_player_state_table(connection)
        tracks = [
            _build_track_payload(track_name, artist_name="Oracle Playback")
            for track_name in resolved_track_names
        ]
        connection.execute("DELETE FROM audio_player_state_table")
        connection.execute(
            "INSERT INTO audio_player_state_table (id, playing, loop_mode, shuffled, collections, current_index, tracks) VALUES (1, 0, 'single', 0, '[]', 0, ?)",
            (json.dumps(tracks, ensure_ascii=False, separators=(",", ":")),),
        )
        return {"queued_tracks": resolved_track_names}

    return mutate_spotube_state(
        controller,
        mutator=_mutator,
        app_package=app_package,
        app_activity=app_activity,
    )


def apply_search_artist_state(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    artist_name: str,
) -> dict[str, Any]:
    def _mutator(connection: sqlite3.Connection) -> dict[str, Any]:
        _ensure_audio_player_state_table(connection)
        track = _build_track_payload(f"{artist_name} Oracle Track", artist_name=artist_name)
        connection.execute("DELETE FROM audio_player_state_table")
        connection.execute(
            "INSERT INTO audio_player_state_table (id, playing, loop_mode, shuffled, collections, current_index, tracks) VALUES (1, 0, 'none', 0, '[]', 0, ?)",
            (json.dumps([track], ensure_ascii=False, separators=(",", ":")),),
        )
        return {"active_artist": artist_name, "active_track": track["name"]}

    return mutate_spotube_state(
        controller,
        mutator=_mutator,
        app_package=app_package,
        app_activity=app_activity,
    )


def clear_player_state(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
) -> dict[str, Any]:
    """Remove stale playback tracks so init is not already a completed Spotube task."""

    def _mutator(connection: sqlite3.Connection) -> dict[str, Any]:
        _ensure_audio_player_state_table(connection)
        connection.execute("DELETE FROM audio_player_state_table")
        connection.execute(
            "INSERT INTO audio_player_state_table (id, playing, loop_mode, shuffled, collections, current_index, tracks) VALUES (1, 0, 'none', 0, '[]', 0, '[]')",
        )
        return {"cleared_player_state": True}

    return mutate_spotube_state(
        controller,
        mutator=_mutator,
        app_package=app_package,
        app_activity=app_activity,
    )


def _ensure_minimal_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS preferences_table (
            id INTEGER PRIMARY KEY,
            market TEXT NOT NULL DEFAULT 'US',
            locale TEXT NOT NULL DEFAULT '{"languageCode":"system","countryCode":"system"}',
            theme_mode TEXT NOT NULL DEFAULT 'system',
            accent_color_scheme TEXT NOT NULL DEFAULT 'Slate:0xff64748b',
            normalize_audio INTEGER NOT NULL DEFAULT 0,
            audio_source_id TEXT,
            audio_source TEXT NOT NULL DEFAULT 'youtube',
            endless_playback INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS plugins_table (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            selected_for_audio_source INTEGER NOT NULL DEFAULT 0,
            selected_for_metadata INTEGER NOT NULL DEFAULT 0,
            author TEXT,
            description TEXT,
            version TEXT,
            entry_point TEXT,
            apis TEXT,
            abilities TEXT,
            plugin_api_version TEXT
        )
        """
    )
    _ensure_audio_player_state_table(connection)
    _ensure_preferences_row(connection)


def _ensure_audio_player_state_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audio_player_state_table (
            id INTEGER PRIMARY KEY,
            playing INTEGER NOT NULL DEFAULT 0,
            loop_mode TEXT NOT NULL DEFAULT 'none',
            shuffled INTEGER NOT NULL DEFAULT 0,
            collections TEXT NOT NULL DEFAULT '[]',
            current_index INTEGER NOT NULL DEFAULT 0,
            tracks TEXT NOT NULL DEFAULT '[]'
        )
        """
    )


def _ensure_preferences_row(connection: sqlite3.Connection) -> None:
    columns = set(_table_columns(connection, "preferences_table"))
    if not columns:
        return

    defaults: dict[str, Any] = {
        "id": 0,
        "market": "US",
        "locale": '{"languageCode":"system","countryCode":"system"}',
        "theme_mode": "system",
        "accent_color_scheme": "Slate:0xff64748b",
        "normalize_audio": 0,
        "audio_source_id": None,
        "audio_source": "youtube",
        "endless_playback": 1,
    }
    present_columns = [column for column in defaults if column in columns]
    if not present_columns:
        return

    placeholders = ", ".join("?" for _ in present_columns)
    connection.execute(
        f"INSERT OR IGNORE INTO preferences_table ({', '.join(present_columns)}) VALUES ({placeholders})",
        [defaults[column] for column in present_columns],
    )


def _grant_runtime_permissions(controller: Any, *, app_package: str) -> None:
    permissions = (
        "android.permission.READ_MEDIA_AUDIO",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.POST_NOTIFICATIONS",
    )
    for permission in permissions:
        try:
            controller.execute_adb(["shell", "pm", "grant", app_package, permission])
        except Exception:
            continue


def _allow_permission_prompts(controller: Any) -> None:
    driver = AndroidBootstrapDriver(controller, settle_delay_seconds=0.2, poll_interval_seconds=0.2)
    selectors = [
        {"resource_id": "com.android.permissioncontroller:id/permission_allow_button"},
        {"text": "ALLOW"},
        {"text": "Allow"},
        {"text_contains": "WHILE USING"},
        {"text_contains": "While using"},
    ]
    for _ in range(3):
        tapped = driver.tap_if_present(selectors, timeout_seconds=0.8)
        if not tapped:
            break
        time.sleep(0.8)


def _dismiss_spotube_onboarding(controller: Any) -> None:
    driver = AndroidBootstrapDriver(controller, settle_delay_seconds=0.2, poll_interval_seconds=0.2)
    selectors = [
        {"text": "Skip this nonsense"},
        {"content_description": "Skip this nonsense"},
        {"text_contains": "Skip this nonsense"},
        {"text_contains": "Let's get started"},
    ]
    for _ in range(2):
        tapped = driver.tap_if_present(selectors, timeout_seconds=1.0)
        if not tapped:
            break
        time.sleep(1.0)


def _dismiss_spotube_prompts(controller: Any) -> None:
    driver = AndroidBootstrapDriver(controller, settle_delay_seconds=0.2, poll_interval_seconds=0.2)
    selectors = [
        {"content_description": "Help this project grow"},
        {"content_description": "Contribute on GitHub"},
        {"content_description": "Donate on Open Collective"},
        {"content_description": "Install a Metadata Provider"},
        {"text_contains": "Help this project grow"},
        {"text_contains": "Install a Metadata Provider"},
    ]
    for _ in range(2):
        node = driver.wait_for_node(selectors, timeout_seconds=0.8, raise_on_timeout=False)
        if node is None:
            break
        controller.execute_adb(["shell", "input", "keyevent", "4"])
        time.sleep(1.0)


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]


def _read_single_row(connection: sqlite3.Connection, table: str) -> dict[str, Any]:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if table not in tables:
        return {}
    row = connection.execute(f"SELECT * FROM {table} ORDER BY id ASC LIMIT 1").fetchone()
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def _read_rows(connection: sqlite3.Connection, table: str, *, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if table not in tables:
        return []
    available = [column for column in columns if column in _table_columns(connection, table)]
    if not available:
        return []
    rows = connection.execute(
        f"SELECT {', '.join(available)} FROM {table} ORDER BY id ASC"
    ).fetchall()
    return [{column: row[idx] for idx, column in enumerate(available)} for row in rows]


@contextlib.contextmanager
def _temporary_directory_ignore_errors(*, prefix: str):
    tmpdir = tempfile.mkdtemp(prefix=prefix)
    try:
        yield tmpdir
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _resolve_pulled_sqlite_path(local_path: Path, remote_path: str) -> Path:
    if local_path.is_file() or not local_path.exists():
        return local_path
    remote_name = PurePosixPath(remote_path).name
    direct_child = local_path / remote_name
    if direct_child.is_file():
        return direct_child
    for candidate in local_path.rglob(remote_name):
        if candidate.is_file():
            return candidate
    for candidate in local_path.rglob("*.sqlite"):
        if candidate.is_file():
            return candidate
    return local_path


def _update_row(connection: sqlite3.Connection, table: str, values: Mapping[str, Any], *, row_id: int) -> None:
    assignments = {key: value for key, value in values.items() if value is not None}
    if not assignments:
        return
    columns = ", ".join(f"{column}=?" for column in assignments)
    params = list(assignments.values()) + [row_id]
    connection.execute(f"UPDATE {table} SET {columns} WHERE id=?", params)


def _parse_tracks(raw: Any) -> list[dict[str, Any]]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _build_track_payload(track_name: str, *, artist_name: str) -> dict[str, Any]:
    artist = {
        "id": artist_name.lower().replace(" ", "-"),
        "name": artist_name,
        "externalUri": f"https://example.test/artist/{artist_name.lower().replace(' ', '-')}"
    }
    return {
        "id": track_name.lower().replace(" ", "-") or f"track-{int(time.time())}",
        "name": track_name,
        "externalUri": f"https://example.test/track/{track_name.lower().replace(' ', '-')}",
        "artists": [artist],
        "album": {
            "id": "oracle-album",
            "name": "Oracle Album",
            "externalUri": "https://example.test/album/oracle-album",
            "artists": [artist],
            "images": [],
            "albumType": "album",
            "releaseDate": "2026-01-01",
        },
        "durationMs": 180000,
        "isrc": "ORACLE000000",
        "explicit": False,
    }
