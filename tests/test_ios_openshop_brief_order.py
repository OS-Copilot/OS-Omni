"""iOS OpenShop 807073 / 958608 / 368575 / 263796: grade the orders the brief states.

"The first order" / "the second order" are labels, so in-window orders are
matched to the brief by content, not by placement time. Line items are graded
by position only where the brief says "in this exact sequence" (807073, 958608);
otherwise by product (368575, 263796). The only time orders kept:

* 807073: each cart in its stated sequence; the review "immediately following"
  the first order (no other cart addition or order placement in between);
* 958608: each cart in its stated sequence; both reviews "following the
  placement of the first order";
* 368575: "Place two separate orders ... and then submit two product reviews";
* 263796: logical only (the reviewed order exists before its review).

Every order's items are in the cart before it is placed (per-order check).
807073 / 958608 also re-read WebKit localStorage until it settles (IOS-034/036).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from evaluators.ios import openshop_beauty_office_checkout_review_807073 as beauty
from evaluators.ios import openshop_coffee_baby_dual_checkout_958608 as coffee
from evaluators.ios import openshop_home_four_item_cart_checkout_368575 as home
from evaluators.ios import openshop_trip_gear_dual_checkout_review_263796 as trip

REPO = Path(__file__).resolve().parents[1]
WINDOW_START = datetime(2026, 10, 11, 15, 30, tzinfo=timezone.utc)
T0 = 1_791_732_640_000
BEAUTY = beauty.OpenShopBeautyOfficeCheckoutReview807073Evaluator
COFFEE = coffee.OpenShopCoffeeBabyDualCheckout958608Evaluator
HOME = home.OpenShopHomeFourItemCartCheckout368575Evaluator
TRIP = trip.OpenShopTripGearDualCheckoutReview263796Evaluator
SEEDED = {"pass": True, "source": "synthetic", "applications": [],
          "seed_account": {"passwordHash": "fnv1a-900f7aee"}}


def _ts(epoch_ms):
    value = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _order(spec, placed_s, cart_s, reviews=None, *, item_order=None, total=None):
    """One persisted order: cart_s[i] is the cart-add second of spec item i."""
    reviews = reviews or {}
    rows = []
    for index, expected in enumerate(spec["items"]):
        row = {
            "id": f"cart-{T0 + cart_s[index] * 1000}",
            "quantity": expected["quantity"],
            "selectedSpec": expected["selected_spec"],
            "unitPrice": expected["unit_price"],
            "lineTotal": expected["line_total"],
            "product": {"id": expected["product_id"], "title": expected["title"],
                        "category": expected["category"]},
        }
        if expected["product_id"] in reviews:
            review_spec, second = reviews[expected["product_id"]]
            row["review"] = {"rating": review_spec["rating"], "review": review_spec["review"],
                             "reviewedAt": _ts(T0 + second * 1000)}
        rows.append(row)
    if item_order is not None:
        rows = [rows[index] for index in item_order]
    created_ms = T0 + placed_s * 1000
    return {"id": f"TB{created_ms}", "createdAt": _ts(created_ms), "address": spec["address"],
            "payment": spec["payment"], "note": spec["note"], "items": rows,
            "total": spec["total"] if total is None else total, "status": spec["status"]}


def _state(module, *orders):
    """Orders are stored newest first, as the app prepends them."""
    stored = sorted(orders, key=lambda order: order["createdAt"], reverse=True)
    return {"session": {"loggedIn": True, "user": {"name": module.ACCOUNT_NAME,
                                                   "phone": module.ACCOUNT_PHONE}},
            "users": {module.ACCOUNT_PHONE: {"cart": [], "orders": stored}}}


def _grade(evaluator, state):
    return evaluator._evaluate_state(state, window_start=WINDOW_START, window_end=None,
                                     app_binding=SEEDED)


def _failed(result):
    return {check["name"] for check in result.metadata["failures"]}


def _violations(result):
    check = next(c for c in result.metadata["checks"]
                 if c["name"] == "durable_events_and_required_order")
    return check["observed"]["order_violations"]


# ---------------------------------------------------------------------------
# 263796 trip gear: no stated order
# ---------------------------------------------------------------------------

TRIP_FIRST, TRIP_SECOND, TRIP_REVIEW = trip.CHECKPOINT_SPECS


def _trip(first_at, second_at, review_at, *, first_items=(0, 1, 2), second_items=(0, 1, 2)):
    first = _order(TRIP_FIRST, first_at, [first_at - 3, first_at - 2, first_at - 1],
                   item_order=list(first_items))
    second = _order(TRIP_SECOND, second_at, [second_at - 3, second_at - 2, second_at - 1],
                    {TRIP_REVIEW["product_id"]: (TRIP_REVIEW, review_at)},
                    item_order=list(second_items))
    return _state(trip, first, second)


def test_trip_recorded_order_passes():
    result = _grade(TRIP, _trip(10, 20, 30))
    assert result.status.value == "PASS", _failed(result)


def test_trip_second_order_first_and_items_in_another_position_passes():
    # Blue Tin order placed and reviewed before the backpack order; items stored
    # in a different position than the brief lists them.
    result = _grade(TRIP, _trip(40, 10, 20, first_items=(2, 0, 1), second_items=(1, 2, 0)))
    assert result.status.value == "PASS", _failed(result)


def test_trip_review_before_its_order_or_wrong_note_fails():
    early = _grade(TRIP, _trip(10, 20, 15))
    assert _failed(early) == {"durable_events_and_required_order"}
    assert ["second_order_exact.placed", "blue_tin_review_exact.submitted"] in _violations(early)

    state = _trip(40, 10, 20)
    state["users"][trip.ACCOUNT_PHONE]["orders"][0]["note"] = "Pack travel gear"
    assert "first_order_exact" in _failed(_grade(TRIP, state))


def test_trip_duplicate_order_fails():
    state = _trip(10, 20, 30)
    state["users"][trip.ACCOUNT_PHONE]["orders"].insert(0, _order(TRIP_FIRST, 50, [45, 46, 47]))
    assert "causal_window_order_cardinality" in _failed(_grade(TRIP, state))


# ---------------------------------------------------------------------------
# 368575 home: "Place two separate orders ... and then submit two product reviews"
# ---------------------------------------------------------------------------

OFFICE_SPEC, HOME_SPEC, CASAPURE, MUKAWA = home.CHECKPOINT_SPECS


def _home(office_at, home_at, casapure_at, mukawa_at, *, office_items=(0, 1, 2),
          home_items=(0, 1, 2, 3)):
    office = _order(OFFICE_SPEC, office_at, [office_at - 3, office_at - 2, office_at - 1],
                    {MUKAWA["product_id"]: (MUKAWA, mukawa_at)}, item_order=list(office_items))
    home_order = _order(HOME_SPEC, home_at, [home_at - 4, home_at - 3, home_at - 2, home_at - 1],
                        {CASAPURE["product_id"]: (CASAPURE, casapure_at)},
                        item_order=list(home_items))
    return _state(home, office, home_order)


def test_home_recorded_order_passes():
    result = _grade(HOME, _home(10, 20, 30, 40))
    assert result.status.value == "PASS", _failed(result)


def test_home_orders_and_reviews_in_another_order_pass():
    result = _grade(HOME, _home(20, 10, 40, 30, office_items=(2, 1, 0), home_items=(3, 0, 2, 1)))
    assert result.status.value == "PASS", _failed(result)


def test_home_review_before_both_orders_are_placed_fails():
    result = _grade(HOME, _home(10, 30, 35, 20))
    assert _failed(result) == {"durable_events_and_required_order"}
    assert _violations(result) == [["home_order_exact.placed", "mukawa_review_exact.submitted"]]


def test_home_wrong_quantity_or_extra_review_fails():
    state = _home(20, 10, 40, 30)
    item = next(row for order in state["users"][home.ACCOUNT_PHONE]["orders"]
                for row in order["items"] if row["product"]["id"] == "p2024")
    item["quantity"] = 2
    assert "home_order_exact" in _failed(_grade(HOME, state))

    state = _home(20, 10, 40, 30)
    other = next(row for order in state["users"][home.ACCOUNT_PHONE]["orders"]
                 for row in order["items"] if row["product"]["id"] not in {"p2024", "p1002"})
    other["review"] = {"rating": 5, "review": "extra", "reviewedAt": _ts(T0 + 45_000)}
    assert "causal_window_review_cardinality" in _failed(_grade(HOME, state))


# ---------------------------------------------------------------------------
# 807073 beauty/office: sequenced carts; review immediately follows the first order
# ---------------------------------------------------------------------------

_, B_FIRST, B_REVIEW, B_SECOND = beauty.CHECKPOINT_SPECS


def _beauty(first_at, review_at, second_at, *, first_cart=None, second_cart=None, first_items=None):
    first_cart = first_cart or [first_at - 5 + index for index in range(5)]
    second_cart = second_cart or [second_at - 2, second_at - 1]
    first = _order(B_FIRST, first_at, first_cart, {B_REVIEW["product_id"]: (B_REVIEW, review_at)},
                   item_order=first_items)
    second = _order(B_SECOND, second_at, second_cart)
    return _state(beauty, first, second)


def test_beauty_recorded_order_passes():
    result = _grade(BEAUTY, _beauty(10, 11, 20))
    assert result.status.value == "PASS", _failed(result)


def test_beauty_second_order_placed_first_passes():
    result = _grade(BEAUTY, _beauty(20, 21, 10))
    assert result.status.value == "PASS", _failed(result)


def test_beauty_cart_out_of_the_stated_sequence_fails():
    swapped = _grade(BEAUTY, _beauty(10, 11, 20, first_items=[1, 0, 2, 3, 4]))
    assert "first_order_exact" in _failed(swapped)

    late_first_item = _grade(BEAUTY, _beauty(10, 11, 20, first_cart=[9, 5, 6, 7, 8]))
    assert _failed(late_first_item) == {"durable_events_and_required_order"}
    assert ["first_order_exact.cart_add_1", "first_order_exact.cart_add_2"] in _violations(late_first_item)


def test_beauty_review_not_immediately_after_the_first_order_fails():
    # A second-order cart addition lands between the first order and its review.
    result = _grade(BEAUTY, _beauty(10, 14, 20, second_cart=[12, 15]))
    assert _failed(result) == {"durable_events_and_required_order"}
    assert _violations(result) == [
        ["first_order_exact.placed", "second_order_exact.cart_add_1", "serum_review_exact.submitted"]
    ]


def test_beauty_duplicate_review_or_wrong_record_fails():
    state = _beauty(10, 11, 20)
    second = state["users"][beauty.ACCOUNT_PHONE]["orders"][0]
    second["items"][0]["review"] = {"rating": 5, "review": "x", "reviewedAt": _ts(T0 + 30_000)}
    assert {"no_unexpected_target_reviews", "causal_window_review_cardinality"} <= _failed(
        _grade(BEAUTY, state)
    )

    state = _beauty(10, 11, 20)
    state["users"][beauty.ACCOUNT_PHONE]["orders"][1]["note"] = "Desk"
    assert "first_order_exact" in _failed(_grade(BEAUTY, state))


# ---------------------------------------------------------------------------
# 958608 coffee/baby: sequenced carts; both reviews follow the first order
# ---------------------------------------------------------------------------

_, C_HOME, C_COFFEE, C_HEADPHONES, C_OFFICE = coffee.CHECKPOINT_SPECS


def _coffee(home_at, coffee_at, headphones_at, office_at, *, home_items=None):
    home_order = _order(C_HOME, home_at, [home_at - 4 + index for index in range(4)],
                        {C_COFFEE["product_id"]: (C_COFFEE, coffee_at),
                         C_HEADPHONES["product_id"]: (C_HEADPHONES, headphones_at)},
                        item_order=home_items)
    office = _order(C_OFFICE, office_at, [office_at - 3, office_at - 2, office_at - 1])
    return _state(coffee, home_order, office)


def test_coffee_recorded_order_passes():
    result = _grade(COFFEE, _coffee(10, 11, 12, 20))
    assert result.status.value == "PASS", _failed(result)


def test_coffee_second_order_first_and_reviews_swapped_passes():
    result = _grade(COFFEE, _coffee(20, 30, 25, 10))
    assert result.status.value == "PASS", _failed(result)


def test_coffee_review_before_the_first_order_or_items_out_of_sequence_fails():
    early = _grade(COFFEE, _coffee(20, 15, 25, 10))
    assert _failed(early) == {"durable_events_and_required_order"}
    assert _violations(early) == [["home_order_exact.placed", "coffee_review_exact.submitted"]]

    swapped = _grade(COFFEE, _coffee(10, 11, 12, 20, home_items=[0, 1, 3, 2]))
    assert "home_order_exact" in _failed(swapped)


def test_coffee_duplicate_order_fails():
    state = _coffee(10, 11, 12, 20)
    state["users"][coffee.ACCOUNT_PHONE]["orders"].insert(0, _order(C_OFFICE, 40, [35, 36, 37]))
    assert "causal_window_order_cardinality" in _failed(_grade(COFFEE, state))


# ---------------------------------------------------------------------------
# rulesets and the settled localStorage read
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "module, name",
    [
        (beauty, "openshop_beauty_office_checkout_review_807073"),
        (coffee, "openshop_coffee_baby_dual_checkout_958608"),
        (home, "openshop_home_four_item_cart_checkout_368575"),
        (trip, "openshop_trip_gear_dual_checkout_review_263796"),
    ],
)
def test_tasks_bind_the_updated_ruleset(module, name):
    doc = yaml.safe_load((REPO / "tasks/v1/ios" / f"{name}.yaml").read_text(encoding="utf-8"))
    assert doc["evaluation"]["params"]["expected_ruleset_sha256"] == module.RULESET_SHA256
    assert doc["metadata"]["evaluator_ruleset_sha256"] == module.RULESET_SHA256


def _run_settled(monkeypatch, evaluator_cls, yaml_name, states):
    doc = yaml.safe_load((REPO / "tasks/v1/ios" / yaml_name).read_text(encoding="utf-8"))
    params = dict(doc["evaluation"]["params"], udid="FAKE-UDID",
                  settle_poll_interval_seconds=0.0, settle_stable_seconds=0.0)
    remaining = list(states)
    monkeypatch.setattr(evaluator_cls, "_resolve_causal_window",
                        classmethod(lambda cls, **_: (WINDOW_START, None, "synthetic")))
    monkeypatch.setattr(evaluator_cls, "_resolve_live_binding",
                        classmethod(lambda cls, **_: (Path("/nonexistent/ls.sqlite3"), dict(SEEDED))))

    def fake_read(cls, **_):
        state = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return state, {"quick_check": "ok"}

    monkeypatch.setattr(evaluator_cls, "_read_state_snapshot", classmethod(fake_read))
    return evaluator_cls().evaluate({"params": params})


@pytest.mark.parametrize(
    "evaluator_cls, yaml_name, build, account",
    [
        (BEAUTY, "openshop_beauty_office_checkout_review_807073.yaml",
         lambda: _beauty(10, 11, 20), beauty.ACCOUNT_PHONE),
        (COFFEE, "openshop_coffee_baby_dual_checkout_958608.yaml",
         lambda: _coffee(10, 11, 12, 20), coffee.ACCOUNT_PHONE),
    ],
)
def test_evaluate_waits_for_the_late_final_write(monkeypatch, evaluator_cls, yaml_name, build, account):
    complete = build()
    before_flush = build()
    newest = before_flush["users"][account]["orders"]
    newest.pop(0)  # the last Place Order has not reached disk yet
    result = _run_settled(monkeypatch, evaluator_cls, yaml_name, [before_flush, complete])
    assert result.status.value == "PASS", result.message
    settle = result.metadata["observed"]["database"]["settle"]
    assert settle["stop_reason"] == "accepted" and settle["attempts"] == 2

    wrong = build()
    wrong["users"][account]["orders"][0]["note"] = "wrong note"
    result = _run_settled(monkeypatch, evaluator_cls, yaml_name, [wrong])
    assert result.status.value == "FAIL"
    assert result.metadata["observed"]["database"]["settle"]["stop_reason"] == "stable"
