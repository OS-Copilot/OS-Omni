$script = @'
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request

BASE_URL = "http://127.0.0.1:4310"

def request_json(path):
    with urllib.request.urlopen(BASE_URL + path, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))

def norm(value):
    return re.sub(r"\s+", " ", str(value or "").lower())

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

INIT_LOG_NAME = "helloworld_thunderbird_calendar_init.log"
LOG_STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})")


def local_dt(value, timezone_name):
    # Thunderbird stores event times as integer microseconds since the epoch (UTC)
    # plus the event's timezone name; compare in that local time.
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
    return utc.astimezone().replace(tzinfo=None)


def calendar_db_paths():
    root = os.path.expandvars(r"%APPDATA%\Thunderbird\Profiles")
    paths = []
    for dirpath, _dirs, files in os.walk(root):
        if os.path.basename(dirpath).lower() != "calendar-data":
            continue
        for name in ("local.sqlite", "cache.sqlite"):
            if name in files:
                paths.append(os.path.join(dirpath, name))
    return paths


def load_calendar_events():
    events = []
    tmp = tempfile.mkdtemp(prefix="cross_calendar_eval_")
    try:
        for index, src in enumerate(calendar_db_paths()):
            dst_dir = os.path.join(tmp, str(index))
            os.makedirs(dst_dir)
            dst = os.path.join(dst_dir, os.path.basename(src))
            try:
                shutil.copy2(src, dst)
                for suffix in ("-wal", "-shm"):
                    if os.path.exists(src + suffix):
                        shutil.copy2(src + suffix, dst + suffix)
                conn = sqlite3.connect(dst)
                conn.row_factory = sqlite3.Row
                try:
                    events.extend(dict(row) for row in conn.execute(
                        "SELECT title, event_start, event_end, event_start_tz, event_end_tz FROM cal_events"
                    ))
                finally:
                    conn.close()
            except Exception:
                pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return events


def task_start_time():
    # The Thunderbird calendar initializer logs culture-invariant `Get-Date -Format o`
    # stamps (guest local time) to %TEMP%; the first one is the reset that starts the task.
    log_path = os.path.join(os.environ.get("TEMP") or tempfile.gettempdir(), INIT_LOG_NAME)
    try:
        with open(log_path, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                match = LOG_STAMP.match(line.strip())
                if match:
                    return dt.datetime.strptime(" ".join(match.groups()), "%Y-%m-%d %H:%M:%S")
    except OSError:
        pass
    return None


def has_event(events, title, day, hour, minute, duration_minutes=30):
    want = norm(title).strip()
    for event in events:
        if norm(event.get("title")).strip() != want:
            continue
        start = local_dt(event.get("event_start"), event.get("event_start_tz"))
        end = local_dt(event.get("event_end"), event.get("event_end_tz"))
        if start is None or end is None or start.date() != day:
            continue
        if (start.hour, start.minute) != (hour, minute):
            continue
        if round((end - start).total_seconds() / 60) == duration_minutes:
            return True
    return False


def missing_events(events, anchor, expected_events):
    return [
        title
        for title, offset_days, hour, minute in expected_events
        if not has_event(events, title, anchor + dt.timedelta(days=offset_days), hour, minute)
    ]

deadline = time.time() + 30
last_error = ""
while time.time() < deadline:
    try:
        session_payload = request_json("/api/session")
        session = session_payload.get("session") or session_payload
        cart = request_json("/api/cart")
        orders_payload = request_json("/api/orders")
        orders = orders_payload.get("orders") if isinstance(orders_payload, dict) else orders_payload
        # The OpenShop seed carries Lucas Lin's order history (TBH-LUCAS-*); only orders placed in the episode count.
        orders = [o for o in orders if not str((o or {}).get("id") or "").startswith("TBH-")]
        assert session.get("loggedIn") is True and (session.get("user") or {}).get("phone") == "13800138000", f"session mismatch: {session!r}"
        assert len(cart.get("items") or []) == 0, f"expected empty cart, got {cart!r}"
        assert float(cart.get("total") or 0) == 0.0, f"expected cart total 0, got {cart!r}"
        assert len(orders) == 1, f"expected 1 order, got {orders!r}"
        latest = orders[-1]
        assert latest.get("status") == "Awaiting Shipment", f"unexpected order status: {latest!r}"
        assert (latest.get("address") or {}).get("label") == "Office", f"unexpected address: {latest!r}"
        assert (latest.get("payment") or {}).get("id") == "wechat", f"unexpected payment id: {latest!r}"
        assert (latest.get("payment") or {}).get("label") == "WeChat Pay", f"unexpected payment label: {latest!r}"
        assert latest.get("note") == "Leave it at the front desk", f"unexpected note: {latest!r}"
        assert float(latest.get("total") or 0) in {78.0, 90.0}, f"unexpected total: {latest!r}"
        items = latest.get("items") or []
        assert len(items) == 1, f"unexpected order items: {latest!r}"
        item = items[0]
        assert (item.get("product") or {}).get("id") == "p1005", f"unexpected product: {item!r}"
        assert int(item.get("quantity") or 0) == 1, f"unexpected quantity: {item!r}"
        assert item.get("selectedSpec") == "20 sachets", f"unexpected spec: {item!r}"
        # Offsets are relative to the day the task started ("tomorrow", "N days from
        # now"); the evaluation day is an anchor too in case evaluation runs after midnight.
        started = task_start_time()
        anchors = []
        for moment in (started, dt.datetime.now()):
            if moment is not None and moment.date() not in anchors:
                anchors.append(moment.date())
        expected_events = [
            ("Bench Coffee Delivery Follow-up", 2, 9, 0),
            ("Bench Coffee Receipt Audit", 1, 15, 15),
            ("Bench Coffee Stock Review", 3, 11, 45),
            ("Bench Coffee Packaging Check", 4, 10, 15),
            ("Bench Coffee Desk Drop Confirmation", 5, 14, 0),
            ("Bench Coffee Invoice Match Review", 6, 16, 30),
            ("Bench Coffee Pantry Count Update", 7, 9, 45),
            ("Bench Coffee Vendor Thank-You Draft", 8, 13, 15),
            ("Bench Coffee Delivery Exception Scan", 9, 15, 30),
            ("Bench Coffee Budget Sync", 10, 10, 0),
            ("Bench Coffee Facility Receipt Review", 11, 11, 0),
            ("Bench Coffee Supply Follow-up Closeout", 12, 16, 0),
            ("Bench Coffee Front Desk Pickup Audit", 13, 9, 30),
            ("Bench Coffee Stockroom Label Check", 14, 14, 30),
            ("Bench Coffee Order Retention", 15, 10, 45),
            ("Bench Coffee Team Brew Inventory", 16, 13, 45),
            ("Bench Coffee Vendor Receipt Archive", 17, 15, 0),
            ("Bench Coffee Final Closeout", 18, 16, 45),
        ]
        events = load_calendar_events()
        misses = {anchor: missing_events(events, anchor, expected_events) for anchor in anchors}
        best = min(anchors, key=lambda anchor: len(misses[anchor]))
        assert not misses[best], (
            f"calendar event missing or wrong: {', '.join(misses[best])} "
            f"(30-minute events relative to {best.isoformat()}; task start {started}; {len(events)} calendar events read)"
        )
        print("EVAL_RESULT:PASS coffee checkout and 18-event calendar package verified")
        sys.exit(0)
    except Exception as exc:
        last_error = str(exc)
        time.sleep(1)

print("EVAL_RESULT:FAIL " + last_error)
'@
$tmp = Join-Path $env:TEMP "cross_app_openshop_calendar_checkout_coffee_followup_hard.py"
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
