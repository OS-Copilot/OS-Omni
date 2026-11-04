"""WIN-039: the OpenFood cross-role audit resolves the cart's restaurant and menu items
from the shipped app.asar seed when the renderer's cached window.OPENFOOD_DATA copy is
not on disk.

The guest storage scan is run locally against a temporary APPDATA tree: a Local Storage
log holding the agent's cart state, and (optionally) the HTTP cache file holding the
window.OPENFOOD_DATA script that the old evaluator depended on.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.evaluation import EvalStatus
from evaluators.windows.openfood_customer_cart_cross_role_audit import OpenFoodCustomerAuditEvaluator

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tasks/v1/windows/openfood_customer_cart_cross_role_audit.yaml"

SEED = {
    "users": [{"id": "lucas", "name": "Lucas Lin", "role": "Customer"}],
    "restaurants": [
        {"id": "r1", "name": "Dumpling Room No. 20 San Jose CA", "fee": 2.24},
        {"id": "r2", "name": "Santana Row Banh Mi Market No. 12 San Jose CA", "fee": 1.5},
    ],
    "menu": [
        {"id": "m1", "restaurantId": "r1", "name": "Pork Dumplings", "price": 8.2},
        {"id": "m2", "restaurantId": "r1", "name": "Beef Chow Fun", "price": 9.55},
        {"id": "m3", "restaurantId": "r2", "name": "Banh Mi", "price": 7.0},
    ],
}
STATE = {
    "view": "admin", "userId": "lucas", "selectedRestaurantId": "r1", "activeCoupon": "WELCOME12",
    "cart": [{"itemId": "m1", "qty": 2}, {"itemId": "m2", "qty": 2}],
    "createdOrders": [], "orderStatus": {}, "menuAvailability": {}, "restaurantOpen": {}, "tickets": [],
}
CART_CHECKS = ("cart_pork_dumplings", "cart_beef_chow_fun", "coupon_selected", "protected_actions_unchanged",
               "cart_financials")


def _write_asar(path: Path, seed: dict) -> None:
    payload = json.dumps(seed).encode()
    header = json.dumps({"files": {"shared": {"files": {"seed-data.json": {"offset": "0", "size": len(payload)}}}}}).encode()
    path.write_bytes(struct.pack("<IIII", 4, 8 + len(header), 0, len(header)) + header + payload)


class LocalGuest:
    """Runs the evaluator's guest Python locally with APPDATA pointing at a temp tree."""

    def __init__(self, appdata: Path):
        self.appdata = appdata

    def run_python_script(self, code, timeout=60):
        env = {**os.environ, "APPDATA": str(self.appdata), "LOCALAPPDATA": str(self.appdata.parent / "Local")}
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout, env=env)
        return {"returncode": done.returncode, "output": done.stdout or done.stderr}

    def run_powershell_script(self, *args, **kwargs):  # the final-UI read is not under test here
        raise RuntimeError("no PowerShell in this test")


def _guest(tmp_path: Path, state: dict, *, cached_copy: bool) -> LocalGuest:
    appdata = tmp_path / "Roaming"
    leveldb = appdata / "openfood" / "Local Storage" / "leveldb"
    leveldb.mkdir(parents=True)
    (leveldb / "000003.log").write_text(
        "_http://127.0.0.1:4320\x00\x01openfood-static-state-v1\n" + json.dumps(state), encoding="utf-8")
    if cached_copy:
        cache = appdata / "openfood" / "Cache" / "Cache_Data"
        cache.mkdir(parents=True)
        (cache / "f_000033").write_text("window.OPENFOOD_DATA = " + json.dumps(SEED, indent=2) + ";\n",
                                        encoding="utf-8")
    (tmp_path / "Local").mkdir()
    return LocalGuest(appdata)


def _evaluate(tmp_path: Path, *, cached_copy: bool, asar: bool, state: dict = STATE):
    params = yaml.safe_load(TASK.read_text(encoding="utf-8"))["evaluation"]["params"]
    asar_path = tmp_path / "app.asar"
    if asar:
        _write_asar(asar_path, SEED)
    params = {**params, "seed_asar_paths": [str(asar_path)]}
    controller = _guest(tmp_path, state, cached_copy=cached_copy)
    return OpenFoodCustomerAuditEvaluator().evaluate({"controller": controller, "params": params})


def _checks(result) -> dict[str, bool]:
    return {row["label"]: row["passed"] for row in (result.metadata or {}).get("checks") or []}


def test_cart_is_graded_from_the_shipped_seed_without_a_cached_copy(tmp_path):
    result = _evaluate(tmp_path, cached_copy=False, asar=True)
    checks = _checks(result)
    assert all(checks[name] for name in CART_CHECKS), checks
    assert result.metadata["resolved_state"]["seed_sources"] == ["app.asar shared/seed-data.json"]
    # Only the final Admin screen, which this test does not provide, is left failing.
    assert result.status == EvalStatus.FAIL and not checks["final_admin_all_orders_ui"]


def test_old_reader_could_not_grade_the_cart_without_the_cached_copy(tmp_path):
    # Without the asar fallback (no archive at the path) the result is the old ERROR.
    result = _evaluate(tmp_path, cached_copy=False, asar=False)
    assert result.status == EvalStatus.ERROR
    assert "restaurant seed record could not be decoded for 'r1'" in result.message
    assert "shipped seed:" in result.message


def test_cached_copy_is_still_used_when_present(tmp_path):
    result = _evaluate(tmp_path, cached_copy=True, asar=False)
    checks = _checks(result)
    assert all(checks[name] for name in CART_CHECKS), checks
    assert result.metadata["resolved_state"]["seed_sources"] == ["cached window.OPENFOOD_DATA"]


@pytest.mark.parametrize("cart, failing", [
    ([{"itemId": "m1", "qty": 1}, {"itemId": "m2", "qty": 2}], "cart_pork_dumplings"),
    ([{"itemId": "m1", "qty": 2}], "cart_beef_chow_fun"),
])
def test_wrong_cart_still_fails_with_the_shipped_seed(tmp_path, cart, failing):
    result = _evaluate(tmp_path, cached_copy=False, asar=True, state={**STATE, "cart": cart})
    checks = _checks(result)
    assert not checks[failing] and not checks["cart_financials"]


def test_other_restaurant_selected_fails_with_the_shipped_seed(tmp_path):
    state = {**STATE, "selectedRestaurantId": "r2", "cart": [{"itemId": "m3", "qty": 2}]}
    result = _evaluate(tmp_path, cached_copy=False, asar=True, state=state)
    assert result.status == EvalStatus.FAIL
    assert "does not resolve to 'Dumpling Room No. 20 San Jose CA'" in result.message
