$script = @'
import datetime as dt
import os
import re
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
    if str(timezone_name or "").lower() == "floating":
        return utc.replace(tzinfo=None)
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


def find_calendar_db():
    profile_root = os.path.expandvars(r"%APPDATA%\Thunderbird\Profiles")
    if not os.path.exists(profile_root):
        raise FileNotFoundError("Thunderbird profile root not found")
    candidates = []
    for root, _dirs, files in os.walk(profile_root):
        if "local.sqlite" in files and os.path.basename(root).lower() == "calendar-data":
            candidates.append(os.path.join(root, "local.sqlite"))
    if not candidates:
        raise FileNotFoundError("calendar-data\\local.sqlite not found")
    return candidates[0]


def open_calendar_db(path):
    temp_dir = tempfile.mkdtemp(prefix="calendar_eval_")
    try:
        dst = copy_sqlite_with_wal(path, temp_dir)
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


INIT_LOG_NAME = "helloworld_thunderbird_calendar_init.log"
LOG_STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})")


def task_start_time(db_path):
    """Guest-local time at which the task started, or None.

    The Thunderbird calendar initializer logs `Get-Date -Format o` stamps
    (culture-invariant, local time) to %TEMP%; its first line is the profile reset
    that starts the task.  Without the log, the creation time of the profile
    directory the initializer recreated is used (getctime is the creation time on
    Windows).
    """
    log_path = os.path.join(os.environ.get("TEMP") or tempfile.gettempdir(), INIT_LOG_NAME)
    try:
        with open(log_path, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                match = LOG_STAMP.match(line.strip())
                if match:
                    return dt.datetime.strptime(" ".join(match.groups()), "%Y-%m-%d %H:%M:%S")
    except OSError:
        pass
    try:
        return dt.datetime.fromtimestamp(os.path.getctime(os.path.dirname(os.path.dirname(db_path))))
    except (OSError, ValueError):
        return None


def next_weekday_readings(anchor, weekday):
    """Dates "next <weekday>" can mean when said on `anchor`.

    The nearest such weekday after today, or that weekday in the following
    calendar week (weeks starting Monday, or Sunday as in en-US Thunderbird).
    """
    upcoming = anchor + dt.timedelta(days=(weekday - anchor.weekday()) % 7 or 7)
    next_monday_week = anchor - dt.timedelta(days=anchor.weekday()) + dt.timedelta(days=7 + weekday)
    sunday_offset = (anchor.weekday() + 1) % 7
    next_sunday_week = anchor - dt.timedelta(days=sunday_offset) + dt.timedelta(days=7 + (weekday + 1) % 7)
    return [upcoming, next_monday_week, next_sunday_week]


def candidate_plans(anchors, weekdays):
    """One consistent reading of "next ..." for all events per anchor day and reading."""
    plans = []
    for anchor in anchors:
        readings = [next_weekday_readings(anchor, weekday) for weekday in weekdays]
        for index in range(len(readings[0])):
            plan = tuple(reading[index] for reading in readings)
            if plan not in plans:
                plans.append(plan)
    return plans


def weekly_every(recurrence_text, byday):
    """True when an RRULE repeats every week on `byday` only.

    Thunderbird's "Weekly" preset writes FREQ=WEEKLY without BYDAY (the weekday
    comes from DTSTART, which the date check pins to the right weekday); a custom
    rule writes BYDAY explicitly.
    """
    rules = re.findall(r"RRULE:([^\r\n]*)", recurrence_text) or re.findall(r"(FREQ=[^\r\n]*)", recurrence_text)
    for rule in rules:
        parts = {}
        for item in rule.strip().split(";"):
            if "=" in item:
                key, value = item.split("=", 1)
                parts[key.strip()] = value.strip()
        if parts.get("FREQ") != "WEEKLY" or parts.get("INTERVAL", "1") != "1":
            continue
        days = [day.strip() for day in parts.get("BYDAY", byday).split(",") if day.strip()]
        if days == [byday]:
            return True
    return False


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
        if start is None or start.date() != day:
            continue
        reason = "start_time"
        if start.hour != hour or start.minute != minute:
            continue
        reason = "duration"
        if minutes_between(start, end) != duration_minutes:
            continue
        return event, ""
    return None, reason


db_path = find_calendar_db()
conn, temp_dir = open_calendar_db(db_path)
try:
    events = load_rows(conn, "cal_events")
    recurrences = load_rows(conn, "cal_recurrence")
    alarms = load_rows(conn, "cal_alarms")
finally:
    conn.close()
    shutil.rmtree(temp_dir, ignore_errors=True)

# "next Tuesday/Thursday/Friday" is relative to the day the task started.  The
# evaluation can run after midnight, so the evaluation day is an anchor too; each
# anchor and reading gives one consistent set of dates for all three events.
started = task_start_time(db_path)
anchors = [moment.date() for moment in (started, dt.datetime.now()) if moment is not None]
expectations = [
    # title, weekday, hour, minute, duration, weekly BYDAY, alarm trigger
    ("Weekly Release Triage", 1, 9, 15, 45, "TU", "TRIGGER:-PT15M"),
    ("QA Sign-off", 3, 11, 0, 30, None, None),
    ("Launch Readiness Review", 4, 16, 0, 60, None, None),
]


def missing_for(plan):
    missing = []
    for (title, _weekday, hour, minute, duration, byday, alarm_kw), day in zip(expectations, plan):
        event, reason = check_event(events, title, day, hour, minute, duration)
        if event is None:
            missing.append(f"{title}:{reason}")
            continue
        recurrence = related_text(recurrences, event)
        alarm = related_text(alarms, event)
        if byday and "FREQ=WEEKLY" not in recurrence:
            missing.append(f"{title}:recurrence")
        elif byday and not weekly_every(recurrence, byday):
            missing.append(f"{title}:byday")
        if alarm_kw and alarm_kw not in alarm:
            missing.append(f"{title}:alarm")
    return missing


best = None
for plan in candidate_plans(anchors, [item[1] for item in expectations]):
    missing = missing_for(plan)
    if not missing:
        dates = ", ".join(day.isoformat() for day in plan)
        print(f"EVAL_RESULT:PASS release calendar plan matches Linux-aligned hard task ({dates})")
        raise SystemExit(0)
    if best is None or len(missing) < len(best[1]):
        best = (plan, missing)

dates = ", ".join(day.isoformat() for day in best[0])
print(
    "EVAL_RESULT:FAIL release calendar details missing: "
    + "; ".join(best[1])
    + f" (closest dates {dates}; task start {started}; anchors {[a.isoformat() for a in anchors]})"
)
raise SystemExit(1)
'@
$tmp = Join-Path $env:TEMP 'calendar_create_recurring_event_eval.py'
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
