"""Helpers for directly seeding iOS Simulator Reminders data."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_BUNDLE_ID = "com.apple.reminders"
REMINDERS_APP_GROUP_PREF = "group.com.apple.reminders.plist"
REMINDERS_STORE_GLOB = "Container_v1/Stores/Data-*.sqlite"


@dataclass(frozen=True)
class ReminderRecord:
    rowid: int
    title: str
    list_name: str
    completed: bool
    marked_for_deletion: bool


def reminders_store_path_for_udid(udid: str) -> Path:
    resolved_udid = str(udid or "").strip()
    if not resolved_udid:
        raise ValueError("Simulator UDID is required")

    data_root = (
        Path.home()
        / "Library"
        / "Developer"
        / "CoreSimulator"
        / "Devices"
        / resolved_udid
        / "data"
    )
    app_group_root = data_root / "Containers" / "Shared" / "AppGroup"
    if not app_group_root.exists():
        raise FileNotFoundError(f"Reminders AppGroup root does not exist: {app_group_root}")

    candidates: list[Path] = []
    for app_group in app_group_root.iterdir():
        if not app_group.is_dir():
            continue
        if not (app_group / "Library" / "Preferences" / REMINDERS_APP_GROUP_PREF).exists():
            continue
        candidates.extend(sorted(app_group.glob(REMINDERS_STORE_GLOB)))

    if not candidates:
        candidates = sorted(app_group_root.glob(f"*/{REMINDERS_STORE_GLOB}"))

    for candidate in candidates:
        if _looks_like_reminders_store(candidate):
            return candidate

    raise FileNotFoundError(f"Could not find Reminders CoreData store under simulator {resolved_udid}")


def coerce_present_titles(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    titles: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            title = str(item.get("title") or "").strip()
        else:
            title = str(item or "").strip()
        if title:
            titles.append(title)
    return titles


class IOSReminderStore:
    """Read and seed Reminders lists in an iOS Simulator CoreData store."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()

    @classmethod
    def from_simulator(cls, udid: str) -> "IOSReminderStore":
        return cls(reminders_store_path_for_udid(udid))

    def seed_present_titles(self, *, list_name: str, present_titles: Sequence[str]) -> dict[str, Any]:
        normalized_list_name = self._normalize_text(list_name)
        if not normalized_list_name:
            raise ValueError("Reminders seed requires a non-empty list_name")

        titles = [self._normalize_text(title) for title in present_titles if self._normalize_text(title)]
        with self._connect_writable() as conn:
            list_id = self._ensure_list(conn, normalized_list_name)
            deleted_count = self._purge_list_reminders(conn, list_id)
            inserted_ids = self._seed_reminders(conn, list_id, titles)
            self._refresh_primary_key(conn, "REMCDList", "ZREMCDBASELIST")
            self._refresh_primary_key(conn, "REMCDBaseList", "ZREMCDBASELIST")
            self._refresh_primary_key(conn, "REMCDReminder", "ZREMCDREMINDER")
            conn.commit()

        return {
            "list_name": normalized_list_name,
            "deleted_count": deleted_count,
            "seeded_rowids": inserted_ids,
        }

    def list_reminders(self, list_name: str | None = None) -> list[ReminderRecord]:
        with self._snapshot_db_path() as snapshot_db_path:
            conn = sqlite3.connect(snapshot_db_path)
            conn.row_factory = sqlite3.Row
            try:
                params: list[Any] = []
                where_clause = ""
                normalized_list_name = self._normalize_text(list_name)
                if normalized_list_name:
                    where_clause = "AND l.ZNAME = ?"
                    params.append(normalized_list_name)
                rows = conn.execute(
                    f"""
                    SELECT
                        r.Z_PK AS rowid,
                        r.ZTITLE AS title,
                        COALESCE(l.ZNAME, '') AS list_name,
                        COALESCE(r.ZCOMPLETED, 0) AS completed,
                        COALESCE(r.ZMARKEDFORDELETION, 0) AS marked_for_deletion
                    FROM ZREMCDREMINDER r
                    LEFT JOIN ZREMCDBASELIST l ON l.Z_PK = r.ZLIST
                    WHERE COALESCE(r.ZTITLE, '') != ''
                      {where_clause}
                    ORDER BY r.ZLIST ASC, r.Z_FOK_LIST ASC, r.Z_PK ASC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()

        return [
            ReminderRecord(
                rowid=int(row["rowid"]),
                title=str(row["title"] or ""),
                list_name=str(row["list_name"] or ""),
                completed=bool(row["completed"]),
                marked_for_deletion=bool(row["marked_for_deletion"]),
            )
            for row in rows
        ]

    def _ensure_list(self, conn: sqlite3.Connection, list_name: str) -> int:
        row = conn.execute(
            """
            SELECT Z_PK
            FROM ZREMCDBASELIST
            WHERE Z_ENT = 3
              AND COALESCE(ZMARKEDFORDELETION, 0) = 0
              AND ZNAME = ?
            ORDER BY Z_PK DESC
            LIMIT 1
            """,
            (list_name,),
        ).fetchone()
        if row is not None:
            return int(row[0])

        account_id = self._resolve_account_id(conn)
        display_order = self._next_list_display_order(conn)
        identifier = uuid.uuid4()
        now_ts = self._apple_timestamp_now()
        cursor = conn.execute(
            """
            INSERT INTO ZREMCDBASELIST (
                Z_ENT,
                Z_OPT,
                ZCKDIRTYFLAGS,
                ZCKNEEDSINITIALFETCHFROMCLOUD,
                ZCKNEEDSTOBEFETCHEDFROMCLOUD,
                ZEFFECTIVEMINIMUMSUPPORTEDAPPVERSION,
                ZMARKEDFORDELETION,
                ZMINIMUMSUPPORTEDAPPVERSION,
                ZSHOWINGLARGEATTACHMENTS,
                ZSPOTLIGHTINDEXCOUNT,
                ZACCOUNT,
                ZCKCLOUDSTATE,
                ZDADISPLAYORDER,
                ZDAISEVENTONLYCONTAINER,
                ZDAISIMMUTABLE,
                ZDAISNOTIFICATIONSCOLLECTION,
                ZDAISREADONLY,
                ZISGROUP,
                ZISPINNEDBYCURRENTUSER,
                ZSHARINGSTATUS,
                ZSHOULDAUTOCATEGORIZEITEMS,
                ZSHOULDCATEGORIZEGROCERYITEMS,
                ZSHOULDSUGGESTCONVERSIONTOGROCERYLIST,
                ZPARENTACCOUNT,
                ZLASTUSERACCESSDATE,
                ZNAME,
                ZIDENTIFIER
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                3,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                account_id,
                1,
                display_order,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                account_id,
                now_ts,
                list_name,
                sqlite3.Binary(identifier.bytes),
            ),
        )
        return int(cursor.lastrowid)

    def _purge_list_reminders(self, conn: sqlite3.Connection, list_id: int) -> int:
        cursor = conn.execute("DELETE FROM ZREMCDREMINDER WHERE ZLIST = ?", (list_id,))
        return int(cursor.rowcount or 0)

    def _seed_reminders(self, conn: sqlite3.Connection, list_id: int, titles: Sequence[str]) -> list[int]:
        if not titles:
            return []

        account_id = self._resolve_account_id(conn)
        timezone_offset = self._local_timezone_offset_seconds()
        now_ts = self._apple_timestamp_now()
        inserted_ids: list[int] = []
        for index, title in enumerate(titles, start=1):
            identifier = uuid.uuid4()
            identifier_text = str(identifier).upper()
            cursor = conn.execute(
                """
                INSERT INTO ZREMCDREMINDER (
                    Z_ENT,
                    Z_OPT,
                    ZALLDAY,
                    ZCKDIRTYFLAGS,
                    ZCKNEEDSINITIALFETCHFROMCLOUD,
                    ZCKNEEDSTOBEFETCHEDFROMCLOUD,
                    ZCOMPLETED,
                    ZDISPLAYDATEISALLDAY,
                    ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT,
                    ZEFFECTIVEMINIMUMSUPPORTEDAPPVERSION,
                    ZFLAGGED,
                    ZICSDISPLAYORDER,
                    ZISURGENTSTATEENABLEDFORCURRENTUSER,
                    ZMARKEDFORDELETION,
                    ZMINIMUMSUPPORTEDAPPVERSION,
                    ZPRIORITY,
                    ZSPOTLIGHTINDEXCOUNT,
                    ZACCOUNT,
                    ZCKCLOUDSTATE,
                    ZLIST,
                    Z_FOK_LIST,
                    ZCREATIONDATE,
                    ZLASTMODIFIEDDATE,
                    ZDACALENDARITEMUNIQUEIDENTIFIER,
                    ZTITLE,
                    ZIDENTIFIER
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    39,
                    1,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    timezone_offset,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    account_id,
                    1,
                    list_id,
                    (index + 1) * 1024,
                    now_ts + index * 0.001,
                    now_ts + index * 0.001,
                    identifier_text,
                    title,
                    sqlite3.Binary(identifier.bytes),
                ),
            )
            inserted_ids.append(int(cursor.lastrowid))
        return inserted_ids

    @staticmethod
    def _resolve_account_id(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            """
            SELECT Z_PK
            FROM ZREMCDOBJECT
            WHERE Z_ENT = 14
              AND COALESCE(ZMARKEDFORDELETION, 0) = 0
            ORDER BY Z_PK ASC
            LIMIT 1
            """
        ).fetchone()
        if row is not None:
            return int(row[0])
        return 1

    @staticmethod
    def _next_list_display_order(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(ZDADISPLAYORDER), 0) + 1
            FROM ZREMCDBASELIST
            WHERE Z_ENT = 3
              AND COALESCE(ZMARKEDFORDELETION, 0) = 0
            """
        ).fetchone()
        return int(row[0] or 1)

    @staticmethod
    def _refresh_primary_key(conn: sqlite3.Connection, entity_name: str, table_name: str) -> None:
        row = conn.execute(f"SELECT COALESCE(MAX(Z_PK), 0) FROM {table_name}").fetchone()
        max_pk = int(row[0] or 0)
        conn.execute(
            "UPDATE Z_PRIMARYKEY SET Z_MAX = MAX(COALESCE(Z_MAX, 0), ?) WHERE Z_NAME = ?",
            (max_pk, entity_name),
        )

    def _snapshot_db_path(self):
        class _SnapshotContext:
            def __init__(self, store: "IOSReminderStore") -> None:
                self._store = store
                self._tmpdir = tempfile.TemporaryDirectory(prefix="ios_reminders_snapshot_")

            def __enter__(self) -> str:
                snapshot_root = Path(self._tmpdir.name)
                base_name = self._store.db_path.name
                for candidate in self._store.db_path.parent.glob(f"{base_name}*"):
                    if candidate.is_file():
                        shutil.copy2(candidate, snapshot_root / candidate.name)
                return str(snapshot_root / base_name)

            def __exit__(self, exc_type, exc, tb) -> bool:
                self._tmpdir.cleanup()
                return False

        return _SnapshotContext(self)

    def _connect_writable(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Reminders store does not exist: {self.db_path}")
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    @staticmethod
    def _apple_timestamp_now() -> float:
        return time.time() - 978307200.0

    @staticmethod
    def _local_timezone_offset_seconds() -> int:
        offset = datetime.now().astimezone().utcoffset()
        return int(offset.total_seconds()) if offset is not None else 0

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").strip().split())


def _looks_like_reminders_store(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name IN ('ZREMCDREMINDER', 'ZREMCDBASELIST', 'Z_PRIMARYKEY')
                """
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return {str(row[0]) for row in rows} == {"ZREMCDREMINDER", "ZREMCDBASELIST", "Z_PRIMARYKEY"}
