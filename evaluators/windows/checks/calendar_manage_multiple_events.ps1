$script = @'
import datetime as dt
import os
import shutil
import sqlite3
import tempfile

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


def local_dt(value, timezone_name):
    if value is None:
        return None
    utc = dt.datetime.fromtimestamp(int(value) / 1_000_000, dt.timezone.utc)
    if timezone_name and ZoneInfo is not None:
        try:
            return utc.astimezone(ZoneInfo(str(timezone_name))).replace(tzinfo=None)
        except Exception:
            pass
    if str(timezone_name) == "America/Los_Angeles":
        return (utc + dt.timedelta(hours=-7)).replace(tzinfo=None)
    return utc.astimezone().replace(tzinfo=None)


def copy_sqlite_with_wal(src, temp_dir):
    dst = os.path.join(temp_dir, os.path.basename(src))
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        companion = src + suffix
        if os.path.exists(companion):
            shutil.copy2(companion, dst + suffix)
    return dst


def open_calendar_db():
    profile_root = os.path.expandvars(r"%APPDATA%\Thunderbird\Profiles")
    if not os.path.exists(profile_root):
        raise FileNotFoundError("Thunderbird profile root not found")
    candidates = []
    for root, _dirs, files in os.walk(profile_root):
        if "local.sqlite" in files and os.path.basename(root).lower() == "calendar-data":
            candidates.append(os.path.join(root, "local.sqlite"))
    if not candidates:
        raise FileNotFoundError("calendar-data\\local.sqlite not found")
    temp_dir = tempfile.mkdtemp(prefix="calendar_eval_")
    try:
        dst = copy_sqlite_with_wal(candidates[0], temp_dir)
        conn = sqlite3.connect(dst)
        conn.row_factory = sqlite3.Row
        return conn, temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def load_rows(conn, table):
    try:
        return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"')]
    except Exception:
        return []


def next_week_monday():
    today = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today - dt.timedelta(days=today.weekday()) + dt.timedelta(days=7)


def minutes_between(start, end):
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 60)


def event_rows(events, title):
    want = title.strip().lower()
    return [event for event in events if str(event.get("title") or "").strip().lower() == want]


def related_text(rows, event):
    item_id = event.get("id")
    cal_id = event.get("cal_id")
    return "\n".join(
        str(row.get("icalString") or "")
        for row in rows
        if row.get("item_id") == item_id and row.get("cal_id") == cal_id
    ).upper()


def check_event(events, title, day, hour, minute, duration_minutes):
    rows = event_rows(events, title)
    if not rows:
        return None, "not_found"
    reason = "date"
    for event in rows:
        start = local_dt(event.get("event_start"), event.get("event_start_tz"))
        end = local_dt(event.get("event_end"), event.get("event_end_tz"))
        if start is None or start.date() != day.date():
            continue
        reason = "start_time"
        if start.hour != hour or start.minute != minute:
            continue
        reason = "duration"
        if minutes_between(start, end) != duration_minutes:
            continue
        return event, ""
    return None, reason


conn, temp_dir = open_calendar_db()
try:
    events = load_rows(conn, "cal_events")
    recurrences = load_rows(conn, "cal_recurrence")
    alarms = load_rows(conn, "cal_alarms")
finally:
    conn.close()
    shutil.rmtree(temp_dir, ignore_errors=True)

monday = next_week_monday()
expectations = [
    ("Design Review", monday, 10, 0, 60, None, None),
    ("Backlog Triage", monday + dt.timedelta(days=1), 9, 15, 45, "TRIGGER:-PT15M", None),
    ("Sprint Planning", monday + dt.timedelta(days=2), 13, 30, 60, None, None),
    ("Launch Debrief", monday + dt.timedelta(days=3), 16, 15, 30, "TRIGGER:-PT10M", None),
    ("Retrospective", monday + dt.timedelta(days=4), 14, 30, 60, "TRIGGER:-PT30M", None),
    ("Risk Review", monday + dt.timedelta(days=4), 16, 0, 45, "TRIGGER:-PT20M", None),
    ("Ops Review Sync", monday + dt.timedelta(days=3), 9, 0, 30, None, "FREQ=WEEKLY"),
    ("Vendor Dry Run", monday + dt.timedelta(days=2), 16, 45, 30, "TRIGGER:-PT5M", None),
    ("Metrics Review", monday + dt.timedelta(days=1), 15, 0, 30, "TRIGGER:-PT10M", "FREQ=WEEKLY"),
]

missing = []
for title, day, hour, minute, duration, alarm_kw, recurrence_kw in expectations:
    event, reason = check_event(events, title, day, hour, minute, duration)
    if event is None:
        missing.append(f"{title}:{reason}")
        continue
    alarm = related_text(alarms, event)
    recurrence = related_text(recurrences, event)
    if alarm_kw and alarm_kw not in alarm:
        missing.append(f"{title}:alarm")
    if recurrence_kw and recurrence_kw not in recurrence:
        missing.append(f"{title}:recurrence")

if missing:
    print("EVAL_RESULT:FAIL next-week calendar details missing: " + "; ".join(missing))
    raise SystemExit(1)

print("EVAL_RESULT:PASS nine-event next-week calendar plan matches Linux-aligned hard task")
'@
$tmp = Join-Path $env:TEMP 'calendar_manage_multiple_events_eval.py'
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
