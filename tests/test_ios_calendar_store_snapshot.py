import sqlite3

from platforms.ios.calendar_store import IOSCalendarStore


def test_calendar_snapshot_reads_wal_and_excludes_disabled_stores(tmp_path):
    db = tmp_path / "Calendar.sqlitedb"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE Store (ROWID INTEGER PRIMARY KEY, name TEXT, disabled INTEGER);
        CREATE TABLE Calendar (ROWID INTEGER PRIMARY KEY, store_id INTEGER);
        CREATE TABLE Location (ROWID INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE CalendarItem (
          ROWID INTEGER PRIMARY KEY, summary TEXT, location_id INTEGER,
          description TEXT, start_date REAL, end_date REAL, calendar_id INTEGER,
          entity_type INTEGER
        );
        INSERT INTO Store VALUES (1, 'Default', 0), (3, 'Subscribed Calendars', 1);
        INSERT INTO Calendar VALUES (11, 1), (33, 3);
        INSERT INTO CalendarItem VALUES
          (1, 'Visible task event', NULL, '', 800000000, 800001800, 11, 2),
          (2, 'Hidden system event', NULL, '', 800000000, 800001800, 33, 2);
        """
    )
    conn.commit()  # Keep committed rows in WAL for snapshot verification.
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()

    store = IOSCalendarStore(db, timezone_name="Asia/Singapore")
    assert [item.summary for item in store.list_events()] == [
        "Visible task event",
        "Hidden system event",
    ]
    assert [item.summary for item in store.list_events(visible_calendars_only=True)] == [
        "Visible task event",
    ]
