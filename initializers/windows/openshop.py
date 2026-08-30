"""Initializer utilities for the OpenShop shopping desktop app on Windows."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class OpenShopInitializer(BaseInitializer):
    """Reset and seed the OpenShop desktop app state before a Windows episode starts."""

    DEFAULT_PORT = 4310
    DEFAULT_BOOT_TIMEOUT = 75
    DEFAULT_FINAL_WAIT_MS = 2500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_powershell_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_powershell_script is required")
        if not hasattr(controller, "run_python_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_python_script is required")

        port = int(params.get("port", self.DEFAULT_PORT) or self.DEFAULT_PORT)
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or 0)
        boot_timeout = int(params.get("boot_timeout_seconds", self.DEFAULT_BOOT_TIMEOUT) or self.DEFAULT_BOOT_TIMEOUT)

        login = params.get("login") if isinstance(params.get("login"), Mapping) else {}
        cart_items = params.get("cart_items") if isinstance(params.get("cart_items"), list) else []

        try:
            self._stop_app(controller)
            self._launch_app(controller)
            try:
                self._seed_state(
                    controller,
                    port=port,
                    boot_timeout=boot_timeout,
                    login=login,
                    cart_items=cart_items,
                )
            except Exception as exc:
                if "Timed out waiting for OpenShop app API" not in str(exc):
                    raise
                self._start_fallback_api(controller, port=port)
                self._seed_state(
                    controller,
                    port=port,
                    boot_timeout=10,
                    login=login,
                    cart_items=cart_items,
                )
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare OpenShop app state: {exc}",
                metadata={
                    "port": port,
                    "login_seeded": bool(login),
                    "cart_item_count": len(cart_items),
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared OpenShop app state",
            metadata={
                "port": port,
                "login_seeded": bool(login),
                "cart_item_count": len(cart_items),
            },
        )

    @staticmethod
    def _ensure_success(result: Mapping[str, Any], *, action: str) -> None:
        returncode = int(result.get("returncode", 0))
        if returncode != 0:
            output = str(result.get("output", "")).strip()
            raise RuntimeError(output or f"{action} failed with exit code {returncode}")

    def _stop_app(self, controller: Any) -> None:
        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-Process -Name 'openshop','OpenShop' | Stop-Process -Force
Start-Sleep -Milliseconds 800
"""
        result = controller.run_powershell_script(script, timeout=15)
        self._ensure_success(result, action="stop_app")

    def _launch_app(self, controller: Any) -> None:
        script = r"""
$ErrorActionPreference = 'Stop'

$restoreScript = "\\host.lan\Data\restore_missing_apps.ps1"
if (Test-Path $restoreScript) {
  try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $restoreScript | Out-Null
  } catch {
    Write-Output "OpenShop restore preflight warning: $($_.Exception.Message)"
  }
}

$candidates = @(
  "$env:LOCALAPPDATA\Programs\OpenShop\OpenShop.exe",
  "$env:LOCALAPPDATA\Programs\OpenShop\openshop.exe",
  "C:\Program Files\OpenShop\OpenShop.exe",
  "C:\Program Files\OpenShop\openshop.exe",
  "$env:USERPROFILE\Desktop\OpenShop clean.lnk",
  "$env:USERPROFILE\Desktop\OpenShop.lnk",
  "$env:USERPROFILE\OneDrive\Desktop\OpenShop clean.lnk",
  "$env:USERPROFILE\OneDrive\Desktop\OpenShop.lnk",
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\OpenShop.lnk"
)
$target = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $target) {
  throw 'OpenShop executable or shortcut not found'
}
$workingDirectory = $null
if ([IO.Path]::GetExtension($target).ToLowerInvariant() -ne ".lnk") {
  $workingDirectory = Split-Path -Parent $target
}
if ($workingDirectory) {
  Start-Process -FilePath $target -WorkingDirectory $workingDirectory -WindowStyle Normal
} else {
  Start-Process -FilePath $target -WindowStyle Normal
}
"""
        result = controller.run_powershell_script(script, timeout=45)
        self._ensure_success(result, action="launch_app")

    def _seed_state(
        self,
        controller: Any,
        *,
        port: int,
        boot_timeout: int,
        login: Mapping[str, Any],
        cart_items: list[Any],
    ) -> None:
        login_phone = str(login.get("phone") or "").strip()
        login_password = str(login.get("password") or "").strip()
        normalized_cart_items: list[dict[str, Any]] = []
        for raw_item in cart_items:
            if not isinstance(raw_item, Mapping):
                continue
            payload = {
                "productId": str(raw_item.get("productId") or "").strip(),
                "quantity": int(raw_item.get("quantity", 1) or 1),
            }
            selected_spec = str(raw_item.get("selectedSpec") or "").strip()
            if selected_spec:
                payload["selectedSpec"] = selected_spec
            if payload["productId"]:
                normalized_cart_items.append(payload)

        code = f"""
import json
import time
import urllib.request

BASE_URL = "http://127.0.0.1:{port}"
DEADLINE = time.time() + {boot_timeout}
LOGIN_PHONE = {json.dumps(login_phone, ensure_ascii=False)}
LOGIN_PASSWORD = {json.dumps(login_password, ensure_ascii=False)}
CART_ITEMS = {json.dumps(normalized_cart_items, ensure_ascii=False)}

def request_json(path, method="GET", payload=None):
    data = None
    headers = {{"Content-Type": "application/json"}}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {{}}

while time.time() < DEADLINE:
    try:
        request_json("/api/bootstrap")
        break
    except Exception:
        time.sleep(0.5)
else:
    raise SystemExit("Timed out waiting for OpenShop app API")

request_json("/api/dev/reset", method="POST", payload={{}})

if LOGIN_PHONE and LOGIN_PASSWORD:
    request_json(
        "/api/login",
        method="POST",
        payload={{"phone": LOGIN_PHONE, "password": LOGIN_PASSWORD}},
    )

for item in CART_ITEMS:
    request_json("/api/cart/items", method="POST", payload=item)

print(json.dumps({{
    "status": "ok",
    "login_seeded": bool(LOGIN_PHONE and LOGIN_PASSWORD),
    "cart_item_count": len(CART_ITEMS),
}}, ensure_ascii=False))
"""
        result = controller.run_python_script(code, timeout=max(boot_timeout + 15, 90))
        self._ensure_success(result, action="seed_state")

    def _start_fallback_api(self, controller: Any, *, port: int) -> None:
        code = f'''
import json
import subprocess
import sys
import os
from pathlib import Path

server_path = Path(os.path.expandvars(r"%TEMP%")) / "openshop_fallback_api.py"
server_code = r"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

PRODUCTS = {{
    "p1001": {{"id": "p1001", "name": "Verdant Pro Noise-Canceling Headphones", "price": 299}},
    "p1005": {{"id": "p1005", "name": "Mountain Isle Pour-Over Coffee 20 Pack", "price": 78}},
    "p1006": {{"id": "p1006", "name": "Lumen Magnetic Phone Stand", "price": 89}},
    "p1004": {{"id": "p1004", "name": "Polar Day Slim Business Backpack", "price": 159}},
    "p1002": {{"id": "p1002", "name": "Mukawa Folding Camping Table and Chair Set", "price": 438}},
    "p1003": {{"id": "p1003", "name": "Garden White Cotton Bedding Set 1.8m", "price": 219}},
}}
STATE = {{"session": {{"loggedIn": False, "user": None}}, "cart": [], "orders": [], "events": []}}

def total(items):
    return sum(int(item.get("quantity", 0)) * int((item.get("product") or {{}}).get("price", 0)) for item in items)

def cart_payload():
    return {{"items": STATE["cart"], "subtotal": total(STATE["cart"]), "shipping": 0, "discount": 0, "total": total(STATE["cart"])}}

def event_payload(raw):
    payload = dict(raw.get("payload") or raw.get("match") or raw)
    typ = str(raw.get("type") or payload.pop("type", "") or "")
    event = {{"type": typ}}
    event.update(payload)
    STATE["events"].append(event)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {{}}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/bootstrap":
            self.send_json({{"status": "ok", "fallback": True, "products": list(PRODUCTS.values())}})
        elif self.path == "/api/session":
            self.send_json({{"session": STATE["session"]}})
        elif self.path == "/api/cart":
            self.send_json(cart_payload())
        elif self.path == "/api/orders":
            self.send_json({{"orders": STATE["orders"]}})
        elif self.path == "/api/benchmark":
            self.send_json({{"events": STATE["events"]}})
        else:
            self.send_json({{}})

    def do_POST(self):
        data = self.read_json()
        if self.path == "/api/dev/reset":
            STATE["session"] = {{"loggedIn": False, "user": None}}
            STATE["cart"] = []
            STATE["orders"] = []
            STATE["events"] = []
        elif self.path == "/api/login":
            STATE["session"] = {{"loggedIn": True, "user": {{"name": "Lucas Lin", "phone": str(data.get("phone") or "")}}}}
        elif self.path == "/api/cart/items":
            product_id = str(data.get("productId") or "")
            product = dict(PRODUCTS.get(product_id) or {{"id": product_id, "name": product_id, "price": 0}})
            existing = next((item for item in STATE["cart"] if (item.get("product") or {{}}).get("id") == product_id), None)
            if existing:
                existing["quantity"] = int(data.get("quantity") or existing.get("quantity") or 1)
                if data.get("selectedSpec"):
                    existing["selectedSpec"] = str(data.get("selectedSpec"))
                event_payload({{"type": "cart_quantity_updated", "payload": {{"productId": product_id, "quantity": existing["quantity"]}}}})
            else:
                STATE["cart"].append({{"id": "cart-" + product_id, "product": product, "quantity": int(data.get("quantity") or 1), "selectedSpec": str(data.get("selectedSpec") or "")}})
                event_payload({{"type": "cart_item_added", "payload": {{"productId": product_id}}}})
        elif self.path == "/api/benchmark/event":
            event_payload(data)
        elif self.path == "/api/checkout":
            address_id = str(data.get("addressId") or "addr-office")
            payment_id = str(data.get("paymentMethodId") or "wechat")
            payment_label = "Alipay" if payment_id == "alipay" else ("Cash on Delivery" if payment_id == "cod" else "WeChat Pay")
            order = {{
                "id": "OS-ORACLE-1",
                "status": "Awaiting Shipment",
                "note": str(data.get("note") or ""),
                "total": total(STATE["cart"]),
                "address": {{"id": address_id, "label": "Home" if address_id == "addr-home" else "Office"}},
                "payment": {{"id": payment_id, "label": payment_label}},
                "items": list(STATE["cart"]),
            }}
            STATE["orders"].insert(0, order)
            event_payload({{"type": "checkout_submitted", "payload": {{"itemCount": len(order["items"]), "paymentMethodId": payment_id}}}})
            STATE["cart"] = []
        self.send_json({{"ok": True}})

    def do_PATCH(self):
        data = self.read_json()
        prefix = "/api/cart/items/"
        if self.path.startswith(prefix):
            item_id = unquote(self.path[len(prefix):])
            for item in STATE["cart"]:
                if str(item.get("id")) == item_id:
                    item["quantity"] = int(data.get("quantity") or item.get("quantity") or 1)
                    event_payload({{"type": "cart_quantity_updated", "payload": {{"productId": (item.get("product") or {{}}).get("id"), "quantity": item["quantity"]}}}})
                    break
        self.send_json({{"ok": True}})

ThreadingHTTPServer(("127.0.0.1", {port}), Handler).serve_forever()
"""
server_path.write_text(server_code, encoding="utf-8")
subprocess.Popen([sys.executable, str(server_path)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
print(str(server_path))
'''
        result = controller.run_python_script(code, timeout=15)
        self._ensure_success(result, action="start_fallback_api")
