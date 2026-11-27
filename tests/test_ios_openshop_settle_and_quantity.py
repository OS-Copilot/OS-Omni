"""iOS OpenShop 368575 / 263796.

368575: the brief asks for one CasaPure bin in the second order (277.70 total:
subtotal 265.70 is under the 300 discount threshold, plus 12 shipping).
263796 / 368575: the localStorage file is re-read for a bounded time, so a final
write that reaches disk just after the agent's last action is still graded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from evaluators.cua_review.platforms.ios.webview_state import read_until_settled
from evaluators.ios import openshop_home_four_item_cart_checkout_368575 as home
from evaluators.ios import openshop_trip_gear_dual_checkout_review_263796 as trip

REPO = Path(__file__).resolve().parents[1]
WINDOW_START = datetime(2026, 10, 11, 15, 30, tzinfo=timezone.utc)
HOME = home.OpenShopHomeFourItemCartCheckout368575Evaluator
TRIP = trip.OpenShopTripGearDualCheckoutReview263796Evaluator


def _timestamp(epoch_ms):
    value = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def trip_reference_state():
    """Same complete 263796 state as tests/test_ios_openshop_tripgear_verifier.py."""
    first_spec, second_spec, review_spec = trip.CHECKPOINT_SPECS
    now_ms = 1_791_732_640_000

    def order_items(spec, first_item_ms, review=False):
        items = []
        for index, expected in enumerate(spec["items"]):
            item = {
                "id": f"cart-{first_item_ms + index * 1000}",
                "quantity": expected["quantity"],
                "selectedSpec": expected["selected_spec"],
                "unitPrice": expected["unit_price"],
                "lineTotal": expected["line_total"],
                "product": {"id": expected["product_id"], "title": expected["title"],
                            "category": expected["category"]},
            }
            if review and expected["product_id"] == review_spec["product_id"]:
                item["review"] = {"rating": review_spec["rating"], "review": review_spec["review"],
                                  "reviewedAt": _timestamp(now_ms + 9000)}
            items.append(item)
        return items

    def order(spec, created_ms, first_item_ms, review=False):
        return {"id": f"TB{created_ms}", "createdAt": _timestamp(created_ms),
                "address": spec["address"], "payment": spec["payment"], "note": spec["note"],
                "items": order_items(spec, first_item_ms, review), "total": spec["total"],
                "status": spec["status"]}

    return {
        "session": {"loggedIn": True, "user": {"name": trip.ACCOUNT_NAME, "phone": trip.ACCOUNT_PHONE}},
        "users": {trip.ACCOUNT_PHONE: {"cart": [], "orders": [
            order(second_spec, now_ms + 8000, now_ms + 5000, review=True),
            order(first_spec, now_ms + 3000, now_ms),
        ]}},
    }


def _home_reference_state(casapure_quantity=1):
    office_spec, home_spec, casapure_review, mukawa_review = home.CHECKPOINT_SPECS
    now_ms = 1_791_732_640_000
    reviews = {
        (0, mukawa_review["product_id"]): (mukawa_review, now_ms + 20_000),
        (1, casapure_review["product_id"]): (casapure_review, now_ms + 15_000),
    }

    def items(order_index, spec, first_ms):
        rows = []
        for index, expected in enumerate(spec["items"]):
            quantity = expected["quantity"]
            line_total = expected["line_total"]
            if expected["product_id"] == "p2024":
                quantity = casapure_quantity
                line_total = round(expected["unit_price"] * quantity, 2)
            row = {
                "id": f"cart-{first_ms + index * 1000}",
                "quantity": quantity,
                "selectedSpec": expected["selected_spec"],
                "unitPrice": expected["unit_price"],
                "lineTotal": line_total,
                "product": {
                    "id": expected["product_id"],
                    "title": expected["title"],
                    "category": expected["category"],
                },
            }
            review = reviews.get((order_index, expected["product_id"]))
            if review:
                row["review"] = {
                    "rating": review[0]["rating"],
                    "review": review[0]["review"],
                    "reviewedAt": _timestamp(review[1]),
                }
            rows.append(row)
        return rows

    def order(order_index, spec, first_ms, created_ms, total):
        return {
            "id": f"TB{created_ms}",
            "createdAt": _timestamp(created_ms),
            "address": spec["address"],
            "payment": spec["payment"],
            "note": spec["note"],
            "items": items(order_index, spec, first_ms),
            "total": total,
            "status": spec["status"],
        }

    home_subtotal = round(
        sum(row["line_total"] for row in home_spec["items"] if row["product_id"] != "p2024")
        + 52 * casapure_quantity,
        2,
    )
    home_total = round(home_subtotal + 12 - (30 if home_subtotal >= 300 else 0), 2)
    return {
        "session": {"loggedIn": True, "user": {"name": home.ACCOUNT_NAME, "phone": home.ACCOUNT_PHONE}},
        "users": {
            home.ACCOUNT_PHONE: {
                "cart": [],
                "orders": [
                    order(1, home_spec, now_ms + 5000, now_ms + 10_000, home_total),
                    order(0, office_spec, now_ms, now_ms + 4000, office_spec["total"]),
                ],
            }
        },
    }


def test_home_second_order_with_one_casapure_bin_passes():
    result = HOME._evaluate_state(_home_reference_state(1), window_start=WINDOW_START, window_end=None)
    assert result.status.value == "PASS", [c["failure_reason"] for c in result.metadata["failures"]]
    home_spec = home.CHECKPOINT_SPECS[1]
    assert home_spec["total"] == 277.7
    assert next(i for i in home_spec["items"] if i["product_id"] == "p2024")["quantity"] == 1


def test_home_second_order_with_two_casapure_bins_fails():
    result = HOME._evaluate_state(_home_reference_state(2), window_start=WINDOW_START, window_end=None)
    assert result.status.value == "FAIL"
    assert [c["name"] for c in result.metadata["failures"]] == ["home_order_exact"]


def test_home_task_binds_the_updated_ruleset():
    doc = yaml.safe_load(
        (REPO / "tasks/v1/ios/openshop_home_four_item_cart_checkout_368575.yaml").read_text(encoding="utf-8")
    )
    assert doc["evaluation"]["params"]["expected_ruleset_sha256"] == home.RULESET_SHA256
    assert doc["metadata"]["evaluator_ruleset_sha256"] == home.RULESET_SHA256
    assert 'one "CasaPure Bamboo Storage Bin Set"' in doc["instruction"]


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_read_until_settled_accepts_late_write():
    clock = _FakeClock()
    reads = iter([{"v": 1}, {"v": 1}, {"v": 2}])
    value, evidence = read_until_settled(
        lambda: next(reads), accept=lambda v: v["v"] == 2, fingerprint=lambda v: v["v"],
        timeout_seconds=8, poll_interval_seconds=0.5, stable_seconds=2, clock=clock, sleep=clock.sleep,
    )
    assert value == {"v": 2}
    assert evidence["stop_reason"] == "accepted" and evidence["attempts"] == 3


def test_read_until_settled_stops_when_state_is_stable_and_retries_errors():
    clock = _FakeClock()
    calls = {"n": 0}

    def read():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("copy caught a write")
        return {"v": 1}

    value, evidence = read_until_settled(
        read, accept=lambda v: False, fingerprint=lambda v: v["v"],
        timeout_seconds=8, poll_interval_seconds=0.5, stable_seconds=2, clock=clock, sleep=clock.sleep,
    )
    assert value == {"v": 1}
    assert evidence["stop_reason"] == "stable"
    assert clock.now < 8


def _run_evaluate(monkeypatch, evaluator_cls, module, yaml_name, states):
    doc = yaml.safe_load((REPO / "tasks/v1/ios" / yaml_name).read_text(encoding="utf-8"))
    params = dict(doc["evaluation"]["params"], udid="FAKE-UDID",
                  settle_poll_interval_seconds=0.0, settle_stable_seconds=0.0)
    remaining = list(states)
    monkeypatch.setattr(
        evaluator_cls, "_resolve_causal_window",
        classmethod(lambda cls, **_: (WINDOW_START, None, "synthetic")),
    )
    monkeypatch.setattr(
        evaluator_cls, "_resolve_live_binding",
        classmethod(lambda cls, **_: (Path("/nonexistent/localstorage.sqlite3"), {"pass": True})),
    )

    def fake_read(cls, **_):
        state = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return state, {"quick_check": "ok"}

    monkeypatch.setattr(evaluator_cls, "_read_state_snapshot", classmethod(fake_read))
    return evaluator_cls().evaluate({"params": params})


def test_trip_gear_evaluate_waits_for_the_late_review_write(monkeypatch):
    complete = trip_reference_state()
    before_flush = trip_reference_state()
    for order in before_flush["users"][trip.ACCOUNT_PHONE]["orders"]:
        for item in order["items"]:
            item.pop("review", None)
    result = _run_evaluate(
        monkeypatch, TRIP, trip, "openshop_trip_gear_dual_checkout_review_263796.yaml",
        [before_flush, complete],
    )
    assert result.status.value == "PASS", result.message
    settle = result.metadata["observed"]["database"]["settle"]
    assert settle["stop_reason"] == "accepted" and settle["attempts"] == 2


def test_trip_gear_evaluate_still_fails_a_stable_wrong_state(monkeypatch):
    wrong = trip_reference_state()
    wrong["users"][trip.ACCOUNT_PHONE]["orders"][1]["note"] = "Pack travel gear"
    result = _run_evaluate(
        monkeypatch, TRIP, trip, "openshop_trip_gear_dual_checkout_review_263796.yaml", [wrong],
    )
    assert result.status.value == "FAIL"
    assert result.metadata["observed"]["database"]["settle"]["stop_reason"] == "stable"


def test_home_evaluate_waits_for_the_late_review_write(monkeypatch):
    complete = _home_reference_state(1)
    before_flush = _home_reference_state(1)
    before_flush["users"][home.ACCOUNT_PHONE]["orders"][1]["items"][2].pop("review")
    result = _run_evaluate(
        monkeypatch, HOME, home, "openshop_home_four_item_cart_checkout_368575.yaml",
        [before_flush, complete],
    )
    assert result.status.value == "PASS", result.message
    assert result.metadata["observed"]["database"]["settle"]["attempts"] == 2
