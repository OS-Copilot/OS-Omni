"""Helpers for reading and seeding iOS Simulator Calendar data."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time as time_value, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
DEFAULT_TIMEZONE_NAME = "Asia/Shanghai"
DEFAULT_EVENT_CALENDAR_NAME = "DEFAULT_CALENDAR_NAME"


@dataclass(frozen=True)
class CalendarEventSpec:
    summary: str
    day_offset: int
    start_time: str
    end_time: str
    location: str = ""
    description: str = ""
    exact_description: bool = False


@dataclass(frozen=True)
class CalendarEventRecord:
    rowid: int
    summary: str
    local_date: str
    start_time: str
    end_time: str
    location: str
    description: str
    calendar_id: int


def _extract_zoneinfo_name(value: Any) -> str:
    """Return ``value`` when it names a real IANA zone, else ``""``.

    Accepts bare IANA keys (``Asia/Singapore``), a leading-colon ``TZ``
    form (``:Asia/Singapore``), and absolute zoneinfo paths
    (``/usr/share/zoneinfo/America/Los_Angeles`` or the Darwin
    ``/var/db/timezone/zoneinfo/...`` target of ``/etc/localtime``).
    Anything that is not loadable via :class:`zoneinfo.ZoneInfo`
    (POSIX ``TZ`` strings, typos, empty values) is rejected so callers
    fall through to the next resolution source instead of silently
    adopting a wrong zone.
    """
    text = str(value or "").strip()
    if text.startswith(":"):
        text = text[1:].strip()
    if not text:
        return ""
    marker = "zoneinfo/"
    if marker in text:
        text = text.rsplit(marker, 1)[-1].strip()
    if not text:
        return ""
    try:
        ZoneInfo(text)
    except Exception:
        return ""
    return text


def default_timezone_name() -> str:
    # 1. Explicit host TZ environment. A valid IANA value wins because on
    #    hosts where TZ is set, datetime.astimezone().tzinfo is typically a
    #    fixed-offset tzinfo without a ``key`` (the original Shanghai
    #    fallback bug). An invalid TZ value is ignored here so resolution
    #    falls through; an invalid explicit task/initializer ``timezone``
    #    param is still rejected visibly by ZoneInfo in IOSCalendarStore.
    candidate = _extract_zoneinfo_name(os.environ.get("TZ", ""))
    if candidate:
        return candidate

    # 2. tzinfo key when the platform provides one.
    try:
        local_tz = datetime.now().astimezone().tzinfo
        candidate = _extract_zoneinfo_name(getattr(local_tz, "key", "") or "")
        if candidate:
            return candidate
    except Exception:
        pass

    # 3. /etc/localtime zoneinfo symlink (Darwin and most Unix hosts).
    #    Deliberately symlink-only: container images that copy (not link)
    #    the zone file carry no zone name, so they keep the legacy default.
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        target = ""
    candidate = _extract_zoneinfo_name(target)
    if candidate:
        return candidate

    return DEFAULT_TIMEZONE_NAME


def calendar_db_path_for_udid(udid: str) -> Path:
    resolved_udid = str(udid or "").strip()
    if not resolved_udid:
        raise ValueError("Simulator UDID is required")
    return (
        Path.home()
        / "Library"
        / "Developer"
        / "CoreSimulator"
        / "Devices"
        / resolved_udid
        / "data"
        / "Library"
        / "Calendar"
        / "Calendar.sqlitedb"
    )


def coerce_event_specs(raw: Any) -> list[CalendarEventSpec]:
    if not isinstance(raw, list):
        return []

    specs: list[CalendarEventSpec] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        summary = str(item.get("summary") or "").strip()
        start_time = str(item.get("start_time") or "").strip()
        end_time = str(item.get("end_time") or "").strip()
        if not summary or not start_time or not end_time:
            continue
        try:
            day_offset = int(item.get("day_offset", 0) or 0)
        except (TypeError, ValueError):
            continue
        specs.append(
            CalendarEventSpec(
                summary=summary,
                day_offset=day_offset,
                start_time=start_time,
                end_time=end_time,
                location=str(item.get("location") or "").strip(),
                description=str(item.get("description") or "").strip(),
                exact_description=bool(item.get("exact_description", False)),
            )
        )
    return specs


class IOSCalendarStore:
    """Read and seed Calendar events in an iOS Simulator database."""

    def __init__(self, db_path: str | Path, *, timezone_name: str | None = None):
        self.db_path = Path(db_path).expanduser().resolve()
        self.timezone_name = str(timezone_name or default_timezone_name()).strip() or DEFAULT_TIMEZONE_NAME
        self.tzinfo = ZoneInfo(self.timezone_name)

    @classmethod
    def from_simulator(
        cls,
        udid: str,
        *,
        timezone_name: str | None = None,
    ) -> "IOSCalendarStore":
        return cls(calendar_db_path_for_udid(udid), timezone_name=timezone_name)

    def purge_events_by_summaries(self, summaries: Sequence[str]) -> int:
        resolved_summaries = sorted({self._normalize_text(item) for item in summaries if self._normalize_text(item)})
        if not resolved_summaries:
            return 0

        with self._connect_writable() as conn:
            placeholders = ", ".join("?" for _ in resolved_summaries)
            rowids = [
                int(row[0])
                for row in conn.execute(
                    f"""
                    SELECT ROWID
                    FROM CalendarItem
                    WHERE entity_type = 2
                      AND summary IN ({placeholders})
                    """,
                    resolved_summaries,
                ).fetchall()
            ]
            deleted_count = self._purge_event_rowids(conn, rowids)
            conn.commit()
            return deleted_count

    def purge_all_events(self) -> int:
        with self._connect_writable() as conn:
            rowids = [
                int(row[0])
                for row in conn.execute(
                    """
                    SELECT ROWID
                    FROM CalendarItem
                    WHERE entity_type = 2
                    """
                ).fetchall()
            ]
            deleted_count = self._purge_event_rowids(conn, rowids)
            conn.commit()
            return deleted_count

    def disable_subscribed_calendars(self) -> list[int]:
        """Disable iOS's external subscription store for isolated benchmark tasks.

        Some simulator images contain an active "Subscribed Calendars" store.
        Calendar can populate it asynchronously after initialization, which
        makes an exact event-count task nondeterministic even after its events
        were purged. Call this only when a task explicitly requests isolation.
        """
        with self._connect_writable() as conn:
            store_ids = [
                int(row[0])
                for row in conn.execute(
                    """
                    SELECT ROWID
                    FROM Store
                    WHERE lower(trim(coalesce(name, ''))) = 'subscribed calendars'
                       OR lower(trim(coalesce(external_id, ''))) = 'subscribed calendars'
                    """
                ).fetchall()
            ]
            if not store_ids:
                return []
            placeholders = ", ".join("?" for _ in store_ids)
            conn.execute(
                f"UPDATE Store SET disabled = 1 WHERE ROWID IN ({placeholders})",
                store_ids,
            )
            conn.commit()
            return store_ids

    @staticmethod
    def _purge_event_rowids(conn: sqlite3.Connection, rowids: Sequence[int]) -> int:
        resolved_rowids = sorted({int(rowid) for rowid in rowids if int(rowid) > 0})
        if not resolved_rowids:
            return 0

        placeholders = ", ".join("?" for _ in resolved_rowids)
        conn.execute(
            f"DELETE FROM OccurrenceCache WHERE event_id IN ({placeholders})",
            resolved_rowids,
        )
        conn.execute(
            f"DELETE FROM CalendarItemChanges WHERE entity_type = 2 AND record IN ({placeholders})",
            resolved_rowids,
        )
        conn.execute(
            f"DELETE FROM Location WHERE item_owner_id IN ({placeholders})",
            resolved_rowids,
        )
        cursor = conn.execute(
            f"DELETE FROM CalendarItem WHERE ROWID IN ({placeholders})",
            resolved_rowids,
        )
        return int(cursor.rowcount or 0)

    def seed_events(self, events: Sequence[CalendarEventSpec] | Sequence[Mapping[str, Any]]) -> list[int]:
        resolved_events = self._coerce_seed_events(events)
        if not resolved_events:
            return []

        inserted_rowids: list[int] = []
        with self._connect_writable() as conn:
            calendar_id = self._resolve_event_calendar_id(conn)
            next_sequence_number = self._next_change_sequence_number(conn)
            now_ts = self._apple_timestamp(datetime.now(self.tzinfo))

            for spec in resolved_events:
                start_ts = self._event_timestamp(spec.day_offset, spec.start_time)
                end_ts = self._event_timestamp(spec.day_offset, spec.end_time)
                day_ts = self._local_midnight_timestamp(spec.day_offset)
                unique_identifier = str(uuid.uuid4()).upper()
                row_uuid = str(uuid.uuid4()).upper()

                cursor = conn.execute(
                    """
                    INSERT INTO CalendarItem (
                        summary,
                        location_id,
                        description,
                        start_date,
                        start_tz,
                        end_date,
                        end_tz,
                        all_day,
                        calendar_id,
                        status,
                        availability,
                        privacy_level,
                        last_modified,
                        sequence_num,
                        modified_properties,
                        unique_identifier,
                        UUID,
                        entity_type,
                        creation_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        spec.summary,
                        0,
                        spec.description,
                        start_ts,
                        self.timezone_name,
                        end_ts,
                        self.timezone_name,
                        0,
                        calendar_id,
                        0,
                        0,
                        0,
                        now_ts,
                        0,
                        13,
                        unique_identifier,
                        row_uuid,
                        2,
                        now_ts,
                    ),
                )
                rowid = int(cursor.lastrowid)

                if spec.location:
                    location_cursor = conn.execute(
                        """
                        INSERT INTO Location (title, address, item_owner_id)
                        VALUES (?, ?, ?)
                        """,
                        (spec.location, spec.location, rowid),
                    )
                    location_id = int(location_cursor.lastrowid)
                    conn.execute(
                        "UPDATE CalendarItem SET location_id = ? WHERE ROWID = ?",
                        (location_id, rowid),
                    )

                conn.execute(
                    """
                    INSERT INTO OccurrenceCache (
                        day,
                        event_id,
                        calendar_id,
                        store_id,
                        occurrence_date,
                        occurrence_start_date,
                        occurrence_end_date,
                        latest_possible_alarm,
                        earliest_possible_alarm,
                        next_reminder_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        day_ts,
                        rowid,
                        calendar_id,
                        1,
                        start_ts,
                        None,
                        end_ts,
                        None,
                        None,
                        None,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO CalendarItemChanges (
                        record,
                        type,
                        sequence_number,
                        unique_identifier,
                        UUID,
                        entity_type,
                        store_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rowid,
                        0,
                        next_sequence_number,
                        unique_identifier,
                        row_uuid,
                        2,
                        1,
                    ),
                )

                inserted_rowids.append(rowid)
                next_sequence_number += 1

            conn.commit()

        return inserted_rowids

    def list_events(
        self,
        summaries: Sequence[str] | None = None,
        *,
        visible_calendars_only: bool = False,
    ) -> list[CalendarEventRecord]:
        with self._snapshot_db_path() as snapshot_db_path:
            conn = sqlite3.connect(snapshot_db_path)
            conn.row_factory = sqlite3.Row
            try:
                where_clause = ""
                calendar_join = ""
                params: list[Any] = []
                if visible_calendars_only:
                    calendar_join = "JOIN Calendar cal ON cal.ROWID = ci.calendar_id JOIN Store st ON st.ROWID = cal.store_id"
                    where_clause = "AND COALESCE(st.disabled, 0) = 0"
                normalized_summaries = [
                    self._normalize_text(item)
                    for item in (summaries or [])
                    if self._normalize_text(item)
                ]
                if normalized_summaries:
                    placeholders = ", ".join("?" for _ in normalized_summaries)
                    where_clause = f"AND ci.summary IN ({placeholders})"
                    params.extend(normalized_summaries)

                rows = conn.execute(
                    f"""
                    SELECT
                        ci.ROWID AS rowid,
                        ci.summary AS summary,
                        COALESCE(loc.title, '') AS location,
                        COALESCE(ci.description, '') AS description,
                        ci.start_date AS start_date,
                        ci.end_date AS end_date,
                        ci.calendar_id AS calendar_id
                    FROM CalendarItem ci
                    {calendar_join}
                    LEFT JOIN Location loc ON loc.ROWID = ci.location_id
                    WHERE ci.entity_type = 2
                      AND ci.summary IS NOT NULL
                      AND ci.summary != ''
                      {where_clause}
                    ORDER BY ci.start_date ASC, ci.ROWID ASC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()

        return [self._row_to_record(row) for row in rows]

    def find_matching_events(self, specs: Sequence[CalendarEventSpec]) -> dict[str, list[CalendarEventRecord]]:
        wanted_summaries = [spec.summary for spec in specs]
        observed_by_summary: dict[str, list[CalendarEventRecord]] = {}
        for record in self.list_events(wanted_summaries):
            observed_by_summary.setdefault(record.summary, []).append(record)
        return observed_by_summary

    def event_matches_spec(self, record: CalendarEventRecord, spec: CalendarEventSpec) -> bool:
        if record.summary != spec.summary:
            return False
        expected_date = self._base_date() + timedelta(days=spec.day_offset)
        if record.local_date != expected_date.isoformat():
            return False
        if record.start_time != spec.start_time or record.end_time != spec.end_time:
            return False
        if spec.location and self._normalize_text(record.location) != self._normalize_text(spec.location):
            return False
        if spec.exact_description:
            if self._normalize_text(record.description) != self._normalize_text(spec.description):
                return False
        elif spec.description and self._normalize_text(record.description) != self._normalize_text(spec.description):
            return False
        return True

    def _row_to_record(self, row: sqlite3.Row) -> CalendarEventRecord:
        start_dt = self._apple_timestamp_to_local(float(row["start_date"] or 0.0))
        end_dt = self._apple_timestamp_to_local(float(row["end_date"] or 0.0))
        return CalendarEventRecord(
            rowid=int(row["rowid"]),
            summary=str(row["summary"] or "").strip(),
            local_date=start_dt.date().isoformat(),
            start_time=start_dt.strftime("%H:%M"),
            end_time=end_dt.strftime("%H:%M"),
            location=str(row["location"] or "").strip(),
            description=str(row["description"] or "").strip(),
            calendar_id=int(row["calendar_id"] or 0),
        )

    def _snapshot_db_path(self):
        class _SnapshotContext:
            def __init__(self, store: "IOSCalendarStore") -> None:
                self._store = store
                self._tmpdir = tempfile.TemporaryDirectory(prefix="ios_calendar_snapshot_")

            def __enter__(self) -> str:
                snapshot_root = Path(self._tmpdir.name)
                base_name = self._store.db_path.name
                if not self._store.db_path.is_file():
                    raise FileNotFoundError(self._store.db_path)
                snapshot_path = snapshot_root / base_name
                source_uri = self._store.db_path.as_uri() + "?mode=ro"
                with sqlite3.connect(source_uri, uri=True, timeout=10.0) as source:
                    source.execute("PRAGMA busy_timeout = 10000")
                    with sqlite3.connect(snapshot_path) as snapshot:
                        source.backup(snapshot, pages=256, sleep=0.01)
                return str(snapshot_path)

            def __exit__(self, exc_type, exc, tb) -> bool:
                self._tmpdir.cleanup()
                return False

        return _SnapshotContext(self)

    def _connect_writable(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout = 10000")
        # Calendar.sqlitedb ships triggers that call private SQLite functions which are
        # unavailable in a plain host-side sqlite3 connection. Stub them so benchmark
        # cleanup can safely delete previously seeded rows.
        conn.create_function("CalNoteAttachmentDeleted", 2, lambda *_args: 0)
        conn.create_function("CalNoteStoreDeleted", 3, lambda *_args: 0)
        return conn

    def _resolve_event_calendar_id(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT ROWID FROM Calendar WHERE title = ? LIMIT 1",
            (DEFAULT_EVENT_CALENDAR_NAME,),
        ).fetchone()
        if row is not None:
            return int(row[0])

        row = conn.execute(
            """
            SELECT ROWID
            FROM Calendar
            WHERE store_id = 1
            ORDER BY CASE WHEN title = 'Default' THEN 0 ELSE 1 END, ROWID ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("Could not find an event calendar in Calendar.sqlitedb")
        return int(row[0])

    def _next_change_sequence_number(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM CalendarItemChanges"
        ).fetchone()
        return int(row[0] or 1)

    def _base_date(self) -> date:
        return datetime.now(self.tzinfo).date()

    def _event_timestamp(self, day_offset: int, hhmm: str) -> float:
        parsed_time = self._parse_hhmm(hhmm)
        local_date = self._base_date() + timedelta(days=day_offset)
        local_dt = datetime.combine(local_date, parsed_time, tzinfo=self.tzinfo)
        return self._apple_timestamp(local_dt)

    def _local_midnight_timestamp(self, day_offset: int) -> float:
        local_date = self._base_date() + timedelta(days=day_offset)
        local_dt = datetime.combine(local_date, time_value(0, 0), tzinfo=self.tzinfo)
        return self._apple_timestamp(local_dt)

    @staticmethod
    def _parse_hhmm(value: str) -> time_value:
        try:
            return datetime.strptime(value, "%H:%M").time()
        except ValueError as exc:
            raise ValueError(f"Invalid time string '{value}', expected HH:MM") from exc

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _coerce_seed_events(
        events: Sequence[CalendarEventSpec] | Sequence[Mapping[str, Any]]
    ) -> list[CalendarEventSpec]:
        if not events:
            return []
        if all(isinstance(event, CalendarEventSpec) for event in events):
            return [event for event in events if isinstance(event, CalendarEventSpec)]
        return coerce_event_specs(list(events))

    @staticmethod
    def _apple_timestamp(local_dt: datetime) -> float:
        return (local_dt.astimezone(timezone.utc) - APPLE_EPOCH).total_seconds()

    def _apple_timestamp_to_local(self, value: float) -> datetime:
        return (APPLE_EPOCH + timedelta(seconds=float(value))).astimezone(self.tzinfo)
