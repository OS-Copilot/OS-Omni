"""Initializers for Fossify Calendar benchmark tasks."""

from __future__ import annotations

import base64
import datetime as dt
import shlex
import time
import uuid
from typing import Any, Mapping

try:
    from zoneinfo import ZoneInfo
except ModuleNotFoundError:  # pragma: no cover - compatibility with older local Python.
    ZoneInfo = None  # type: ignore[assignment]

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.app_utils import ensure_package_installed


DEFAULT_APP_PACKAGE = "org.fossify.calendar"
DEFAULT_DATABASE_PATH = "/data/user/0/org.fossify.calendar/databases/events.db"
DEFAULT_TIMEZONE = "UTC"


class FossifyCalendarInitializer(BaseInitializer):
    """Prepare a clean Fossify local calendar database and open the app."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Fossify Calendar initialization",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        database_path = str(params.get("database_path") or DEFAULT_DATABASE_PATH).strip()
        timezone_name = str(params.get("timezone") or DEFAULT_TIMEZONE).strip()
        seed_events = list(params.get("seed_events") or [])
        clear_app_data = bool(params.get("clear_app_data", True))
        wait_ms = int(params.get("wait_ms", 1500) or 0)

        try:
            self._require_package_installed(controller, app_package)
            if clear_app_data:
                controller.execute_adb(["shell", "pm", "clear", app_package])
            self._grant_permissions(controller, app_package)

            controller.execute_adb(
                ["shell", "monkey", "-p", app_package, "-c", "android.intent.category.LAUNCHER", "1"]
            )
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            self._wait_for_database(controller, database_path=database_path, app_package=app_package)
            self._execute_sql(
                controller,
                database_path=database_path,
                sql="DELETE FROM events WHERE title LIKE 'BMK %';",
            )
            for event in seed_events:
                self._insert_event(
                    controller,
                    database_path=database_path,
                    event=dict(event),
                    timezone_name=timezone_name,
                )

            controller.execute_adb(["shell", "am", "force-stop", app_package])
            controller.execute_adb(
                ["shell", "monkey", "-p", app_package, "-c", "android.intent.category.LAUNCHER", "1"]
            )
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Fossify Calendar: {type(exc).__name__}: {exc}",
                metadata={
                    "app_package": app_package,
                    "database_path": database_path,
                    "seed_event_count": len(seed_events),
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Fossify Calendar opened with a clean benchmark event set",
            metadata={
                "app_package": app_package,
                "database_path": database_path,
                "seed_event_count": len(seed_events),
            },
        )

    @staticmethod
    def _require_package_installed(controller: Any, package_name: str) -> None:
        ensure_package_installed(controller, package_name, label="Fossify Calendar")

    @staticmethod
    def _grant_permissions(controller: Any, package_name: str) -> None:
        for permission in (
            "android.permission.READ_CALENDAR",
            "android.permission.WRITE_CALENDAR",
            "android.permission.POST_NOTIFICATIONS",
        ):
            controller.execute_adb(["shell", "pm", "grant", package_name, permission])

    @staticmethod
    def _wait_for_database(controller: Any, *, database_path: str, app_package: str) -> None:
        for attempt in range(30):
            output = str(controller.execute_adb(["shell", "test", "-f", database_path, "&&", "echo", "present"]) or "")
            if "present" in output:
                return
            if attempt in {9, 19}:
                controller.execute_adb(
                    ["shell", "monkey", "-p", app_package, "-c", "android.intent.category.LAUNCHER", "1"]
                )
            time.sleep(0.5)
        FossifyCalendarInitializer._create_minimal_database(
            controller,
            database_path=database_path,
            app_package=app_package,
        )

    @staticmethod
    def _create_minimal_database(controller: Any, *, database_path: str, app_package: str) -> None:
        root_output = str(controller.execute_adb(["root"]) or "").strip().lower()
        if "cannot run as root" in root_output or "production builds" in root_output:
            raise RuntimeError(f"Fossify Calendar database was not created: {database_path}")
        if "restarting adbd as root" in root_output:
            controller.execute_adb(["wait-for-device"])
            time.sleep(1.0)

        quoted_db = shlex.quote(database_path)
        quoted_dir = shlex.quote(str(database_path.rsplit("/", 1)[0]))
        schema = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  start_ts INTEGER NOT NULL DEFAULT 0,
  end_ts INTEGER NOT NULL DEFAULT 0,
  title TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  reminder_1_minutes INTEGER NOT NULL DEFAULT -1,
  reminder_2_minutes INTEGER NOT NULL DEFAULT -1,
  reminder_3_minutes INTEGER NOT NULL DEFAULT -1,
  reminder_1_type INTEGER NOT NULL DEFAULT 0,
  reminder_2_type INTEGER NOT NULL DEFAULT 0,
  reminder_3_type INTEGER NOT NULL DEFAULT 0,
  repeat_interval INTEGER NOT NULL DEFAULT 0,
  repeat_rule INTEGER NOT NULL DEFAULT 0,
  repeat_limit INTEGER NOT NULL DEFAULT 0,
  repetition_exceptions TEXT NOT NULL DEFAULT '[]',
  attendees TEXT NOT NULL DEFAULT '[]',
  import_id TEXT NOT NULL DEFAULT '',
  time_zone TEXT NOT NULL DEFAULT '',
  flags INTEGER NOT NULL DEFAULT 0,
  event_type INTEGER NOT NULL DEFAULT 1,
  parent_id INTEGER NOT NULL DEFAULT 0,
  last_updated INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'simple-calendar',
  availability INTEGER NOT NULL DEFAULT 0,
  access_level INTEGER NOT NULL DEFAULT 0,
  color INTEGER NOT NULL DEFAULT 0,
  type INTEGER NOT NULL DEFAULT 0,
  status INTEGER NOT NULL DEFAULT 1
);
"""
        encoded_schema = base64.b64encode(schema.encode("utf-8")).decode("ascii")
        controller.execute_adb(["shell", f"mkdir -p {quoted_dir}"])
        controller.execute_adb(["shell", f"printf %s {encoded_schema} | base64 -d | sqlite3 {quoted_db}"])
        owner_group = str(
            controller.execute_adb(["shell", f"stat -c %U:%G /data/user/0/{shlex.quote(app_package)}"])
            or ""
        ).strip()
        if owner_group:
            controller.execute_adb(["shell", f"chown {owner_group} {quoted_db} {quoted_dir}"])
        controller.execute_adb(["shell", f"chmod 700 {quoted_dir}; chmod 600 {quoted_db}"])
        controller.execute_adb(["shell", f"restorecon -R {quoted_dir}"])

    @classmethod
    def _insert_event(
        cls,
        controller: Any,
        *,
        database_path: str,
        event: Mapping[str, Any],
        timezone_name: str,
    ) -> None:
        title = str(event.get("title") or "").strip()
        start = str(event.get("start") or "").strip()
        end = str(event.get("end") or "").strip()
        if not title or not start or not end:
            raise RuntimeError(f"Seed event requires title/start/end: {event!r}")

        now_ms = int(time.time() * 1000)
        columns = (
            "start_ts,end_ts,title,location,description,reminder_1_minutes,"
            "reminder_2_minutes,reminder_3_minutes,reminder_1_type,reminder_2_type,"
            "reminder_3_type,repeat_interval,repeat_rule,repeat_limit,repetition_exceptions,"
            "attendees,import_id,time_zone,flags,event_type,parent_id,last_updated,source,"
            "availability,access_level,color,type,status"
        )
        values = [
            str(cls._datetime_to_seconds(start, timezone_name)),
            str(cls._datetime_to_seconds(end, timezone_name)),
            _sql_quote(title),
            _sql_quote(str(event.get("location") or "").strip()),
            _sql_quote(str(event.get("description") or "").strip()),
            "10",
            "-1",
            "-1",
            "0",
            "0",
            "0",
            "0",
            "0",
            "0",
            _sql_quote("[]"),
            _sql_quote("[]"),
            _sql_quote(f"helloworld-{uuid.uuid4().hex}"),
            _sql_quote(""),
            "0",
            "1",
            "0",
            str(now_ms),
            _sql_quote("simple-calendar"),
            "0",
            "0",
            "0",
            "0",
            "1",
        ]
        cls._execute_sql(
            controller,
            database_path=database_path,
            sql=f"INSERT INTO events ({columns}) VALUES ({','.join(values)});",
        )

    @staticmethod
    def _datetime_to_seconds(value: str, timezone_name: str) -> int:
        timezone = _timezone_for_name(timezone_name)
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)
        return int(parsed.timestamp())

    @staticmethod
    def _execute_sql(controller: Any, *, database_path: str, sql: str) -> str:
        encoded_sql = base64.b64encode(sql.encode("utf-8")).decode("ascii")
        command = f"printf %s {encoded_sql} | base64 -d | sqlite3 {shlex.quote(database_path)}"
        return str(controller.execute_adb(["shell", command]) or "")


def _timezone_for_name(timezone_name: str) -> dt.tzinfo:
    if ZoneInfo is not None:
        return ZoneInfo(timezone_name)
    return dt.timezone.utc


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
