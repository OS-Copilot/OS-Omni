import sqlite3

from platforms.ios.calendar_store import IOSCalendarStore


def test_disable_subscribed_calendars_only_disables_external_store(tmp_path):
    db = tmp_path / "Calendar.sqlitedb"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE Store (ROWID INTEGER PRIMARY KEY, name TEXT, external_id TEXT, disabled INTEGER)"
    )
    conn.executemany(
        "INSERT INTO Store (ROWID, name, external_id, disabled) VALUES (?, ?, ?, ?)",
        [
            (1, "Default", "default", 0),
            (3, "Subscribed Calendars", "Subscribed Calendars", 0),
            (4, "Reminders", "integration:reminders", 0),
        ],
    )
    conn.commit()
    conn.close()

    store = IOSCalendarStore(str(db), timezone_name="Asia/Singapore")
    assert store.disable_subscribed_calendars() == [3]
    assert store.disable_subscribed_calendars() == [3]

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT ROWID, disabled FROM Store ORDER BY ROWID").fetchall() == [
            (1, 0),
            (3, 1),
            (4, 0),
        ]
    finally:
        conn.close()


def test_disable_subscribed_calendars_is_noop_without_external_store(tmp_path):
    db = tmp_path / "Calendar.sqlitedb"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE Store (ROWID INTEGER PRIMARY KEY, name TEXT, external_id TEXT, disabled INTEGER)"
    )
    conn.execute("INSERT INTO Store VALUES (1, 'Default', 'default', 0)")
    conn.commit()
    conn.close()

    store = IOSCalendarStore(str(db), timezone_name="Asia/Singapore")
    assert store.disable_subscribed_calendars() == []
