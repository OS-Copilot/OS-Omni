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
        assert latest.get("note") == "Bring both items together.", f"unexpected note: {latest!r}"
        assert float(latest.get("total") or 0) in {347.0, 377.0, 389.0, 407.0}, f"unexpected total: {latest!r}"
        items = latest.get("items") or []
        assert len(items) == 2, f"unexpected order items: {latest!r}"
        seen = {(item.get("product") or {}).get("id"): item for item in items}
        assert "p1001" in seen and "p1005" in seen, f"missing expected products: {seen!r}"
        assert int(seen["p1001"].get("quantity") or 0) == 1 and seen["p1001"].get("selectedSpec") == "Bluetooth 5.4", f"unexpected headphones item: {seen['p1001']!r}"
        assert int(seen["p1005"].get("quantity") or 0) == 1 and seen["p1005"].get("selectedSpec") == "20 sachets", f"unexpected coffee item: {seen['p1005']!r}"
        snippets = read_profile_text()
        expected_events = [
            ("Bench Combined Order Check", 1, 17, 0, 17, 30),
            ("Bench Coffee Restock Review", 3, 10, 0, 10, 30),
            ("Bench Dual Order Audit", 4, 14, 45, 15, 15),
            ("Bench Headphones Pairing Check", 5, 9, 15, 9, 45),
            ("Bench Coffee Sample Count", 6, 10, 45, 11, 15),
            ("Bench Invoice Bundle Review", 7, 13, 30, 14, 0),
            ("Bench Fulfillment Desk Sync", 8, 15, 0, 15, 30),
            ("Bench Cart Evidence Archive", 9, 16, 15, 16, 45),
            ("Bench Payment Receipt Review", 10, 11, 30, 12, 0),
            ("Bench Office Delivery Scan", 11, 14, 0, 14, 30),
            ("Bench Product Warranty Note", 12, 9, 45, 10, 15),
            ("Bench Coffee Pantry Sync", 13, 15, 45, 16, 15),
            ("Bench Combined Return Window Check", 14, 16, 30, 17, 0),
            ("Bench Team Gear Handoff", 15, 10, 15, 10, 45),
            ("Bench Order Metadata Audit", 16, 13, 0, 13, 30),
            ("Bench Receipt Closeout Review", 17, 14, 30, 15, 0),
            ("Bench Shipment Exception Sweep", 18, 11, 0, 11, 30),
            ("Bench Purchase Approval Archive", 19, 15, 15, 15, 45),
            ("Bench Dual Order Closeout", 20, 16, 0, 16, 30),
            ("Bench Finance Reconciliation Note", 21, 9, 30, 10, 0),
        ]
        for event in expected_events:
            assert has_event(snippets, *event), f"calendar event missing or wrong: {event[0]}"
        print("EVAL_RESULT:PASS dual checkout and 20-event calendar package verified")
        sys.exit(0)
    except Exception as exc:
        last_error = str(exc)
        time.sleep(1)

print("EVAL_RESULT:FAIL " + last_error)
'@
$tmp = Join-Path $env:TEMP "cross_app_openshop_calendar_dual_item_checkout_two_events_hard.py"
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
