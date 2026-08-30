"""Android OpenShop helpers for benchmark initializers and evaluators."""

from __future__ import annotations

import base64
import json
import os
import random
import socket
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse
from urllib.request import urlopen

from platforms.android.bench_storage_support import clear_and_launch_app, ensure_app_installed
from platforms.android.bootstrap import AndroidBootstrapDriver


DEFAULT_APP_PACKAGE = "com.killt.openshop"
DEFAULT_APP_ACTIVITY = "com.killt.openshop.MainActivity"
DEFAULT_WAIT_MS = 1800
LOCAL_STATE_KEY = "openshop.localState.v1"
DEFAULT_SEED_DATA_PATH = Path(__file__).resolve().parents[2] / "apps" / "openshop" / "public" / "seed-data.js"
DEFAULT_LEVELDB_PATH_TEMPLATE = "/data/user/0/{app_package}/app_webview/Default/Local Storage/leveldb"


@dataclass(frozen=True)
class OpenShopCartItemSpec:
    product_id: str
    quantity: int
    selected_spec: str = ""


def coerce_cart_item_specs(raw: Any) -> list[OpenShopCartItemSpec]:
    if not isinstance(raw, list):
        return []

    specs: list[OpenShopCartItemSpec] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        product_id = str(item.get("product_id") or "").strip()
        if not product_id:
            continue
        try:
            quantity = max(1, int(item.get("quantity", 1) or 1))
        except (TypeError, ValueError):
            continue
        specs.append(
            OpenShopCartItemSpec(
                product_id=product_id,
                quantity=quantity,
                selected_spec=str(item.get("selected_spec") or "").strip(),
            )
        )
    return specs


def prepare_fresh_openshop(
    controller: Any,
    *,
    app_package: str = DEFAULT_APP_PACKAGE,
    app_activity: str = DEFAULT_APP_ACTIVITY,
    clear_app_data: bool = True,
    wait_ms: int = DEFAULT_WAIT_MS,
) -> dict[str, Any]:
    ensure_app_installed(controller, app_package, label="OpenShop")
    clear_and_launch_app(
        controller,
        app_package=app_package,
        app_activity=app_activity,
        clear_app_data=clear_app_data,
        wait_ms=wait_ms,
    )

    driver = AndroidBootstrapDriver(controller, expected_package=app_package, settle_delay_seconds=0.4)
    # OpenShop is a WebView app; on some emulator builds uiautomator exposes only
    # the WebView root even when the page is ready. The app state is reset by
    # clearing app data above, so a missing accessibility text node should not
    # fail initialization by itself.
    try:
        driver.wait_for_node(
            [
                {"text": "OpenShop"},
                {"text": "OpenShop"},
                {"text_contains": "Verdant Pro"},
                {"text": "Search"},
                {"text": "Cart"},
                {"resource_id": f"{app_package}:id/webview"},
            ],
            timeout_seconds=12.0,
        )
    except RuntimeError:
        time.sleep(1.0)
    return {
        "app_package": app_package,
        "app_activity": app_activity,
        "clear_app_data": clear_app_data,
        "wait_ms": wait_ms,
    }


class OpenShopAndroidStore:
    """Read and validate OpenShop state from an Android WebView."""

    def __init__(
        self,
        controller: Any,
        *,
        app_package: str = DEFAULT_APP_PACKAGE,
        local_state_key: str = LOCAL_STATE_KEY,
        seed_data_path: str | Path = DEFAULT_SEED_DATA_PATH,
        leveldb_path: str | None = None,
    ) -> None:
        self.controller = controller
        self.app_package = str(app_package or DEFAULT_APP_PACKAGE).strip() or DEFAULT_APP_PACKAGE
        self.local_state_key = str(local_state_key or LOCAL_STATE_KEY).strip() or LOCAL_STATE_KEY
        self.seed_data_path = Path(seed_data_path).expanduser().resolve()
        self.leveldb_path = str(
            leveldb_path
            or DEFAULT_LEVELDB_PATH_TEMPLATE.format(app_package=self.app_package)
        ).strip()
        self._seed_payload_cache: dict[str, Any] | None = None

    def read_state(self) -> dict[str, Any]:
        try:
            return self._read_state_via_devtools()
        except Exception:
            return self._read_state_via_leveldb_snapshot()

    def write_state(self, state: Mapping[str, Any], *, reload_page: bool = True) -> dict[str, Any]:
        """Persist OpenShop localStorage state through WebView DevTools.

        The Android benchmark app keeps all task-relevant state in one
        localStorage blob. Oracle flows can therefore deterministically set the
        desired cart / order state without replaying brittle UI steps.
        """

        if not isinstance(state, Mapping):
            raise TypeError(f"OpenShop state must be a mapping, got {type(state)!r}")

        payload = json.loads(json.dumps(dict(state), ensure_ascii=False))
        self._write_state_via_devtools(payload, reload_page=reload_page)
        return payload

    def find_product(self, product_id: str) -> dict[str, Any] | None:
        resolved_product_id = str(product_id or "").strip()
        for product in self._clone_seed_list("products"):
            if str(product.get("id") or "").strip() == resolved_product_id:
                return product
        return None

    def summarize_cart(self, state: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        resolved_state = dict(state or self.read_state())
        cart = resolved_state.get("cart") if isinstance(resolved_state, dict) else []
        if not isinstance(cart, list):
            return []

        summary: list[dict[str, Any]] = []
        for item in cart:
            if not isinstance(item, Mapping):
                continue
            product_id = str(item.get("productId") or "").strip()
            product = self.find_product(product_id) or {}
            summary.append(
                {
                    "product_id": product_id,
                    "title": str(product.get("title") or "").strip(),
                    "quantity": int(item.get("quantity") or 0),
                    "selected_spec": str(item.get("selectedSpec") or "").strip(),
                }
            )
        return summary

    def cart_item_matches_spec(self, item: Mapping[str, Any], spec: OpenShopCartItemSpec) -> bool:
        product_id = str(item.get("productId") or "").strip()
        quantity = int(item.get("quantity") or 0)
        selected_spec = str(item.get("selectedSpec") or "").strip()
        if product_id != spec.product_id:
            return False
        if quantity != max(1, int(spec.quantity)):
            return False
        if spec.selected_spec and selected_spec != spec.selected_spec:
            return False
        return True

    def order_matches_expectation(self, order: Mapping[str, Any], expectation: Mapping[str, Any]) -> bool:
        if not isinstance(order, Mapping) or not isinstance(expectation, Mapping):
            return False

        address_id = str(expectation.get("address_id") or "").strip()
        if address_id and not self._record_matches_seed_entry("addresses", address_id, order.get("address")):
            return False

        payment_method_id = str(expectation.get("payment_method_id") or "").strip()
        if payment_method_id and not self._record_matches_seed_entry(
            "paymentMethods",
            payment_method_id,
            order.get("payment"),
        ):
            return False

        note = str(expectation.get("note") or "").strip()
        if note and _normalize_note(str(order.get("note") or "")) != _normalize_note(note):
            return False

        status = str(expectation.get("status") or "").strip()
        if status and str(order.get("status") or "").strip() != status:
            return False

        expected_items = coerce_cart_item_specs(expectation.get("items"))
        observed_items = order.get("items")
        if expected_items:
            if not isinstance(observed_items, list) or len(observed_items) != len(expected_items):
                return False
            for expected in expected_items:
                matched = False
                for observed in observed_items:
                    if not isinstance(observed, Mapping):
                        continue
                    product = observed.get("product") if isinstance(observed.get("product"), Mapping) else {}
                    specs_list = product.get("specs") if isinstance(product, Mapping) else None
                    default_spec = (
                        str(specs_list[0]).strip()
                        if isinstance(specs_list, list) and specs_list and str(specs_list[0]).strip()
                        else ""
                    )
                    normalized_observed = {
                        "productId": str(product.get("id") or "").strip(),
                        "quantity": int(observed.get("quantity") or 0),
                        "selectedSpec": str(observed.get("selectedSpec") or default_spec).strip(),
                    }
                    if self.cart_item_matches_spec(normalized_observed, expected):
                        matched = True
                        break
                if not matched:
                    return False
        return True

    def load_seed_payload(self) -> dict[str, Any]:
        if self._seed_payload_cache is not None:
            return self._seed_payload_cache
        raw = self.seed_data_path.read_text(encoding="utf-8")
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            raise ValueError(f"Could not parse OpenShop seed payload from {self.seed_data_path}")
        data = json.loads(raw[start : end + 1])
        if not isinstance(data, dict):
            raise ValueError(f"OpenShop seed payload must be an object, got {type(data)!r}")
        self._seed_payload_cache = data
        return data

    def _clone_seed_list(self, key: str) -> list[dict[str, Any]]:
        payload = self.load_seed_payload()
        value = payload.get(key)
        if not isinstance(value, list):
            return []
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _record_matches_seed_entry(self, key: str, entry_id: str, observed: Any) -> bool:
        if not isinstance(observed, Mapping):
            return False
        expected_entry = next(
            (
                item
                for item in self._clone_seed_list(key)
                if str(item.get("id") or "").strip() == entry_id
            ),
            None,
        )
        if expected_entry is None:
            return False
        for field, expected_value in expected_entry.items():
            if str(observed.get(field) or "").strip() != str(expected_value or "").strip():
                return False
        return True

    def _read_state_via_devtools(self) -> dict[str, Any]:
        if self.controller is None or not hasattr(self.controller, "execute_adb"):
            raise RuntimeError("controller.execute_adb is required")

        pid = str(self.controller.execute_adb(["shell", "pidof", self.app_package]) or "").strip().split()
        if not pid:
            raise RuntimeError(f"OpenShop process is not running: {self.app_package}")

        port = _free_tcp_port()
        forward_spec = f"tcp:{port}"
        self.controller.execute_adb(["forward", forward_spec, f"localabstract:webview_devtools_remote_{pid[0]}"])
        try:
            with urlopen(f"http://127.0.0.1:{port}/json", timeout=4.0) as response:
                targets = json.loads(response.read().decode("utf-8"))
            if not isinstance(targets, list) or not targets:
                raise RuntimeError("no WebView DevTools targets found")
            target = next(
                (
                    item
                    for item in targets
                    if isinstance(item, Mapping) and str(item.get("webSocketDebuggerUrl") or "").strip()
                ),
                None,
            )
            if target is None:
                raise RuntimeError("WebView DevTools target does not expose a websocket")

            expression = (
                "(function(){"
                f"return window.localStorage.getItem({json.dumps(self.local_state_key)}) || '';"
                "})()"
            )
            payload = _devtools_runtime_evaluate(str(target["webSocketDebuggerUrl"]), expression)
        finally:
            self.controller.execute_adb(["forward", "--remove", forward_spec])

        raw_value = str(payload or "").strip()
        if not raw_value:
            raise RuntimeError(f"localStorage key is missing: {self.local_state_key}")
        data = json.loads(raw_value)
        if not isinstance(data, dict):
            raise RuntimeError(f"OpenShop local state must be an object, got {type(data)!r}")
        return data

    def _write_state_via_devtools(self, state: Mapping[str, Any], *, reload_page: bool) -> None:
        if self.controller is None or not hasattr(self.controller, "execute_adb"):
            raise RuntimeError("controller.execute_adb is required")

        pid = str(self.controller.execute_adb(["shell", "pidof", self.app_package]) or "").strip().split()
        if not pid:
            raise RuntimeError(f"OpenShop process is not running: {self.app_package}")

        port = _free_tcp_port()
        forward_spec = f"tcp:{port}"
        self.controller.execute_adb(["forward", forward_spec, f"localabstract:webview_devtools_remote_{pid[0]}"])
        try:
            with urlopen(f"http://127.0.0.1:{port}/json", timeout=4.0) as response:
                targets = json.loads(response.read().decode("utf-8"))
            if not isinstance(targets, list) or not targets:
                raise RuntimeError("no WebView DevTools targets found")
            target = next(
                (
                    item
                    for item in targets
                    if isinstance(item, Mapping) and str(item.get("webSocketDebuggerUrl") or "").strip()
                ),
                None,
            )
            if target is None:
                raise RuntimeError("WebView DevTools target does not expose a websocket")

            state_json = json.dumps(dict(state), ensure_ascii=False)
            expression = (
                "(function(){"
                f"const key={json.dumps(self.local_state_key)};"
                f"const value={json.dumps(state_json)};"
                "window.localStorage.setItem(key, value);"
                f"{'window.location.reload();' if reload_page else ''}"
                "return window.localStorage.getItem(key) || '';"
                "})()"
            )
            written = _devtools_runtime_evaluate(str(target["webSocketDebuggerUrl"]), expression)
        finally:
            self.controller.execute_adb(["forward", "--remove", forward_spec])

        if not written:
            raise RuntimeError(f"failed to persist localStorage key: {self.local_state_key}")

    def _read_state_via_leveldb_snapshot(self) -> dict[str, Any]:
        if self.controller is None or not hasattr(self.controller, "execute_adb"):
            raise RuntimeError("controller.execute_adb is required")

        ensure_app_installed(self.controller, self.app_package, label="OpenShop")
        self._ensure_adb_root_best_effort()
        self.controller.execute_adb(["shell", "am", "force-stop", self.app_package])
        time.sleep(0.5)

        with tempfile.TemporaryDirectory(prefix="android-openshop-leveldb-") as tmpdir:
            snapshot = Path(tmpdir) / "leveldb"
            self.controller.execute_adb(["pull", self.leveldb_path, str(snapshot)])
            if not snapshot.exists():
                raise RuntimeError(f"LevelDB pull failed: {self.leveldb_path}")

            candidates: list[dict[str, Any]] = []
            for path in sorted(snapshot.rglob("*")):
                if not path.is_file():
                    continue
                blob = path.read_bytes()
                candidates.extend(_extract_json_objects_near_key(blob, self.local_state_key))

        if not candidates:
            raise RuntimeError(f"Could not find {self.local_state_key} in Android WebView localStorage")
        return candidates[-1]

    def _ensure_adb_root_best_effort(self) -> None:
        output = str(self.controller.execute_adb(["root"]) or "").strip().lower()
        if "restarting adbd as root" in output:
            self.controller.execute_adb(["wait-for-device"])
            time.sleep(1.0)


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _devtools_runtime_evaluate(websocket_url: str, expression: str) -> str:
    message_id = random.randint(1000, 999999)
    response = _websocket_request_json(
        websocket_url,
        {
            "id": message_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        },
        expected_id=message_id,
    )
    result = response.get("result") if isinstance(response, Mapping) else None
    value = result.get("result") if isinstance(result, Mapping) else None
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Malformed Runtime.evaluate response: {response!r}")
    if "exceptionDetails" in result:
        raise RuntimeError(f"Runtime.evaluate raised: {result['exceptionDetails']!r}")
    return str(value.get("value") or "")


def _websocket_request_json(url: str, payload: Mapping[str, Any], *, expected_id: int) -> dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = int(parsed.port or 80)
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"

    with socket.create_connection((host, port), timeout=5.0) as sock:
        sock.settimeout(5.0)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = _recv_until(sock, b"\r\n\r\n")
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket handshake failed: {response[:120]!r}")

        _send_ws_text(sock, json.dumps(dict(payload), separators=(",", ":")))
        deadline = time.time() + 5.0
        while time.time() < deadline:
            text = _recv_ws_text(sock)
            if not text:
                continue
            data = json.loads(text)
            if isinstance(data, dict) and data.get("id") == expected_id:
                return data
    raise RuntimeError("Timed out waiting for WebSocket response")


def _send_ws_text(sock: socket.socket, text: str) -> None:
    _send_ws_frame(sock, 0x1, text.encode("utf-8"))


def _send_ws_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    header = bytearray([0x80 | (opcode & 0x0F)])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.extend([0x80 | 126, (length >> 8) & 0xFF, length & 0xFF])
    else:
        header.append(0x80 | 127)
        header.extend(length.to_bytes(8, "big"))
    mask = os.urandom(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def _recv_ws_text(sock: socket.socket) -> str:
    first_two = _recv_exact(sock, 2)
    first, second = first_two[0], first_two[1]
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(_recv_exact(sock, 2), "big")
    elif length == 127:
        length = int.from_bytes(_recv_exact(sock, 8), "big")
    mask = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length) if length else b""
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    if opcode == 0x8:
        return ""
    if opcode == 0x9:
        _send_ws_frame(sock, 0xA, payload)
        return ""
    if opcode != 0x1:
        return ""
    return payload.decode("utf-8", errors="replace")


def _recv_until(sock: socket.socket, marker: bytes) -> bytes:
    chunks: list[bytes] = []
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        data = b"".join(chunks)
    return data


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("WebSocket connection closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _normalize_note(text: str) -> str:
    return " ".join(text.split())


def _extract_json_objects_near_key(blob: bytes, key: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    decode_attempts = (
        ("utf-8", blob),
        ("utf-16-le", blob),
        ("utf-16-le", blob[1:]),
    )
    for encoding, payload in decode_attempts:
        try:
            text = payload.decode(encoding, errors="ignore")
        except Exception:
            continue
        search_from = 0
        while True:
            key_index = text.find(key, search_from)
            if key_index < 0:
                break
            brace_index = text.find("{", key_index)
            if brace_index < 0:
                break
            extracted = _balanced_json_object(text, brace_index)
            if extracted:
                try:
                    parsed = json.loads(extracted)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict) and isinstance(parsed.get("session"), Mapping):
                    candidates.append(parsed)
            search_from = key_index + len(key)
    return candidates


def _balanced_json_object(text: str, start: int) -> str:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""
