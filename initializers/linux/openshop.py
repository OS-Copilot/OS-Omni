"""Initializer utilities for the OpenShop shopping desktop app."""

from __future__ import annotations

import json
import shlex
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class OpenShopInitializer(BaseInitializer):
    """Reset and seed the OpenShop app state before a Linux episode starts."""

    DEFAULT_APP_COMMAND = "openshop"
    DEFAULT_PORT = 4310
    DEFAULT_BOOT_TIMEOUT = 30
    DEFAULT_FINAL_WAIT_MS = 3500
    MODERN_GUEST_APP_DIR = "/tmp/helloworld_openshop_current"
    MODERN_GUEST_ARCHIVE = "/tmp/helloworld_openshop_current.tgz"
    MODERN_GUEST_SERVER = "/tmp/helloworld_openshop_current_server.py"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        requested_app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        port = int(params.get("port", self.DEFAULT_PORT) or self.DEFAULT_PORT)
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        boot_timeout = int(params.get("boot_timeout_seconds", self.DEFAULT_BOOT_TIMEOUT) or self.DEFAULT_BOOT_TIMEOUT)

        login = params.get("login") if isinstance(params.get("login"), Mapping) else {}
        cart_items = params.get("cart_items") if isinstance(params.get("cart_items"), list) else []
        cleanup_paths = params.get("cleanup_paths") if isinstance(params.get("cleanup_paths"), list) else []
        seed_files = params.get("seed_files") if isinstance(params.get("seed_files"), list) else []
        benchmark_mode = str(params.get("benchmark_mode") or "").strip()
        require_benchmark_api = bool(params.get("require_benchmark_api", False))

        try:
            app_command = self._resolve_app_command(controller, requested_app_command)
            self._stop_app(controller, app_command)
            self._cleanup_paths(controller, cleanup_paths)
            if require_benchmark_api:
                self._deploy_and_launch_current_app(controller, port=port)
                app_command = "openshop-current-source"
            else:
                self._launch_app(controller, app_command)
            self._seed_state(
                controller,
                port=port,
                boot_timeout=boot_timeout,
                login=login,
                cart_items=cart_items,
                benchmark_mode=benchmark_mode,
                require_benchmark_api=require_benchmark_api,
            )
            self._write_seed_files(controller, seed_files)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare OpenShop app state: {exc}",
                metadata={
                    "app_command": app_command,
                    "port": port,
                    "login_seeded": bool(login),
                    "cart_item_count": len(cart_items),
                    "cleanup_path_count": len(cleanup_paths),
                    "seed_file_count": len(seed_files),
                    "requested_app_command": requested_app_command,
                    "benchmark_mode": benchmark_mode,
                    "require_benchmark_api": require_benchmark_api,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared OpenShop app state",
            metadata={
                "app_command": app_command,
                "port": port,
                "login_seeded": bool(login),
                "cart_item_count": len(cart_items),
                "cleanup_path_count": len(cleanup_paths),
                "seed_file_count": len(seed_files),
                "requested_app_command": requested_app_command,
                "benchmark_mode": benchmark_mode,
                "require_benchmark_api": require_benchmark_api,
            },
        )

    @staticmethod
    def _run(controller: Any, script: str, *, timeout: int) -> Mapping[str, Any]:
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        if returncode != 0:
            output = str(result.get("output", "")).strip()
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        return result

    def _stop_app(self, controller: Any, app_command: str) -> None:
        commands = [app_command, self.DEFAULT_APP_COMMAND]
        quoted_commands = []
        for command in commands:
            normalized = str(command or "").strip()
            if normalized and normalized not in quoted_commands:
                quoted_commands.append(normalized)
        self._run(
            controller,
            "\n".join(
                [f"pkill -TERM -f {shlex.quote(command)} || true" for command in quoted_commands]
                + ["sleep 1"]
                + [f"pkill -KILL -f {shlex.quote(command)} || true" for command in quoted_commands]
                + ["sleep 1"]
            ),
            timeout=15,
        )

    def _resolve_app_command(self, controller: Any, requested_app_command: str) -> str:
        candidates = [requested_app_command, self.DEFAULT_APP_COMMAND]
        seen: list[str] = []
        for candidate in candidates:
            command = str(candidate or "").strip()
            if not command or command in seen:
                continue
            seen.append(command)
            result = controller.run_bash_script(f"command -v {shlex.quote(command)} >/dev/null 2>&1", timeout=10)
            if int(result.get("returncode", -1)) == 0:
                return command
        raise RuntimeError(
            f"could not find OpenShop executable; checked: {', '.join(seen)}"
        )

    def _launch_app(self, controller: Any, app_command: str) -> None:
        launch_script = "\n".join(
            [
                "export DISPLAY=${DISPLAY:-:0}",
                "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
                'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
                'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
                f"setsid -f bash -lc {shlex.quote(app_command)} >/dev/null 2>&1",
            ]
        )
        self._run(controller, launch_script, timeout=15)

    def _deploy_and_launch_current_app(self, controller: Any, *, port: int) -> None:
        if not hasattr(controller, "upload_file"):
            raise RuntimeError("controller.upload_file is required to deploy the current OpenShop build")

        source_dir = Path(__file__).resolve().parents[2] / "apps" / "openshop"
        if not source_dir.exists():
            raise RuntimeError(f"OpenShop source directory not found: {source_dir}")

        with tempfile.NamedTemporaryFile(suffix=".tgz") as archive:
            with tarfile.open(archive.name, "w:gz") as tar:
                for relative_name in (
                    "public",
                    "shared",
                ):
                    path = source_dir / relative_name
                    if path.exists():
                        tar.add(path, arcname=relative_name)
            controller.upload_file(archive.name, self.MODERN_GUEST_ARCHIVE)

        with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8") as server_file:
            server_file.write(self._current_server_source())
            server_file.flush()
            controller.upload_file(server_file.name, self.MODERN_GUEST_SERVER)

        guest_dir = shlex.quote(self.MODERN_GUEST_APP_DIR)
        guest_archive = shlex.quote(self.MODERN_GUEST_ARCHIVE)
        guest_server = shlex.quote(self.MODERN_GUEST_SERVER)
        launch_script = "\n".join(
            [
                "export DISPLAY=${DISPLAY:-:0}",
                "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
                'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
                'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
                f"pkill -TERM -f {shlex.quote(self.MODERN_GUEST_APP_DIR + '/server.js')} || true",
                f"pkill -TERM -f {shlex.quote(self.MODERN_GUEST_APP_DIR + '/openshop_current_server.py')} || true",
                "sleep 1",
                f"rm -rf {guest_dir}",
                f"mkdir -p {guest_dir}",
                f"tar -xzf {guest_archive} -C {guest_dir}",
                f"cp {guest_server} {guest_dir}/openshop_current_server.py",
                f"cd {guest_dir}",
                f"export PORT={int(port)}",
                "nohup python3 openshop_current_server.py >/tmp/helloworld_openshop_current.log 2>&1 &",
                "for i in $(seq 1 40); do curl -fsS http://127.0.0.1:${PORT:-4310}/api/bootstrap >/dev/null && break; sleep 0.5; done",
                "if ! curl -fsS http://127.0.0.1:${PORT:-4310}/api/benchmark >/dev/null; then cat /tmp/helloworld_openshop_current.log >&2 || true; exit 1; fi",
                "url=http://127.0.0.1:${PORT:-4310}/",
                "browser_cmd=''",
                "for candidate in google-chrome chromium-browser chromium firefox xdg-open; do if command -v \"$candidate\" >/dev/null 2>&1; then browser_cmd=\"$candidate\"; break; fi; done",
                "if [ -z \"$browser_cmd\" ]; then echo 'no browser command available for OpenShop current-source launch' >&2; exit 1; fi",
                'setsid -f "$browser_cmd" "$url" >/dev/null 2>&1 || true',
                "sleep 2",
            ]
        )
        self._run(controller, launch_script, timeout=120)

    @staticmethod
    def _current_server_source() -> str:
        return r'''from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
SEED = json.loads((ROOT / "shared" / "seed-data.json").read_text(encoding="utf-8"))

app = Flask(__name__, static_folder=None)


def clone(value):
    return copy.deepcopy(value)


def create_state():
    return {
        "session": {"loggedIn": False, "user": None},
        "addresses": clone(SEED["addresses"]),
        "paymentMethods": clone(SEED["paymentMethods"]),
        "cart": [],
        "orders": [],
        "benchmarkMode": None,
        "benchmarkEvents": [],
        "benchmarkEventSeq": 0,
        "benchmarkCheckoutState": {
            "addressId": "addr-office",
            "paymentMethodId": "wechat",
            "note": "",
        },
        "cartSeq": 0,
    }


STATE = create_state()


def reset_state():
    fresh = create_state()
    STATE.clear()
    STATE.update(fresh)


def record_event(event_type, payload=None):
    event_type = str(event_type or "").strip()
    if not event_type:
        return None
    STATE["benchmarkEventSeq"] += 1
    event = {
        "seq": STATE["benchmarkEventSeq"],
        "type": event_type,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if isinstance(payload, dict):
        event.update(clone(payload))
    STATE["benchmarkEvents"].append(event)
    STATE["benchmarkEvents"] = STATE["benchmarkEvents"][-400:]
    return event


def find_product(product_id):
    product_id = str(product_id or "")
    return next((item for item in SEED["products"] if str(item.get("id")) == product_id), None)


def find_cart_item(product_id):
    product_id = str(product_id or "")
    return next((entry for entry in STATE["cart"] if str(entry.get("productId")) == product_id), None)


def has_event(event_type, matcher=None):
    matcher = matcher or {}
    for event in STATE["benchmarkEvents"]:
        if str(event.get("type") or "") != str(event_type or ""):
            continue
        if all(str(event.get(key) or "") == str(value or "") for key, value in matcher.items()):
            return True
    return False


def calc_cart_totals():
    items = []
    for entry in STATE["cart"]:
        product = find_product(entry.get("productId"))
        if not product:
            continue
        items.append({
            "id": entry["id"],
            "quantity": int(entry.get("quantity") or 1),
            "selectedSpec": entry.get("selectedSpec") or product["specs"][0],
            "product": clone(product),
        })
    subtotal = sum(float(item["product"]["price"]) * int(item["quantity"]) for item in items)
    shipping = 12 if items else 0
    discount = 30 if subtotal >= 300 else 0
    total = subtotal + shipping - discount
    return {"items": items, "subtotal": subtotal, "shipping": shipping, "discount": discount, "total": total}


def ensure_logged_in():
    if not STATE["session"].get("loggedIn"):
        return jsonify({"error": "LOGIN_REQUIRED"}), 401
    return None


def build_order(address_id, payment_method_id, note):
    address = next((item for item in STATE["addresses"] if str(item.get("id")) == str(address_id or "")), None)
    payment = next((item for item in STATE["paymentMethods"] if str(item.get("id")) == str(payment_method_id or "")), None)
    totals = calc_cart_totals()
    if not address or not payment:
        return {"error": "CHECKOUT_SELECTION_MISSING"}
    if not totals["items"]:
        return {"error": "EMPTY_CART"}
    return {
        "order": {
            "id": f"TB{int(time.time() * 1000)}",
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "address": clone(address),
            "payment": clone(payment),
            "note": str(note or "").strip(),
            "items": clone(totals["items"]),
            "total": totals["total"],
            "status": "Awaiting Shipment",
        },
        "totals": totals,
    }


@app.get("/api/bootstrap")
def api_bootstrap():
    return jsonify({
        "session": STATE["session"],
        "categories": SEED["categories"],
        "addresses": STATE["addresses"],
        "paymentMethods": STATE["paymentMethods"],
        "benchmarkMode": STATE["benchmarkMode"],
        "benchmarkCheckoutState": STATE["benchmarkCheckoutState"],
        "featured": SEED["products"][:4],
        "flashSale": SEED["products"][2:6],
    })


@app.get("/api/products")
def api_products():
    query = str(request.args.get("q", "")).strip().lower()
    category = str(request.args.get("category", "All")).strip()
    sort = str(request.args.get("sort", "default")).strip()
    products = list(SEED["products"])
    if category and category != "All":
        products = [item for item in products if item.get("category") == category]
    if query:
        products = [
            item for item in products
            if query in " ".join(str(item.get(key, "")) for key in ("title", "summary", "detail", "category", "badge")).lower()
        ]
    if sort == "priceAsc":
        products.sort(key=lambda item: float(item.get("price") or 0))
    elif sort == "priceDesc":
        products.sort(key=lambda item: float(item.get("price") or 0), reverse=True)
    elif sort == "sales":
        products.sort(key=lambda item: float(item.get("sales") or 0), reverse=True)
    if query or category != "All" or sort != "default":
        record_event("catalog_view", {"query": query, "category": category, "sort": sort, "total": len(products)})
    return jsonify({"products": products, "total": len(products)})


@app.get("/api/products/<product_id>")
def api_product(product_id):
    product = find_product(product_id)
    if not product:
        return jsonify({"error": "PRODUCT_NOT_FOUND"}), 404
    record_event("product_view", {"productId": product["id"], "title": product["title"]})
    return jsonify({"product": product})


@app.get("/api/session")
def api_session():
    return jsonify({"session": STATE["session"]})


@app.post("/api/login")
def api_login():
    body = request.get_json(silent=True) or {}
    account = SEED["benchmarkAccount"]
    phone = str(body.get("phone") or "").strip()
    password = str(body.get("password") or "").strip()
    if not phone or not password:
        return jsonify({"error": "MISSING_FIELDS"}), 400
    if phone != account["phone"] or password != account["password"]:
        return jsonify({"error": "INVALID_CREDENTIALS"}), 401
    STATE["session"] = {"loggedIn": True, "user": {"name": account["name"], "phone": account["phone"]}}
    record_event("session_login_success", {"phone": account["phone"]})
    return jsonify({"session": STATE["session"]})


@app.post("/api/logout")
def api_logout():
    reset_state()
    return jsonify({"session": STATE["session"]})


@app.post("/api/dev/reset")
def api_dev_reset():
    body = request.get_json(silent=True) or {}
    reset_state()
    mode = str(body.get("benchmarkMode") or "").strip()
    STATE["benchmarkMode"] = mode or None
    return jsonify({
        "ok": True,
        "session": STATE["session"],
        "cart": STATE["cart"],
        "orders": STATE["orders"],
        "benchmarkMode": STATE["benchmarkMode"],
    })


@app.get("/api/benchmark")
def api_benchmark():
    return jsonify({
        "benchmarkMode": STATE["benchmarkMode"],
        "events": STATE["benchmarkEvents"],
        "checkoutState": STATE["benchmarkCheckoutState"],
    })


@app.post("/api/benchmark/event")
def api_benchmark_event():
    body = request.get_json(silent=True) or {}
    event = record_event(body.get("type"), body.get("payload") if isinstance(body.get("payload"), dict) else {})
    if not event:
        return jsonify({"error": "BENCHMARK_EVENT_TYPE_REQUIRED"}), 400
    return jsonify({"ok": True, "event": event}), 201


@app.post("/api/benchmark/cart-review/advance")
def api_benchmark_cart_review_advance():
    stages = [
        ("p1001", 2, "headphones_to_2"),
        ("p1001", 1, "headphones_to_1"),
        ("p1005", 2, "coffee_to_2"),
        ("p1005", 1, "coffee_to_1"),
        ("p1006", 2, "stand_to_2"),
        ("p1006", 1, "stand_to_1"),
    ]
    for product_id, quantity, stage in stages:
        item = find_cart_item(product_id)
        if not item:
            return jsonify({"ok": False, "advanced": False, "reason": "missing_required_cart_item"}), 409
        if not has_event("cart_quantity_updated", {"productId": product_id, "quantity": quantity}):
            item["quantity"] = quantity
            record_event("cart_quantity_updated", {
                "productId": product_id,
                "quantity": quantity,
                "selectedSpec": item.get("selectedSpec"),
            })
            return jsonify({"ok": True, "advanced": True, "stage": stage, "cart": calc_cart_totals()})
    return jsonify({"ok": True, "advanced": False, "done": True, "stage": "complete", "cart": calc_cart_totals()})


@app.post("/api/benchmark/checkout/advance")
def api_benchmark_checkout_advance():
    stages = [
        ("checkout_address_selected", "addressId", "addr-home", "address_home"),
        ("checkout_address_selected", "addressId", "addr-office", "address_office"),
        ("checkout_payment_selected", "paymentMethodId", "alipay", "payment_alipay"),
        ("checkout_payment_selected", "paymentMethodId", "wechat", "payment_wechat"),
    ]
    if not STATE["session"].get("loggedIn"):
        return jsonify({"ok": False, "advanced": False, "error": "LOGIN_REQUIRED"}), 409
    if not calc_cart_totals()["items"]:
        return jsonify({"ok": False, "advanced": False, "error": "EMPTY_CART"}), 409
    for event_type, key, value, stage in stages:
        if not has_event(event_type, {key: value}):
            if key == "addressId":
                STATE["benchmarkCheckoutState"]["addressId"] = value
            else:
                STATE["benchmarkCheckoutState"]["paymentMethodId"] = value
            record_event(event_type, {key: value})
            return jsonify({"ok": True, "advanced": True, "stage": stage, "cart": calc_cart_totals()})
    if str(STATE["benchmarkCheckoutState"].get("note") or "").strip() != "Bring both items together":
        STATE["benchmarkCheckoutState"]["note"] = "Bring both items together"
        return jsonify({"ok": True, "advanced": True, "stage": "note_ready", "cart": calc_cart_totals()})
    built = build_order(
        STATE["benchmarkCheckoutState"]["addressId"],
        STATE["benchmarkCheckoutState"]["paymentMethodId"],
        STATE["benchmarkCheckoutState"]["note"],
    )
    if built.get("error"):
        return jsonify({"ok": False, "advanced": False, "error": built["error"]}), 409
    order = built["order"]
    STATE["orders"].insert(0, order)
    STATE["cart"] = []
    record_event("checkout_submitted", {
        "orderId": order["id"],
        "addressId": order["address"]["id"],
        "addressLabel": order["address"]["label"],
        "paymentMethodId": order["payment"]["id"],
        "paymentLabel": order["payment"]["label"],
        "note": order["note"],
        "total": order["total"],
        "itemCount": len(order["items"]),
    })
    return jsonify({"ok": True, "advanced": True, "done": True, "stage": "submitted", "order": order})


@app.get("/api/cart")
def api_cart():
    return jsonify(calc_cart_totals())


@app.post("/api/cart/items")
def api_add_cart_item():
    body = request.get_json(silent=True) or {}
    product_id = str(body.get("productId") or "").strip()
    product = find_product(product_id)
    if not product:
        return jsonify({"error": "PRODUCT_NOT_FOUND"}), 404
    quantity = max(1, int(float(body.get("quantity") or 1)))
    selected_spec = str(body.get("selectedSpec") or "").strip() or product["specs"][0]
    existing = next((entry for entry in STATE["cart"] if entry["productId"] == product_id and entry["selectedSpec"] == selected_spec), None)
    if existing:
        existing["quantity"] += quantity
        cart_id = existing["id"]
    else:
        STATE["cartSeq"] += 1
        cart_id = f"cart-{STATE['cartSeq']}"
        STATE["cart"].append({"id": cart_id, "productId": product_id, "quantity": quantity, "selectedSpec": selected_spec})
    cart_item = next((entry for entry in STATE["cart"] if entry["id"] == cart_id), None)
    record_event("cart_item_added", {
        "productId": product_id,
        "title": product["title"],
        "quantity": quantity,
        "selectedSpec": selected_spec,
        "cartQuantity": cart_item["quantity"] if cart_item else quantity,
    })
    return jsonify(calc_cart_totals()), 201


@app.patch("/api/cart/items/<cart_id>")
def api_patch_cart_item(cart_id):
    body = request.get_json(silent=True) or {}
    item = next((entry for entry in STATE["cart"] if entry["id"] == cart_id), None)
    if not item:
        return jsonify({"error": "CART_ITEM_NOT_FOUND"}), 404
    item["quantity"] = max(1, int(float(body.get("quantity") or 1)))
    record_event("cart_quantity_updated", {
        "productId": item["productId"],
        "quantity": item["quantity"],
        "selectedSpec": item.get("selectedSpec"),
    })
    return jsonify(calc_cart_totals())


@app.delete("/api/cart/items/<cart_id>")
def api_delete_cart_item(cart_id):
    removed = next((entry for entry in STATE["cart"] if entry["id"] == cart_id), None)
    STATE["cart"] = [entry for entry in STATE["cart"] if entry["id"] != cart_id]
    if removed:
        record_event("cart_item_removed", {
            "productId": removed["productId"],
            "quantity": removed["quantity"],
            "selectedSpec": removed.get("selectedSpec"),
        })
    return jsonify(calc_cart_totals())


@app.post("/api/checkout")
def api_checkout():
    blocked = ensure_logged_in()
    if blocked:
        return blocked
    body = request.get_json(silent=True) or {}
    built = build_order(body.get("addressId"), body.get("paymentMethodId"), body.get("note"))
    if built.get("error"):
        return jsonify({"error": built["error"]}), 400
    order = built["order"]
    STATE["orders"].insert(0, order)
    STATE["cart"] = []
    record_event("checkout_submitted", {
        "orderId": order["id"],
        "addressId": order["address"]["id"],
        "addressLabel": order["address"]["label"],
        "paymentMethodId": order["payment"]["id"],
        "paymentLabel": order["payment"]["label"],
        "note": order["note"],
        "total": order["total"],
        "itemCount": len(order["items"]),
    })
    return jsonify({"order": order}), 201


@app.get("/api/orders")
def api_orders():
    blocked = ensure_logged_in()
    if blocked:
        return blocked
    return jsonify({"orders": STATE["orders"]})


@app.get("/")
def root():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(PUBLIC_DIR, path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "4310")), debug=False, use_reloader=False)
'''

    def _seed_state(
        self,
        controller: Any,
        *,
        port: int,
        boot_timeout: int,
        login: Mapping[str, Any],
        cart_items: list[Any],
        benchmark_mode: str,
        require_benchmark_api: bool,
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

        script = f"""python3 - <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:{port}"
DEADLINE = time.time() + {boot_timeout}
LOGIN_PHONE = {json.dumps(login_phone, ensure_ascii=False)}
LOGIN_PASSWORD = {json.dumps(login_password, ensure_ascii=False)}
CART_ITEMS = {json.dumps(normalized_cart_items, ensure_ascii=False)}
BENCHMARK_MODE = {json.dumps(benchmark_mode, ensure_ascii=False)}
REQUIRE_BENCHMARK_API = {require_benchmark_api!r}


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

reset_payload = {{}}
if BENCHMARK_MODE:
    reset_payload["benchmarkMode"] = BENCHMARK_MODE
request_json("/api/dev/reset", method="POST", payload=reset_payload)

if REQUIRE_BENCHMARK_API:
    try:
        benchmark_payload = request_json("/api/benchmark")
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"OpenShop benchmark API is required but unavailable: HTTP {{exc.code}} for /api/benchmark. "
            "Install or launch the current OpenShop build."
        )
    if BENCHMARK_MODE and benchmark_payload.get("benchmarkMode") != BENCHMARK_MODE:
        raise SystemExit(
            f"OpenShop benchmark mode mismatch: expected {{BENCHMARK_MODE!r}}, "
            f"got {{benchmark_payload.get('benchmarkMode')!r}}"
        )

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
PY"""
        self._run(controller, script, timeout=max(boot_timeout + 10, 30))

    def _cleanup_paths(self, controller: Any, cleanup_paths: list[Any]) -> None:
        normalized = [str(path).strip() for path in cleanup_paths if str(path).strip()]
        if not normalized:
            return

        script = f"""python3 - <<'PY'
import json
import shutil
from pathlib import Path

paths = json.loads({json.dumps(json.dumps(normalized, ensure_ascii=False))})
for raw_path in paths:
    path = Path(str(raw_path))
    if not path.is_absolute():
        raise SystemExit(f"cleanup path must be absolute: {{path}}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
print(json.dumps({{"cleanup_path_count": len(paths)}}, ensure_ascii=False))
PY"""
        self._run(controller, script, timeout=30)

    def _write_seed_files(self, controller: Any, seed_files: list[Any]) -> None:
        normalized: list[dict[str, str]] = []
        for raw_file in seed_files:
            if not isinstance(raw_file, Mapping):
                continue
            path = str(raw_file.get("path") or "").strip()
            if not path:
                continue
            normalized.append(
                {
                    "path": path,
                    "content": str(raw_file.get("content") or ""),
                }
            )
        if not normalized:
            return

        script = f"""python3 - <<'PY'
import json
from pathlib import Path

files = json.loads({json.dumps(json.dumps(normalized, ensure_ascii=False))})
for item in files:
    path = Path(str(item.get("path") or ""))
    if not path.is_absolute():
        raise SystemExit(f"seed file path must be absolute: {{path}}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(item.get("content") or ""), encoding="utf-8")
print(json.dumps({{"seed_file_count": len(files)}}, ensure_ascii=False))
PY"""
        self._run(controller, script, timeout=30)
