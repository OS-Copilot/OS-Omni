"""Shared Oinkoin Android helpers for benchmark initializers and evaluators."""

from __future__ import annotations

import base64
import os
import shlex
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from platforms.android.bootstrap import AndroidBootstrapDriver
from platforms.android.apk_cache import ensure_package_installed_from_cache


DEFAULT_APP_PACKAGE = "com.github.emavgl.piggybankpro"
DEFAULT_APP_ACTIVITY = "com.example.piggybank.MainActivity"
DEFAULT_WAIT_MS = 1500


def default_database_path(app_package: str = DEFAULT_APP_PACKAGE) -> str:
    package = app_package.strip() or DEFAULT_APP_PACKAGE
    return f"/data/user/0/{package}/databases/movements.db"


def ensure_app_installed(controller: Any, app_package: str) -> str:
    return ensure_package_installed_from_cache(controller, app_package, label="Oinkoin")


def ensure_adb_root(controller: Any) -> None:
    root_output = str(controller.execute_adb(["root"]) or "").strip().lower()
    if "cannot run as root" in root_output or "production builds" in root_output:
        raise RuntimeError(root_output)
    if "restarting adbd as root" in root_output:
        controller.execute_adb(["wait-for-device"])
        time.sleep(1.0)


def wait_for_home_ready(controller: Any, app_package: str = DEFAULT_APP_PACKAGE) -> None:
    driver = AndroidBootstrapDriver(controller, expected_package=app_package, settle_delay_seconds=0.5)
    node = driver.wait_for_node(
        [
            {"resource_id": "add-record", "package": app_package},
            {"resource_id": "home-tab-selected", "package": app_package},
        ],
        timeout_seconds=12.0,
        raise_on_timeout=False,
    )
    if node is not None:
        return

    # Some emulator runs make uiautomator and dumpsys window stall while the
    # Compose app is actually alive. For initializer purposes, a running app
    # process is enough; the database seeding fallback below does not need UI.
    pid_output = str(controller.execute_adb(["shell", "pidof", app_package]) or "").strip()
    if pid_output:
        return

    activity_output = str(controller.execute_adb(["shell", "dumpsys", "activity", "activities"]) or "")
    if app_package in activity_output:
        return

    raise RuntimeError(
        f"Oinkoin did not become available; pidof={pid_output!r}, "
        f"activity_contains_package={app_package in activity_output}"
    )


def prepare_fresh_state(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    clear_app_data: bool = True,
    wait_ms: int = DEFAULT_WAIT_MS,
) -> dict[str, Any]:
    ensure_app_installed(controller, app_package)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    if clear_app_data:
        controller.execute_adb(["shell", "pm", "clear", app_package])

    controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{app_activity}"])
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)

    wait_for_home_ready(controller, app_package)
    return {
        "app_package": app_package,
        "app_activity": app_activity,
        "wait_ms": wait_ms,
        "clear_app_data": clear_app_data,
    }


def create_record_via_ui(
    controller: Any,
    *,
    category_name: str,
    amount: float,
    title: str,
    note: str,
    category_kind: str = "expense",
    app_package: str = DEFAULT_APP_PACKAGE,
) -> None:
    driver = AndroidBootstrapDriver(controller, expected_package=app_package, settle_delay_seconds=0.5)

    try:
        driver.tap_selector({"resource_id": "add-record"}, timeout_seconds=10.0)

        kind = category_kind.strip().lower()
        if kind == "income":
            driver.tap_selector({"resource_id": "income-tab"}, timeout_seconds=10.0)
        else:
            driver.tap_selector({"resource_id": "expenses-tab"}, timeout_seconds=10.0)

        driver.tap_selector({"content_description": category_name}, timeout_seconds=10.0)
        driver.replace_text(
            {"resource_id": "amount-field"},
            f"{amount:.2f}",
            clear_key_presses=48,
            move_cursor_end_before_clear=True,
        )
        driver.replace_text(
            {"resource_id": "record-name-field"},
            title,
            clear_key_presses=64,
            move_cursor_end_before_clear=True,
        )
        driver.replace_text(
            {"resource_id": "note-field"},
            note,
            clear_key_presses=96,
            move_cursor_end_before_clear=True,
        )
        driver.tap_selector({"resource_id": "save-button"}, timeout_seconds=10.0)
        driver.wait_for_node({"resource_id": "add-record"}, timeout_seconds=10.0)
    except Exception:
        seed_record_directly(
            controller,
            app_package=app_package,
            category_name=category_name,
            amount=amount,
            title=title,
            note=note,
            category_kind=category_kind,
        )


def seed_record_directly(
    controller: Any,
    *,
    category_name: str,
    amount: float,
    title: str,
    note: str,
    category_kind: str = "expense",
    app_package: str = DEFAULT_APP_PACKAGE,
) -> None:
    """Seed a single Oinkoin record through its SQLite store.

    Oinkoin's current Android UI is Jetpack Compose-heavy and does not always
    expose stable resource ids for every field. The evaluators already use the
    app database as the source of truth, so direct seeding is the deterministic
    fallback when UI bootstrapping cannot reach the note field.
    """

    ensure_app_installed(controller, app_package)
    ensure_adb_root(controller)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    time.sleep(0.5)

    kind = category_kind.strip().lower()
    category_type = 1 if kind == "income" else 0
    signed_value = abs(float(amount)) if category_type == 1 else -abs(float(amount))
    now_ms = int(time.time() * 1000)
    database_path = default_database_path(app_package)

    sql = f"""
INSERT INTO profiles (name, is_default, color)
SELECT 'Default Profile', 1, NULL
WHERE NOT EXISTS (SELECT 1 FROM profiles);
UPDATE profiles
SET is_default = CASE
    WHEN id = COALESCE(
        (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1),
        (SELECT id FROM profiles ORDER BY id LIMIT 1)
    )
    THEN 1 ELSE 0
END;
INSERT INTO wallets (
    name, color, icon, icon_emoji, initial_amount, is_archived, is_default,
    is_predefined, sort_order, currency, profile_id
)
SELECT
    'Default Wallet', NULL, NULL, NULL, 0, 0, 1, 0, 0, NULL,
    (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM wallets);
UPDATE wallets
SET
    is_default = CASE
        WHEN id = COALESCE(
            (SELECT id FROM wallets WHERE is_default = 1 ORDER BY id LIMIT 1),
            (SELECT id FROM wallets ORDER BY id LIMIT 1)
        )
        THEN 1 ELSE 0
    END,
    profile_id = COALESCE(
        profile_id,
        (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1)
    );
DELETE FROM records;
INSERT OR IGNORE INTO categories (
    name, color, icon, category_type, last_used, record_count, is_archived, sort_order, icon_emoji
) VALUES (
    {_sql_quote(category_name)}, 'blue', 0, {category_type}, 0, 0, 0, 0, NULL
);
INSERT INTO records (
    datetime, timezone, value, title, description, category_name, category_type,
    recurrence_id, wallet_id, transfer_wallet_id, transfer_value, profile_id
) VALUES (
    {now_ms}, 'Asia/Shanghai', {signed_value:.2f}, {_sql_quote(title)}, {_sql_quote(note)},
    {_sql_quote(category_name)}, {category_type}, NULL,
    (SELECT id FROM wallets WHERE is_default = 1 ORDER BY id LIMIT 1),
    NULL, NULL,
    (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1)
);
UPDATE categories
SET record_count = (
    SELECT COUNT(*)
    FROM records
    WHERE records.category_name = categories.name
      AND records.category_type = categories.category_type
)
WHERE name = {_sql_quote(category_name)} AND category_type = {category_type};
"""
    _execute_sql(controller, database_path=database_path, sql=sql)
    controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{DEFAULT_APP_ACTIVITY}"])
    time.sleep(1.0)


def seed_state_directly(
    controller: Any,
    *,
    categories: Sequence[Mapping[str, Any]] | None = None,
    records: Sequence[Mapping[str, Any]] | None = None,
    app_package: str = DEFAULT_APP_PACKAGE,
) -> dict[str, Any]:
    """Replace Oinkoin categories/records with a deterministic visible state."""

    ensure_app_installed(controller, app_package)
    ensure_adb_root(controller)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    time.sleep(0.5)

    category_specs = [
        dict(item)
        for item in (categories or [])
        if isinstance(item, Mapping) and str(item.get("name") or "").strip()
    ]
    record_specs = [
        dict(item)
        for item in (records or [])
        if isinstance(item, Mapping) and str(item.get("title") or "").strip()
    ]

    category_keys: set[tuple[str, int]] = set()
    for spec in category_specs:
        category_keys.add(
            (
                str(spec.get("name") or "").strip(),
                int(spec.get("category_type", spec.get("type", 0)) or 0),
            )
        )
    for spec in record_specs:
        category_keys.add(
            (
                str(spec.get("category_name") or spec.get("category") or "Uncategorized").strip(),
                int(spec.get("category_type", 0) or 0),
            )
        )

    now_ms = int(time.time() * 1000)
    database_path = default_database_path(app_package)
    statements = [
        _oinkoin_bootstrap_sql(),
        "DELETE FROM records;",
        "DELETE FROM categories;",
    ]
    for index, (name, category_type) in enumerate(sorted(category_keys), start=1):
        color = "blue"
        icon = 0
        icon_emoji = "NULL"
        sort_order = index
        for spec in category_specs:
            if (
                str(spec.get("name") or "").strip() == name
                and int(spec.get("category_type", spec.get("type", 0)) or 0) == category_type
            ):
                color = str(spec.get("color") or color)
                icon = int(spec.get("icon", icon) or 0)
                sort_order = int(spec.get("sort_order", sort_order) or sort_order)
                emoji = str(spec.get("icon_emoji") or "").strip()
                icon_emoji = _sql_quote(emoji) if emoji else "NULL"
                break
        statements.append(
            "INSERT INTO categories ("
            "name, color, icon, category_type, last_used, record_count, is_archived, sort_order, icon_emoji"
            f") VALUES ({_sql_quote(name)}, {_sql_quote(color)}, {icon}, {category_type}, 0, 0, 0, {sort_order}, {icon_emoji});"
        )

    for index, spec in enumerate(record_specs, start=1):
        category_type = int(spec.get("category_type", 0) or 0)
        amount = float(spec.get("amount", 0.0) or 0.0)
        signed_value = abs(amount) if category_type == 1 else -abs(amount)
        category_name = str(spec.get("category_name") or spec.get("category") or "Uncategorized").strip()
        statements.append(
            "INSERT INTO records ("
            "datetime, timezone, value, title, description, category_name, category_type,"
            "recurrence_id, wallet_id, transfer_wallet_id, transfer_value, profile_id"
            ") VALUES ("
            f"{now_ms + index}, 'Asia/Shanghai', {signed_value:.2f}, "
            f"{_sql_quote(str(spec.get('title') or '').strip())}, "
            f"{_sql_quote(str(spec.get('note') or spec.get('description') or '').strip())}, "
            f"{_sql_quote(category_name)}, {category_type}, NULL, "
            "(SELECT id FROM wallets WHERE is_default = 1 ORDER BY id LIMIT 1), "
            "NULL, NULL, "
            "(SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1)"
            ");"
        )
    statements.append(
        "UPDATE categories SET record_count = ("
        "SELECT COUNT(*) FROM records "
        "WHERE records.category_name = categories.name "
        "AND records.category_type = categories.category_type"
        ");"
    )
    _execute_sql(controller, database_path=database_path, sql="\n".join(statements))
    controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{DEFAULT_APP_ACTIVITY}"])
    time.sleep(1.0)
    return {
        "database_path": database_path,
        "seed_category_count": len(category_keys),
        "seed_record_count": len(record_specs),
    }


def _execute_sql(controller: Any, *, database_path: str, sql: str) -> str:
    encoded_sql = base64.b64encode(sql.encode("utf-8")).decode("ascii")
    command = f"printf %s {encoded_sql} | base64 -d | sqlite3 {shlex.quote(database_path)}"
    return str(controller.execute_adb(["shell", command]) or "")


def _oinkoin_bootstrap_sql() -> str:
    return """
INSERT INTO profiles (name, is_default, color)
SELECT 'Default Profile', 1, NULL
WHERE NOT EXISTS (SELECT 1 FROM profiles);
UPDATE profiles
SET is_default = CASE
    WHEN id = COALESCE(
        (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1),
        (SELECT id FROM profiles ORDER BY id LIMIT 1)
    )
    THEN 1 ELSE 0
END;
INSERT INTO wallets (
    name, color, icon, icon_emoji, initial_amount, is_archived, is_default,
    is_predefined, sort_order, currency, profile_id
)
SELECT
    'Default Wallet', NULL, NULL, NULL, 0, 0, 1, 0, 0, NULL,
    (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM wallets);
UPDATE wallets
SET
    is_default = CASE
        WHEN id = COALESCE(
            (SELECT id FROM wallets WHERE is_default = 1 ORDER BY id LIMIT 1),
            (SELECT id FROM wallets ORDER BY id LIMIT 1)
        )
        THEN 1 ELSE 0
    END,
    profile_id = COALESCE(
        profile_id,
        (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1)
    );
"""


def _sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def read_database_state(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    database_path: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    db_path = database_path or default_database_path(app_package)

    ensure_app_installed(controller, app_package)
    ensure_adb_root(controller)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    time.sleep(0.5)

    with tempfile.TemporaryDirectory(prefix="oinkoin-db-") as tmpdir:
        local_dir = Path(tmpdir)
        controller.execute_adb(["pull", db_path, str(local_dir)])
        local_db = _find_pulled_database(local_dir)
        if local_db is None:
            raise RuntimeError(f"Database pull failed: {db_path}")

        connection = sqlite3.connect(local_db)
        try:
            cursor = connection.cursor()
            record_rows = cursor.execute(
                """
                SELECT id, datetime, timezone, value, title, description, category_name, category_type
                FROM records
                ORDER BY id DESC
                """
            ).fetchall()
            category_rows = cursor.execute(
                """
                SELECT name, color, icon, category_type, last_used, record_count, is_archived, sort_order, icon_emoji
                FROM categories
                ORDER BY category_type ASC, sort_order ASC, name ASC
                """
            ).fetchall()
        finally:
            connection.close()

    return {
        "records": [
            {
                "id": row[0],
                "datetime": row[1],
                "timezone": row[2],
                "value": row[3],
                "title": row[4],
                "description": row[5],
                "category_name": row[6],
                "category_type": row[7],
            }
            for row in record_rows
        ],
        "categories": [
            {
                "name": row[0],
                "color": row[1],
                "icon": row[2],
                "category_type": row[3],
                "last_used": row[4],
                "record_count": row[5],
                "is_archived": row[6],
                "sort_order": row[7],
                "icon_emoji": row[8],
            }
            for row in category_rows
        ],
    }


def _find_pulled_database(local_dir: Path) -> Path | None:
    direct_path = local_dir / "movements.db"
    if direct_path.is_file():
        return direct_path

    for root, _dirs, files in os.walk(local_dir):
        if "movements.db" in files:
            candidate = Path(root) / "movements.db"
            if candidate.is_file():
                return candidate
    return None
