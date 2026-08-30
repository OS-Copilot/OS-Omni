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

def read_profile_text():
    root = os.path.expandvars(r"%APPDATA%\Thunderbird\Profiles")
    snippets = []
    if not os.path.exists(root):
        return snippets
    for dirpath, _dirs, files in os.walk(root):
        for filename in files:
            fpath = os.path.join(dirpath, filename)
            if filename.endswith((".sqlite", ".sqlite-wal", ".sqlite-shm")):
                continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                    snippets.append(norm(fh.read()))
            except Exception:
                pass
    tmp = tempfile.mkdtemp(prefix="cross_calendar_eval_")
    try:
        for dirpath, _dirs, files in os.walk(root):
            for filename in files:
                if not filename.endswith(".sqlite"):
                    continue
                dst = os.path.join(tmp, filename)
                try:
                    src = os.path.join(dirpath, filename)
                    shutil.copy2(src, dst)
                    for suffix in ("-wal", "-shm"):
                        companion = src + suffix
                        if os.path.exists(companion):
                            shutil.copy2(companion, dst + suffix)
                    conn = sqlite3.connect(dst)
                    for (table,) in conn.execute("select name from sqlite_master where type='table'"):
                        try:
                            for row in conn.execute(f'SELECT * FROM "{table}"'):
                                snippets.append(norm(" ".join(str(v) for v in row if v is not None)))
                        except Exception:
                            pass
                    conn.close()
                except Exception:
                    pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return snippets

def context_for(snippets, title):
    title = title.lower()
    return "\n".join(text[max(0, i - 1500): i + 2500] for text in snippets for i in [text.find(title)] if i >= 0)

def date_tokens(day):
    return {day.strftime(fmt).lower().lstrip("0") for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%b %d", "%B %d")}

def time_tokens(day, hour, minute):
    local = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    tokens = {
        local.strftime("%I:%M %p").lower().lstrip("0"),
        local.strftime("%H:%M").lower(),
        local.strftime("%Y%m%dT%H%M%S").lower(),
    }
    try:
        utc = local.astimezone().astimezone(dt.timezone.utc)
        tokens.update({utc.strftime("%H:%M").lower(), utc.strftime("%Y%m%dT%H%M%SZ").lower()})
    except Exception:
        pass
    return tokens

def has_event(snippets, title, offset_days, hour, minute, end_hour, end_minute):
    ctx = context_for(snippets, title)
    day = (dt.datetime.now() + dt.timedelta(days=offset_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return bool(ctx) and any(t in ctx for t in date_tokens(day)) and any(t in ctx for t in time_tokens(day, hour, minute)) and (
        any(t in ctx for t in ["pt30m", "30 minutes", "1800"]) or any(t in ctx for t in time_tokens(day, end_hour, end_minute))
    )

deadline = time.time() + 30
last_error = ""
while time.time() < deadline:
    try:
        session_payload = request_json("/api/session")
        session = session_payload.get("session") or session_payload
        cart = request_json("/api/cart")
        orders_payload = request_json("/api/orders")
        orders = orders_payload.get("orders") if isinstance(orders_payload, dict) else orders_payload
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
        snippets = read_profile_text()
        expected_events = [
            ("Bench Coffee Delivery Follow-up", 2, 9, 0, 9, 30),
            ("Bench Coffee Receipt Audit", 1, 15, 15, 15, 45),
            ("Bench Coffee Stock Review", 3, 11, 45, 12, 15),
            ("Bench Coffee Packaging Check", 4, 10, 15, 10, 45),
            ("Bench Coffee Desk Drop Confirmation", 5, 14, 0, 14, 30),
            ("Bench Coffee Invoice Match Review", 6, 16, 30, 17, 0),
            ("Bench Coffee Pantry Count Update", 7, 9, 45, 10, 15),
            ("Bench Coffee Vendor Thank-You Draft", 8, 13, 15, 13, 45),
            ("Bench Coffee Delivery Exception Scan", 9, 15, 30, 16, 0),
            ("Bench Coffee Budget Sync", 10, 10, 0, 10, 30),
            ("Bench Coffee Facility Receipt Review", 11, 11, 0, 11, 30),
            ("Bench Coffee Supply Follow-up Closeout", 12, 16, 0, 16, 30),
            ("Bench Coffee Front Desk Pickup Audit", 13, 9, 30, 10, 0),
            ("Bench Coffee Stockroom Label Check", 14, 14, 30, 15, 0),
            ("Bench Coffee Order Retention", 15, 10, 45, 11, 15),
            ("Bench Coffee Team Brew Inventory", 16, 13, 45, 14, 15),
            ("Bench Coffee Vendor Receipt Archive", 17, 15, 0, 15, 30),
            ("Bench Coffee Final Closeout", 18, 16, 45, 17, 15),
        ]
        for event in expected_events:
            assert has_event(snippets, *event), f"calendar event missing or wrong: {event[0]}"
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
