"""Helpers for reading and seeding OpenShop local state in an iOS simulator."""

from __future__ import annotations

import json
import shutil
import sqlite3
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from platforms.ios.runtime_env.simulator_manager import (
    get_app_container_path,
    get_app_data_container_path,
    run_cmd,
)


DEFAULT_BUNDLE_ID = "com.killt.openshop"
LOCAL_STATE_KEY = "openshop.localState.v1"
DEFAULT_BOOTSTRAP_WAIT_SECONDS = 1.2


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


class OpenShopStore:
    """Read and write OpenShop benchmark state from WebKit localStorage."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        bundle_id: str = DEFAULT_BUNDLE_ID,
        data_container_path: str | Path | None = None,
        seed_data_path: str | Path | None = None,
        local_state_key: str = LOCAL_STATE_KEY,
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.bundle_id = str(bundle_id or DEFAULT_BUNDLE_ID).strip() or DEFAULT_BUNDLE_ID
        self.data_container_path = (
            Path(data_container_path).expanduser().resolve()
            if data_container_path
            else None
        )
        self.seed_data_path = Path(seed_data_path).expanduser().resolve() if seed_data_path else None
        self.local_state_key = str(local_state_key or LOCAL_STATE_KEY).strip() or LOCAL_STATE_KEY
        self._seed_payload_cache: dict[str, Any] | None = None

    @classmethod
    def from_simulator(
        cls,
        udid: str,
        *,
        bundle_id: str = DEFAULT_BUNDLE_ID,
        local_state_key: str = LOCAL_STATE_KEY,
    ) -> "OpenShopStore":
        data_container = Path(get_app_data_container_path(udid, bundle_id)).expanduser().resolve()
        db_path = cls._find_localstorage_db_path(data_container)
        seed_data_path = cls._resolve_seed_data_path_from_bundle(udid, bundle_id)
        return cls(
            db_path,
            bundle_id=bundle_id,
            data_container_path=data_container,
            seed_data_path=seed_data_path,
            local_state_key=local_state_key,
        )

    @classmethod
    def bootstrap_webview_storage(
        cls,
        *,
        controller: Any,
        bundle_id: str,
        wait_seconds: float = DEFAULT_BOOTSTRAP_WAIT_SECONDS,
    ) -> None:
        if hasattr(controller, "terminate_app"):
            controller.terminate_app(bundle_id)
            time.sleep(0.5)
        if hasattr(controller, "press_home"):
            controller.press_home()
            time.sleep(0.4)
        controller.activate_app(bundle_id)
        time.sleep(max(wait_seconds, 0.0))
        if hasattr(controller, "terminate_app"):
            controller.terminate_app(bundle_id)
            time.sleep(0.7)

    def read_state(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return self.build_fresh_state()

        with self._snapshot_db_path() as snapshot_db_path:
            conn = sqlite3.connect(snapshot_db_path)
            try:
                row = conn.execute(
                    "SELECT value FROM ItemTable WHERE key = ? LIMIT 1",
                    (self.local_state_key,),
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            return self.build_fresh_state()

        raw_value = row[0]
        if isinstance(raw_value, memoryview):
            payload = bytes(raw_value)
        elif isinstance(raw_value, bytes):
            payload = raw_value
        elif isinstance(raw_value, str):
            payload = raw_value.encode("utf-16-le")
        else:
            payload = bytes(raw_value or b"")

        try:
            decoded = payload.decode("utf-16-le").rstrip("\x00")
            data = json.loads(decoded)
        except Exception as exc:
            raise RuntimeError(f"Failed to decode OpenShop local state: {exc}") from exc

        if not isinstance(data, dict):
            raise RuntimeError(f"OpenShop local state must be an object, got {type(data)!r}")
        return data

    def write_state(self, state: Mapping[str, Any]) -> None:
        normalized_state = json.loads(json.dumps(state, ensure_ascii=False))
        self._ensure_storage_exists()
        encoded = json.dumps(normalized_state, ensure_ascii=False, separators=(",", ":")).encode("utf-16-le")
        with self._connect_writable() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                (self.local_state_key, sqlite3.Binary(encoded)),
            )
            conn.commit()

    def reset_state(
        self,
        *,
        login_session: bool = False,
        cart_items: Sequence[OpenShopCartItemSpec] | Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fresh_state = self.build_fresh_state(login_session=login_session)
        cart = self.build_cart_entries(cart_items or [])
        fresh_state["cart"] = cart
        fresh_state["orders"] = []
        session = fresh_state.get("session")
        user = session.get("user") if isinstance(session, Mapping) else None
        users = fresh_state.get("users")
        if isinstance(user, Mapping) and isinstance(users, dict):
            account_state = users.get(str(user.get("phone") or ""))
            if isinstance(account_state, dict):
                account_state["cart"] = json.loads(json.dumps(cart, ensure_ascii=False))
        self.write_state(fresh_state)
        return fresh_state

    def build_fresh_state(self, *, login_session: bool = False) -> dict[str, Any]:
        seed = self.load_seed_payload()
        benchmark_account = seed.get("benchmarkAccount") if isinstance(seed, dict) else {}
        account_name = ""
        account_phone = ""
        if isinstance(benchmark_account, dict):
            account_name = str(benchmark_account.get("name") or "").strip()
            account_phone = str(benchmark_account.get("phone") or "").strip()

        raw_accounts = seed.get("accounts") if isinstance(seed, dict) else None
        accounts = [
            account for account in raw_accounts if isinstance(account, Mapping)
        ] if isinstance(raw_accounts, list) else []
        if not accounts and isinstance(benchmark_account, Mapping):
            accounts = [benchmark_account]

        users: dict[str, dict[str, Any]] = {}
        for account in accounts:
            phone = str(account.get("phone") or "").strip()
            if not phone:
                continue
            addresses = account.get("addresses")
            payment_methods = account.get("paymentMethods")
            orders = account.get("orders")
            users[phone] = {
                "addresses": json.loads(json.dumps(
                    addresses if isinstance(addresses, list) else seed.get("addresses", []),
                    ensure_ascii=False,
                )),
                "paymentMethods": json.loads(json.dumps(
                    payment_methods if isinstance(payment_methods, list) else seed.get("paymentMethods", []),
                    ensure_ascii=False,
                )),
                "cart": [],
                "orders": json.loads(json.dumps(orders if isinstance(orders, list) else [], ensure_ascii=False)),
            }

        active_account = next(
            (account for account in accounts if str(account.get("phone") or "").strip() == account_phone),
            benchmark_account if isinstance(benchmark_account, Mapping) else {},
        )

        return {
            "session": {
                "loggedIn": bool(login_session),
                "user": (
                    {
                        "id": str(active_account.get("id") or account_phone),
                        "name": account_name,
                        "phone": account_phone,
                    }
                    if login_session and account_name and account_phone
                    else None
                ),
            },
            "users": users,
            "addresses": self._clone_seed_list("addresses"),
            "paymentMethods": self._clone_seed_list("paymentMethods"),
            "cart": [],
            "orders": [],
        }

    def build_cart_entries(
        self,
        cart_items: Sequence[OpenShopCartItemSpec] | Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        specs = (
            list(cart_items)
            if cart_items and all(isinstance(item, OpenShopCartItemSpec) for item in cart_items)
            else coerce_cart_item_specs(list(cart_items))
        )

        entries: list[dict[str, Any]] = []
        for index, spec in enumerate(specs, start=1):
            product = self.find_product(spec.product_id)
            if product is None:
                raise ValueError(f"Unknown OpenShop product_id: {spec.product_id}")
            specs_list = product.get("specs") if isinstance(product, dict) else None
            default_spec = (
                str(specs_list[0]).strip()
                if isinstance(specs_list, list) and specs_list and str(specs_list[0]).strip()
                else ""
            )
            entries.append(
                {
                    "id": f"cart-seed-{index:04d}",
                    "productId": spec.product_id,
                    "quantity": max(1, int(spec.quantity)),
                    "selectedSpec": spec.selected_spec or default_spec,
                }
            )
        return entries

    def clear_saved_state(self) -> None:
        if self.data_container_path is None:
            return
        candidates = [
            self.data_container_path
            / "Library"
            / "Saved Application State"
            / f"{self.bundle_id}.savedState",
            self.data_container_path
            / "Library"
            / "SplashBoard"
            / "Snapshots"
            / f"sceneID:{self.bundle_id}-default",
        ]
        for candidate in candidates:
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)

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

    def list_orders(self, state: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        resolved_state = dict(state or self.read_state())
        orders = resolved_state.get("orders") if isinstance(resolved_state, dict) else []
        if not isinstance(orders, list):
            return []
        return [order for order in orders if isinstance(order, dict)]

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
        if address_id:
            address = order.get("address")
            if not self._record_matches_seed_entry("addresses", address_id, address):
                return False

        payment_method_id = str(expectation.get("payment_method_id") or "").strip()
        if payment_method_id:
            payment = order.get("payment")
            if not self._record_matches_seed_entry("paymentMethods", payment_method_id, payment):
                return False

        note = str(expectation.get("note") or "").strip()
        if note and str(order.get("note") or "").strip() != note:
            return False

        status = str(expectation.get("status") or "").strip()
        if status and str(order.get("status") or "").strip() != status:
            return False

        expected_total = expectation.get("total")
        if expected_total is not None and not self._money_values_match(order.get("total"), expected_total):
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

    @staticmethod
    def _money_values_match(observed: Any, expected: Any) -> bool:
        try:
            observed_value = round(float(observed), 2)
            expected_value = round(float(expected), 2)
        except (TypeError, ValueError):
            return False
        return observed_value == expected_value

    def load_seed_payload(self) -> dict[str, Any]:
        if self._seed_payload_cache is not None:
            return self._seed_payload_cache
        if self.seed_data_path is None:
            raise ValueError("OpenShop store needs seed_data_path to build/reset local state")

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

    def _ensure_storage_exists(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB NOT NULL ON CONFLICT FAIL)"
            )
            conn.commit()
        finally:
            conn.close()

    def _connect_writable(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _snapshot_db_path(self):
        class _SnapshotContext:
            def __init__(self, store: "OpenShopStore") -> None:
                self._store = store
                self._tmpdir = tempfile.TemporaryDirectory(prefix="ios_openshop_snapshot_")

            def __enter__(self) -> str:
                snapshot_root = Path(self._tmpdir.name)
                base_name = self._store.db_path.name
                if self._store.db_path.exists():
                    for candidate in self._store.db_path.parent.glob(f"{base_name}*"):
                        if candidate.is_file():
                            shutil.copy2(candidate, snapshot_root / candidate.name)
                else:
                    conn = sqlite3.connect(snapshot_root / base_name)
                    try:
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB NOT NULL ON CONFLICT FAIL)"
                        )
                        conn.commit()
                    finally:
                        conn.close()
                return str(snapshot_root / base_name)

            def __exit__(self, exc_type, exc, tb) -> bool:
                self._tmpdir.cleanup()
                return False

        return _SnapshotContext(self)

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

    @staticmethod
    def _find_localstorage_db_path(data_container_path: Path) -> Path:
        origin_root = (
            data_container_path
            / "Library"
            / "WebKit"
            / DEFAULT_BUNDLE_ID
            / "WebsiteData"
            / "Default"
        )
        origin_files = sorted(origin_root.glob("*/*/origin"))
        active = [path for path in origin_files if OpenShopStore._origin_is_exact(path.read_bytes())]
        if len(active) != 1:
            raise FileNotFoundError(
                "expected exactly one capacitor://localhost WebKit origin for "
                f"OpenShop under {origin_root}, observed {len(active)}"
            )
        db_path = active[0].parent / "LocalStorage" / "localstorage.sqlite3"
        if not db_path.is_file():
            raise FileNotFoundError(f"OpenShop localStorage database is missing: {db_path}")
        return db_path.resolve()

    @staticmethod
    def _origin_is_exact(payload: bytes) -> bool:
        """Match the WebKit origin record used by the packaged Capacitor app."""
        def component(value: bytes) -> bytes:
            return struct.pack("<I", len(value)) + b"\x01" + value

        record = component(b"capacitor") + component(b"localhost") + b"\x00"
        return payload == record + record

    @staticmethod
    def _resolve_seed_data_path_from_bundle(udid: str, bundle_id: str) -> Path:
        app_container = get_app_container_path(str(udid), str(bundle_id), "app")
        seed_data_path = app_container / "public" / "seed-data.js"
        if not seed_data_path.exists():
            raise FileNotFoundError(f"OpenShop seed-data.js not found in app bundle: {seed_data_path}")
        return seed_data_path
