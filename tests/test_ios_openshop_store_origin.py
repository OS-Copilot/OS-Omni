from pathlib import Path
import json

import pytest

from platforms.ios.openshop_store import OpenShopStore
from initializers.ios.openshop_seed_open_app import OpenShopSeedOpenAppInitializer


def _origin_record(scheme: bytes, host: bytes) -> bytes:
    def component(value: bytes) -> bytes:
        return len(value).to_bytes(4, "little") + b"\x01" + value

    record = component(scheme) + component(host) + b"\x00"
    return record + record


def _make_origin(container: Path, directory: str, origin: bytes) -> Path:
    root = (
        container
        / "Library/WebKit/com.killt.openshop/WebsiteData/Default"
        / directory
        / directory
    )
    local_storage = root / "LocalStorage"
    local_storage.mkdir(parents=True)
    (root / "origin").write_bytes(origin)
    database = local_storage / "localstorage.sqlite3"
    database.touch()
    return database.resolve()


def test_selects_capacitor_origin_instead_of_first_database(tmp_path):
    container = tmp_path / "app-data"
    _make_origin(container, "aaa-first-but-inactive", _origin_record(b"file", b""))
    expected = _make_origin(
        container, "zzz-active", _origin_record(b"capacitor", b"localhost")
    )

    assert OpenShopStore._find_localstorage_db_path(container) == expected


def test_fails_closed_without_exact_capacitor_origin(tmp_path):
    container = tmp_path / "app-data"
    _make_origin(container, "inactive", _origin_record(b"file", b""))

    with pytest.raises(FileNotFoundError, match="exactly one capacitor://localhost"):
        OpenShopStore._find_localstorage_db_path(container)


def test_fresh_state_matches_account_scoped_openshop_schema(tmp_path):
    seed = {
        "benchmarkAccount": {"id": "lucas", "name": "Lucas Lin", "phone": "13800138000"},
        "accounts": [
            {
                "id": "lucas",
                "name": "Lucas Lin",
                "phone": "13800138000",
                "addresses": [{"id": "addr-home", "label": "Home"}],
                "paymentMethods": [{"id": "alipay", "label": "Alipay"}],
                "orders": [{"id": "seed-order"}],
            }
        ],
        "addresses": [],
        "paymentMethods": [],
        "products": [],
    }
    seed_path = tmp_path / "seed-data.js"
    seed_path.write_text(f"window.openshopSeed = {json.dumps(seed)};", encoding="utf-8")
    store = OpenShopStore(tmp_path / "localstorage.sqlite3", seed_data_path=seed_path)

    state = store.build_fresh_state(login_session=True)

    assert state["session"] == {
        "loggedIn": True,
        "user": {"id": "lucas", "name": "Lucas Lin", "phone": "13800138000"},
    }
    assert state["users"]["13800138000"] == {
        "addresses": [{"id": "addr-home", "label": "Home"}],
        "paymentMethods": [{"id": "alipay", "label": "Alipay"}],
        "cart": [],
        "orders": [{"id": "seed-order"}],
    }


def test_reset_state_seeds_active_account_cart(tmp_path):
    seed = {
        "benchmarkAccount": {"id": "lucas", "name": "Lucas Lin", "phone": "13800138000"},
        "accounts": [
            {"id": "lucas", "name": "Lucas Lin", "phone": "13800138000", "addresses": [], "paymentMethods": [], "orders": []}
        ],
        "addresses": [],
        "paymentMethods": [],
        "products": [{"id": "p1", "specs": ["Default"]}],
    }
    seed_path = tmp_path / "seed-data.js"
    seed_path.write_text(f"window.openshopSeed = {json.dumps(seed)};", encoding="utf-8")
    store = OpenShopStore(tmp_path / "localstorage.sqlite3", seed_data_path=seed_path)

    state = store.reset_state(
        login_session=True,
        cart_items=[{"product_id": "p1", "quantity": 2}],
    )

    assert state["users"]["13800138000"]["cart"] == [
        {"id": "cart-seed-0001", "productId": "p1", "quantity": 2, "selectedSpec": "Default"}
    ]


def test_initializer_uses_task_local_state_key(monkeypatch):
    captured = {}
    sentinel = object()

    def fake_from_simulator(udid, *, bundle_id, local_state_key):
        captured.update(udid=udid, bundle_id=bundle_id, local_state_key=local_state_key)
        return sentinel

    monkeypatch.setattr(OpenShopStore, "from_simulator", fake_from_simulator)

    result = OpenShopSeedOpenAppInitializer._build_store(
        controller=type("Controller", (), {"runtime": type("Runtime", (), {"udid": "SIM"})()})(),
        params={"local_state_key": "openshop.localState.v3"},
        bundle_id="com.killt.openshop",
    )

    assert result is sentinel
    assert captured == {
        "udid": "SIM",
        "bundle_id": "com.killt.openshop",
        "local_state_key": "openshop.localState.v3",
    }
