"""Shared Tasks.org Android helpers for benchmark initializers and evaluators."""

from __future__ import annotations

import datetime as dt
import base64
import sqlite3
import tempfile
import time
from pathlib import Path
import shlex
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # Python 3.8 test environment fallback.
    class ZoneInfoNotFoundError(Exception):
        pass

    def ZoneInfo(_name: str) -> dt.tzinfo:
        return dt.timezone.utc

from platforms.android.bootstrap import AndroidBootstrapDriver
from platforms.android.bench_storage_support import ensure_app_installed


DEFAULT_APP_PACKAGE = "org.tasks"
DEFAULT_APP_ACTIVITY = "com.todoroo.astrid.activity.TaskListActivity"
DEFAULT_MAIN_ACTIVITY = "com.todoroo.astrid.activity.MainActivity"
DEFAULT_DATABASE_PATH = "/data/user/0/org.tasks/databases/database"
DEFAULT_WAIT_MS = 1200
REPO_ROOT = Path(__file__).resolve().parents[2]
HOST_TEMP_ROOT = REPO_ROOT / ".cache" / "android_tmp"


def _host_temp_dir(prefix: str) -> tempfile.TemporaryDirectory[str]:
    HOST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=HOST_TEMP_ROOT)


def _pull_database_files(controller: Any, database_path: str, tmp_path: Path) -> Path:
    controller.execute_adb(["pull", database_path, str(tmp_path)])
    controller.execute_adb(["pull", f"{database_path}-wal", str(tmp_path)])
    controller.execute_adb(["pull", f"{database_path}-shm", str(tmp_path)])
    local_db = tmp_path / Path(database_path).name
    if not local_db.is_file():
        raise RuntimeError(f"Database pull failed: {database_path}")
    return local_db


def collapse_system_ui(controller: Any) -> None:
    try:
        controller.execute_adb(["shell", "cmd", "statusbar", "collapse"])
    except Exception:
        pass
    try:
        controller.execute_adb(["shell", "wm", "dismiss-keyguard"])
    except Exception:
        pass
    time.sleep(0.3)
    try:
        activity = ""
        if hasattr(controller, "get_current_activity"):
            activity = str(controller.get_current_activity() or "")
        if "com.android.systemui" in activity:
            controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_BACK"])
            time.sleep(0.2)
    except Exception:
        pass


def ensure_adb_root(controller: Any) -> None:
    root_output = str(controller.execute_adb(["root"]) or "").strip().lower()
    if "cannot run as root" in root_output or "production builds" in root_output:
        raise RuntimeError(root_output)
    if "restarting adbd as root" in root_output:
        controller.execute_adb(["wait-for-device"])
        time.sleep(1.0)


def _database_exists(controller: Any, database_path: str = DEFAULT_DATABASE_PATH) -> bool:
    output = str(
        controller.execute_adb(
            ["shell", f"if [ -f {database_path!r} ]; then echo present; fi"]
        )
        or ""
    ).strip()
    return output == "present"


def _wait_for_database(
    controller: Any,
    *,
    app_package: str,
    app_activity: str,
    database_path: str,
    wait_ms: int,
) -> str:
    ensure_adb_root(controller)
    if _database_exists(controller, database_path):
        return "existing"

    controller.execute_adb(["shell", "am", "force-stop", app_package])
    controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{app_activity}"])
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)
    collapse_system_ui(controller)

    driver = AndroidBootstrapDriver(controller, expected_package=app_package, settle_delay_seconds=0.4)
    if driver.node_exists({"text": "Continue without sync"}, timeout_seconds=4.0):
        driver.tap_selector({"text": "Continue without sync"}, timeout_seconds=6.0)

    deadline = time.time() + 45.0
    while time.time() < deadline:
        if _database_exists(controller, database_path):
            return "created"
        time.sleep(0.5)

    raise RuntimeError(f"Tasks.org database was not created: {database_path}")


def reset_tasks_database(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    database_path: str = DEFAULT_DATABASE_PATH,
) -> dict[str, Any]:
    """Clear user-created Tasks.org task rows without clearing app onboarding state."""

    ensure_app_installed(controller, app_package, label="Tasks.org")
    ensure_adb_root(controller)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    time.sleep(0.5)

    if not _database_exists(controller, database_path):
        return {"database_path": database_path, "reset": False, "reason": "missing_database"}

    with _host_temp_dir("tasks-org-reset-") as tmpdir:
        tmp_path = Path(tmpdir)
        local_db = _pull_database_files(controller, database_path, tmp_path)

        connection = sqlite3.connect(local_db)
        try:
            cursor = connection.cursor()
            existing_tables = {
                str(row[0])
                for row in cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            deleted_tables: list[str] = []
            for table_name in (
                "tasks",
                "task_attachments",
                "caldav_tasks",
                "comments",
                "userActivity",
                "Tasks",
                "Properties",
                "Instances",
                "FTS_Content",
            ):
                if table_name not in existing_tables:
                    continue
                cursor.execute(f'DELETE FROM "{table_name}"')
                deleted_tables.append(table_name)
            if "sqlite_sequence" in existing_tables:
                placeholders = ",".join("?" for _ in deleted_tables)
                if placeholders:
                    cursor.execute(
                        f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
                        deleted_tables,
                    )
            connection.commit()
            try:
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.DatabaseError:
                pass
            try:
                cursor.execute("VACUUM")
            except sqlite3.DatabaseError:
                pass
        finally:
            connection.close()

        controller.execute_adb(["push", str(local_db), database_path])
        controller.execute_adb(["shell", "rm", "-f", f"{database_path}-wal", f"{database_path}-shm"])

    return {
        "database_path": database_path,
        "reset": True,
        "deleted_tables": deleted_tables,
    }


def _start_blank_editor_intent(
    controller: Any,
    *,
    app_package: str,
    wait_ms: int,
) -> None:
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    controller.execute_adb(
        [
            "shell",
            "am",
            "start",
            "-n",
            f"{app_package}/{DEFAULT_MAIN_ACTIVITY}",
            "-a",
            "android.intent.action.VIEW",
            "--ei",
            "open_task",
            "0",
        ]
    )
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)


def _wait_for_blank_editor_or_fallback_to_fab(
    controller: Any,
    *,
    app_package: str,
) -> str:
    driver = AndroidBootstrapDriver(controller, expected_package=app_package, settle_delay_seconds=0.4)
    node = driver.wait_for_node(
        {"class_name": "android.widget.EditText", "text": "Task name"},
        timeout_seconds=8.0,
        raise_on_timeout=False,
    )
    if node is not None:
        return "shortcut_intent"

    if driver.node_exists({"text": "Continue without sync"}, timeout_seconds=2.0):
        driver.tap_selector({"text": "Continue without sync"}, timeout_seconds=6.0)

    driver.wait_for_node(
        [
            {"resource_id": "org.tasks:id/fab"},
            {"content_description": "Create new task"},
        ],
        timeout_seconds=10.0,
    )
    driver.tap_selector(
        [
            {"resource_id": "org.tasks:id/fab"},
            {"content_description": "Create new task"},
        ],
        timeout_seconds=10.0,
    )
    driver.wait_for_node({"class_name": "android.widget.EditText", "text": "Task name"}, timeout_seconds=10.0)
    return "fab_fallback"


def prepare_blank_task_editor(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    clear_app_data: bool = True,
    wait_ms: int = DEFAULT_WAIT_MS,
) -> dict[str, Any]:
    ensure_app_installed(controller, app_package, label="Tasks.org")
    collapse_system_ui(controller)
    database_state = _wait_for_database(
        controller,
        app_package=app_package,
        app_activity=app_activity,
        database_path=DEFAULT_DATABASE_PATH,
        wait_ms=wait_ms,
    )
    reset_metadata = (
        reset_tasks_database(controller, app_package=app_package, database_path=DEFAULT_DATABASE_PATH)
        if clear_app_data
        else {"reset": False, "reason": "clear_app_data_disabled"}
    )

    collapse_system_ui(controller)
    _start_blank_editor_intent(controller, app_package=app_package, wait_ms=wait_ms)
    collapse_system_ui(controller)
    editor_entry = _wait_for_blank_editor_or_fallback_to_fab(controller, app_package=app_package)

    return {
        "app_package": app_package,
        "app_activity": app_activity,
        "clear_app_data": clear_app_data,
        "wait_ms": wait_ms,
        "database_state": database_state,
        "reset": reset_metadata,
        "editor_entry": editor_entry,
    }


def prepare_task_list_view(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    clear_app_data: bool = True,
    wait_ms: int = DEFAULT_WAIT_MS,
    seed_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ensure_app_installed(controller, app_package, label="Tasks.org")
    collapse_system_ui(controller)
    database_state = _wait_for_database(
        controller,
        app_package=app_package,
        app_activity=app_activity,
        database_path=DEFAULT_DATABASE_PATH,
        wait_ms=wait_ms,
    )
    reset_metadata = (
        reset_tasks_database(controller, app_package=app_package, database_path=DEFAULT_DATABASE_PATH)
        if clear_app_data
        else {"reset": False, "reason": "clear_app_data_disabled"}
    )

    normalized_seed_tasks = [
        _normalize_seed_task_spec(dict(item))
        for item in (seed_tasks or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    if normalized_seed_tasks:
        _seed_task_rows(controller, normalized_seed_tasks)

    collapse_system_ui(controller)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{DEFAULT_MAIN_ACTIVITY}"])
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)
    collapse_system_ui(controller)

    driver = AndroidBootstrapDriver(controller, expected_package=app_package, settle_delay_seconds=0.4)
    if driver.node_exists({"text": "Continue without sync"}, timeout_seconds=2.0):
        driver.tap_selector({"text": "Continue without sync"}, timeout_seconds=6.0)
    driver.wait_for_node(
        [
            {"resource_id": "org.tasks:id/fab"},
            {"content_description": "Create new task"},
            {"text_contains": "Benchmark"},
        ],
        timeout_seconds=12.0,
    )

    return {
        "app_package": app_package,
        "app_activity": app_activity,
        "clear_app_data": clear_app_data,
        "wait_ms": wait_ms,
        "database_state": database_state,
        "reset": reset_metadata,
        "seed_task_count": len(normalized_seed_tasks),
        "entry": "task_list",
    }


def read_database_state(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    database_path: str = DEFAULT_DATABASE_PATH,
) -> dict[str, list[dict[str, Any]]]:
    ensure_app_installed(controller, app_package, label="Tasks.org")
    ensure_adb_root(controller)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    time.sleep(0.5)

    with _host_temp_dir("tasks-org-db-") as tmpdir:
        local_db = _pull_database_files(controller, database_path, Path(tmpdir))

        connection = sqlite3.connect(local_db)
        try:
            cursor = connection.cursor()
            task_rows = cursor.execute(
                """
                SELECT _id, title, importance, dueDate, hideUntil, created, modified,
                       completed, deleted, notes, parent, remoteId, collapsed, read_only, "order"
                FROM tasks
                ORDER BY _id ASC
                """
            ).fetchall()
            list_rows = cursor.execute(
                """
                SELECT cdl_id, cdl_account, cdl_uuid, cdl_name, cdl_color, cdl_order
                FROM caldav_lists
                ORDER BY cdl_id ASC
                """
            ).fetchall()
        finally:
            connection.close()

    return {
        "tasks": [
            {
                "id": row[0],
                "title": row[1],
                "importance": row[2],
                "dueDate": row[3],
                "hideUntil": row[4],
                "created": row[5],
                "modified": row[6],
                "completed": row[7],
                "deleted": row[8],
                "notes": row[9],
                "parent": row[10],
                "remoteId": row[11],
                "collapsed": row[12],
                "read_only": row[13],
                "order": row[14],
            }
            for row in task_rows
        ],
        "lists": [
            {
                "id": row[0],
                "account": row[1],
                "uuid": row[2],
                "name": row[3],
                "color": row[4],
                "order": row[5],
            }
            for row in list_rows
        ],
    }


def _device_now(controller: Any) -> dt.datetime:
    epoch_seconds = int(str(controller.execute_adb(["shell", "date", "+%s"]) or "0").strip() or 0)
    timezone_name = str(
        controller.execute_adb(["shell", "getprop", "persist.sys.timezone"]) or "UTC"
    ).strip() or "UTC"
    try:
        tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tzinfo = dt.timezone.utc
    return dt.datetime.fromtimestamp(epoch_seconds, tz=tzinfo)


def _normalize_seed_task_spec(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(raw.get("title") or "").strip(),
        "note": str(raw.get("note") or "").strip(),
        "parent": int(raw.get("parent", 0) or 0),
        "order_index": int(raw.get("order_index", 1) or 1),
        "importance": int(raw.get("importance", 0) or 0),
        "due_day_offset": raw.get("due_day_offset"),
        "completed": int(raw.get("completed", 0) or 0),
    }


def _seed_task_rows(controller: Any, seed_tasks: list[dict[str, Any]]) -> None:
    device_now = _device_now(controller)
    created_ms = int(device_now.timestamp() * 1000)
    statements = [
        "DELETE FROM tasks;",
        "DELETE FROM sqlite_sequence WHERE name='tasks';",
    ]
    for index, task in enumerate(seed_tasks, start=1):
        due_ms = 0
        due_day_offset = task.get("due_day_offset")
        if due_day_offset not in (None, ""):
            expected_day = (device_now + dt.timedelta(days=int(due_day_offset))).date()
            due_dt = dt.datetime.combine(expected_day, dt.time(hour=9, minute=0), tzinfo=device_now.tzinfo)
            due_ms = int(due_dt.timestamp() * 1000)
        statements.append(
            f"INSERT INTO tasks ({_TASKS_ORG_COLUMNS_SQL}) VALUES "
            f"({_tasks_org_values_sql(title=task['title'], note=task['note'], due_ms=due_ms, parent=task['parent'], order_index=task['order_index'], created_ms=created_ms + index, importance=task['importance'], completed=task['completed'])});"
        )
    _tasks_org_execute_sql(controller, "".join(statements))


def _tasks_org_execute_sql(controller: Any, sql: str) -> None:
    encoded_sql = base64.b64encode(sql.encode("utf-8")).decode("ascii")
    command = f"printf %s {encoded_sql} | base64 -d | sqlite3 {shlex.quote(DEFAULT_DATABASE_PATH)}"
    controller.execute_adb(["shell", command])
    controller.execute_adb(["shell", "am", "force-stop", DEFAULT_APP_PACKAGE])
    controller.execute_adb(["shell", "am", "start", "-n", f"{DEFAULT_APP_PACKAGE}/{DEFAULT_MAIN_ACTIVITY}"])
    time.sleep(1.0)


_TASKS_ORG_COLUMNS_SQL = (
    "title,importance,dueDate,hideUntil,created,modified,completed,deleted,"
    "notes,estimatedSeconds,elapsedSeconds,timerStart,notificationFlags,lastNotified,"
    "recurrence,repeat_from,calendarUri,remoteId,collapsed,parent,\"order\",read_only"
)


def _tasks_org_values_sql(
    *,
    title: str,
    note: str,
    due_ms: int,
    parent: int,
    order_index: int,
    created_ms: int,
    importance: int = 0,
    completed: int = 0,
) -> str:
    return ",".join(
        [
            _sql_quote(title),
            str(int(importance)),
            str(int(due_ms)),
            "0",
            str(created_ms),
            str(created_ms),
            str(int(completed)),
            "0",
            _sql_quote(note),
            "0",
            "0",
            "0",
            "0",
            "0",
            "NULL",
            "0",
            "NULL",
            "NULL",
            "0",
            str(int(parent)),
            str(int(order_index)),
            "0",
        ]
    )


def _sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"
