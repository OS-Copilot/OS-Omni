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
                src = os.path.join(dirpath, filename)
                dst = os.path.join(tmp, filename)
                try:
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
    tokens = {local.strftime("%I:%M %p").lower().lstrip("0"), local.strftime("%H:%M").lower(), local.strftime("%Y%m%dT%H%M%S").lower()}
    try:
        utc = local.astimezone().astimezone(dt.timezone.utc)
        tokens.update({utc.strftime("%H:%M").lower(), utc.strftime("%Y%m%dT%H%M%SZ").lower()})
    except Exception:
        pass
    return tokens


def has_event(title, offset_days, hour, minute, end_hour, end_minute):
    snippets = read_profile_text()
    ctx = context_for(snippets, title)
    day = (dt.datetime.now() + dt.timedelta(days=offset_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        bool(ctx)
        and any(token in ctx for token in date_tokens(day))
        and any(token in ctx for token in time_tokens(day, hour, minute))
        and (any(token in ctx for token in ["pt30m", "30 minutes", "1800"]) or any(token in ctx for token in time_tokens(day, end_hour, end_minute)))
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
        items = cart.get("items") or []
        assert session.get("loggedIn") is True and (session.get("user") or {}).get("phone") == "13800138000", f"session mismatch: {session!r}"
        assert len(items) == 1, f"expected 1 cart item, got {items!r}"
        item = items[0]
        product = item.get("product") or {}
        assert product.get("id") == "p1005", f"unexpected product {product!r}"
        assert int(item.get("quantity") or 0) == 1, f"unexpected quantity: {item!r}"
        assert item.get("selectedSpec") == "20 sachets", f"unexpected spec: {item!r}"
        assert len(orders) == 0, f"expected no orders, got {orders!r}"
        assert has_event("Bench Coffee Cart Review", 1, 16, 30, 17, 0), "calendar event missing or wrong"
        print("EVAL_RESULT:PASS coffee cart and calendar event verified")
        sys.exit(0)
    except Exception as exc:
        last_error = str(exc)
        time.sleep(1)

print("EVAL_RESULT:FAIL " + last_error)
'@
$tmp = Join-Path $env:TEMP "cross_app_openshop_calendar_add_coffee_event_easy.py"
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
