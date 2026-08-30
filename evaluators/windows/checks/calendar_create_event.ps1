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


def load_events(conn):
    try:
        return [dict(row) for row in conn.execute('SELECT * FROM "cal_events"')]
    except Exception:
        return []


def same_date(actual, expected):
    return actual is not None and actual.date() == expected.date()


def minutes_between(start, end):
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 60)


conn, temp_dir = open_calendar_db()
try:
    events = load_events(conn)
finally:
    conn.close()
    shutil.rmtree(temp_dir, ignore_errors=True)

tomorrow = (dt.datetime.now() + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
target = None
for event in events:
    if str(event.get("title") or "").strip().lower() != "team meeting":
        continue
    start = local_dt(event.get("event_start"), event.get("event_start_tz"))
    if same_date(start, tomorrow):
        target = event
        break
    if target is None:
        target = event

missing = []
if target is None:
    missing.append("title")
else:
    start = local_dt(target.get("event_start"), target.get("event_start_tz"))
    end = local_dt(target.get("event_end"), target.get("event_end_tz"))
    if not same_date(start, tomorrow):
        missing.append("date")
    if start is None or start.hour != 14 or start.minute != 0:
        missing.append("start")
    if minutes_between(start, end) != 60:
        missing.append("duration_or_end")

if not missing:
    print("EVAL_RESULT:PASS Team Meeting event found in Thunderbird calendar")
else:
    print("EVAL_RESULT:FAIL Team Meeting event not found; missing=" + ",".join(missing))
'@
$tmp = Join-Path $env:TEMP 'calendar_create_event_eval.py'
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
