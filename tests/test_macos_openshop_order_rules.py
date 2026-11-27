"""macOS OpenShop Lucas tasks: grade what the brief orders, not the demo ledger.

* "The first order ... The second order ..." are record labels, so the two new
  orders may be placed in either order (the old evaluator pinned them to
  newest-first positions and failed a swapped placement).
* The recorded ledger (searches, product views, add-to-cart vs quantity
  stepper, review order) is a non-blocking diagnostic.
* Kept as blocking: what the brief states --
  - workshop pantry: "place two new orders followed by a review on a
    historical order" (both checkouts before the historical review);
  - coffee/trail mix: the searches it names in named categories (at least once
    each) and the coffee review "replacing an initial 4 / 5 rating";
  - coffee/trail mix: the review texts may be typed with the punctuation the
    brief prints inside the quotes (“Good to share,” / “Compact travel bag.”)
    or without it.
* Durable order/review/cart/session checks still fail duplicates and wrong
  records.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from evaluators.cua_review.core.evaluation import EvalStatus

ROOT = Path(__file__).resolve().parents[1]
TASKS = {
    "client_room": "openshop_lucas_client_room_hybrid_work_two_orders_five_reviews",
    "coffee": "openshop_lucas_coffee_trailmix_backpack_reviews",
    "workshop": "openshop_lucas_workshop_pantry_mobile_work_two_orders_five_reviews",
}
ADDRESS_IDS = {"Office": "addr-office"}


def _task(name: str) -> dict:
    return yaml.safe_load((ROOT / "tasks/v1/macos" / f"{TASKS[name]}.yaml").read_text(encoding="utf-8"))


def _evaluator(task: dict):
    module_name, class_name = task["evaluation"]["evaluator_id"].split(":")
    return getattr(importlib.import_module(module_name), class_name)()


class _Controller:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def run_python_script(self, code: str, timeout: int = 0) -> dict:
        return {"returncode": 0, "stdout": json.dumps(self.payload)}


def _order(expectation: dict, order_id: str) -> dict:
    return {
        "id": order_id,
        "status": expectation.get("status", "Delivered"),
        "total": expectation.get("total", 10),
        "note": expectation.get("note", ""),
        "address": {
            "id": ADDRESS_IDS.get(expectation.get("address_label", ""), "addr-home"),
            "label": expectation.get("address_label", "Home"),
            "receiver": expectation.get("address_receiver", "Lucas Lin"),
            "fullAddress": expectation.get("address_full", ""),
        },
        "payment": {
            "id": expectation.get("payment_id", "alipay"),
            "label": expectation.get("payment_label", "Alipay"),
            "desc": expectation.get("payment_desc", ""),
        },
        "items": [
            {
                "id": f"{order_id}-{item['product_id']}",
                "product": {"id": item["product_id"]},
                "quantity": item.get("quantity", 1),
                "selectedSpec": item.get("selected_spec", ""),
                "review": (
                    {"rating": item["review"]["rating"], "review": item["review"]["text"]}
                    if "review" in item
                    else None
                ),
            }
            for item in expectation.get("items", [])
        ],
    }


class Run:
    """A correct final state plus a ledger that can be reshaped per test."""

    def __init__(self, name: str, *, placement: list[str] | None = None) -> None:
        self.task = _task(name)
        self.params = copy.deepcopy(self.task["evaluation"]["params"])
        orders_spec = self.params["orders"]
        recent = {item["label"]: item for item in orders_spec["recent"]}
        # Brief/demo placement: recent is newest first, so the demo placed it reversed.
        self.placement = placement or [item["label"] for item in orders_spec["recent"]][::-1]
        self.new_orders = {
            label: _order(recent[label], f"TBH-LUCAS-NEW-{index}")
            for index, label in enumerate(self.placement)
        }
        historical = [
            _order({"items": [{"product_id": item["product_id"], **({"review": item["review"]})}
                              for item in spec["items"]]}, spec["order_id"])
            for spec in orders_spec.get("by_id", [])
        ]
        fillers = [
            _order({"items": [{"product_id": "p9999"}]}, f"TBH-LUCAS-SEED-{index}")
            for index in range(orders_spec["count"] - len(recent) - len(historical))
        ]
        self.orders = [*(self.new_orders[label] for label in self.placement[::-1]), *historical, *fillers]
        self.events: list[dict[str, Any]] = [{"type": "session_login_success", "phone": "13800138000"}]
        self.reviews: dict[str, list[dict[str, Any]]] = {}
        for label in self.placement:
            order = self.new_orders[label]
            spec = recent[label]
            for item in spec["items"]:
                self.events.append(
                    {"type": "cart_item_added", "productId": item["product_id"],
                     "selectedSpec": item["selected_spec"], "quantity": item["quantity"]}
                )
            self.events.append(
                {"type": "checkout_submitted", "orderId": order["id"],
                 "addressId": order["address"]["id"], "paymentMethodId": order["payment"]["id"],
                 "note": order["note"], "total": order["total"], "itemCount": len(order["items"])}
            )
            self.reviews[label] = [
                self.review_event(order["id"], item["product_id"], item["review"]["rating"])
                for item in spec["items"]
            ]
        self.historical_reviews = [
            self.review_event(spec["order_id"], item["product_id"], item["review"]["rating"])
            for spec in orders_spec.get("by_id", [])
            for item in spec["items"]
        ]

    @staticmethod
    def review_event(order_id: str, product_id: str, rating: int) -> dict[str, Any]:
        return {"type": "order_item_reviewed", "orderId": order_id, "productId": product_id, "rating": rating}

    def new_order(self, label: str) -> dict:
        return self.new_orders[label]

    def evaluate(self, events: list[dict[str, Any]] | None = None):
        if events is None:
            events = [*self.events, *(e for label in self.placement for e in self.reviews[label]),
                      *self.historical_reviews]
        payload = {
            "session": {"session": {"loggedIn": True, "user": {"phone": "13800138000", "name": "Lucas Lin"}}},
            "cart": {"items": [], "total": 0},
            "orders": {"orders": self.orders},
            "benchmark": {"events": events},
        }
        observation = SimpleNamespace(foreground_app="OpenShop", foreground_bundle_id="local.osomni.openshop", ui_nodes=[])
        return _evaluator(self.task).evaluate(
            {"params": self.params, "controller": _Controller(payload), "final_observation": observation}
        )


def _failed(result) -> list[str]:
    return [check["check"] for check in result.metadata["checks"] if not check["pass"] and not check.get("diagnostic")]


def _ledger_diagnostic(result) -> dict:
    return next(d for d in result.metadata["diagnostics"] if d["diagnostic_id"] == "benchmark.ordered")


# --------------------------------------------------------------------------
# two-order tasks: "the first order" / "the second order" are labels
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["client_room", "workshop"])
def test_two_new_orders_placed_in_either_order_pass(name: str) -> None:
    run = Run(name, placement=["second_new_order", "first_new_order"])
    result = run.evaluate()

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]
    assignment = result.metadata["recent_order_assignment"]
    assert assignment["mode"] == "unordered"
    assert assignment["orders"]["first_new_order"]["position"] == 0  # placed last, newest


@pytest.mark.parametrize("name", ["client_room", "workshop"])
def test_positional_opt_in_reproduces_the_old_failure(name: str) -> None:
    # Pre-fix behaviour: the swapped placement failed on recency positions alone.
    run = Run(name, placement=["second_new_order", "first_new_order"])
    run.params["orders"]["recent_in_order"] = True
    result = run.evaluate()

    assert result.status == EvalStatus.FAIL
    assert all(check.startswith("recent[") for check in _failed(result))


@pytest.mark.parametrize("name", ["client_room", "workshop"])
def test_reviews_swapped_between_the_two_orders_fail(name: str) -> None:
    run = Run(name)
    first = run.new_order("first_new_order")["items"]
    second = run.new_order("second_new_order")["items"]
    first[0]["review"], second[0]["review"] = second[0]["review"], first[0]["review"]
    result = run.evaluate()

    assert result.status == EvalStatus.FAIL
    assert any(check.endswith(".review.text") for check in _failed(result))


@pytest.mark.parametrize("name", ["client_room", "workshop"])
def test_an_extra_order_fails(name: str) -> None:
    run = Run(name)
    run.orders.insert(0, copy.deepcopy(run.new_order("first_new_order")))
    run.orders[0]["id"] = "TBH-LUCAS-DUP"
    result = run.evaluate()

    assert result.status == EvalStatus.FAIL
    assert "orders.count" in _failed(result)


def test_client_room_states_no_order_so_historical_review_first_passes() -> None:
    run = Run("client_room")
    events = [*run.events[:1], *run.historical_reviews, *run.events[1:],
              *run.reviews["second_new_order"], *run.reviews["first_new_order"]]
    result = run.evaluate(events)

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]
    assert _ledger_diagnostic(result)["passed"] is False
    assert _ledger_diagnostic(result)["blocking"] is False


# --------------------------------------------------------------------------
# workshop pantry: "place two new orders followed by a review on a historical order"
# --------------------------------------------------------------------------


def _workshop_events(run: Run, *, historical_after: int) -> list[dict[str, Any]]:
    """Ledger with the historical review inserted after ``historical_after`` checkouts."""
    events: list[dict[str, Any]] = []
    checkouts = 0
    if historical_after == 0:
        events.extend(run.historical_reviews)
    for event in run.events:
        events.append(event)
        if event["type"] == "checkout_submitted":
            checkouts += 1
            if checkouts == historical_after:
                events.extend(run.historical_reviews)
    for label in run.placement:
        events.extend(run.reviews[label])
    return events


@pytest.mark.parametrize("placement", [None, ["second_new_order", "first_new_order"]])
def test_workshop_historical_review_after_both_orders_passes(placement) -> None:
    run = Run("workshop", placement=placement)
    result = run.evaluate(_workshop_events(run, historical_after=2))

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]


@pytest.mark.parametrize("historical_after", [0, 1])
def test_workshop_historical_review_before_an_order_fails(historical_after: int) -> None:
    run = Run("workshop")
    result = run.evaluate(_workshop_events(run, historical_after=historical_after))

    assert result.status == EvalStatus.FAIL
    failed = _failed(result)
    assert failed and all(check.startswith("benchmark.precedence.") for check in failed)
    second_placed = "mobile_work_pair_order_before_historical_review"
    assert f"benchmark.precedence.{second_placed}" in failed


def test_workshop_coffee_quantity_by_stepper_or_by_adding_twice_both_pass() -> None:
    run = Run("workshop")
    stepper = [dict(e, quantity=1) if e.get("productId") == "p1005" and e["type"] == "cart_item_added" else e
               for e in run.events]
    index = next(i for i, e in enumerate(stepper) if e.get("productId") == "p1005")
    stepped = [*stepper[: index + 1], {"type": "cart_quantity_updated", "productId": "p1005", "quantity": 2},
               *stepper[index + 1:]]
    added_twice = [*stepper[: index + 1], dict(stepper[index]), *stepper[index + 1:]]
    for ledger in (stepped, added_twice):
        events = [*ledger, *(e for label in run.placement for e in run.reviews[label]), *run.historical_reviews]
        result = run.evaluate(events)
        assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]


# --------------------------------------------------------------------------
# coffee / trail mix / backpack
# --------------------------------------------------------------------------


SEARCHES = [
    {"type": "catalog_view", "query": "mountain isle", "category": "Grocery", "sort": "default"},
    {"type": "catalog_view", "query": "small batch trail", "category": "Grocery", "sort": "default"},
    {"type": "catalog_view", "query": "polar day", "category": "Bags", "sort": "default"},
]


def _coffee_events(run: Run, *, searches=None, initial_review=True, add_twice=False, historical_first=False):
    order_id = run.new_order("latest_new_order")["id"]
    login, *rest = run.events
    shopping: list[dict[str, Any]] = []
    for event in rest:
        if event["type"] == "cart_item_added" and event["quantity"] == 2:
            single = dict(event, quantity=1)
            shopping.append(single)
            shopping.append(dict(single) if add_twice else
                            {"type": "cart_quantity_updated", "productId": event["productId"], "quantity": 2})
        else:
            shopping.append(event)
    new_reviews = list(run.reviews["latest_new_order"])
    if initial_review:
        new_reviews.insert(0, run.review_event(order_id, "p1005", 4))
    reviews = [*run.historical_reviews, *new_reviews] if historical_first else [*new_reviews, *run.historical_reviews]
    return [login, *(SEARCHES if searches is None else searches), *shopping, *reviews]


def test_coffee_any_valid_order_and_add_twice_pass() -> None:
    run = Run("coffee")
    result = run.evaluate(_coffee_events(run, add_twice=True, historical_first=True,
                                         searches=[*SEARCHES[::-1], SEARCHES[0]]))

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]
    assert _ledger_diagnostic(result)["passed"] is False


def test_coffee_old_ordered_ledger_opt_in_fails_the_same_run() -> None:
    run = Run("coffee")
    run.params["benchmark"]["require_ordered"] = True
    result = run.evaluate(_coffee_events(run, add_twice=True, historical_first=True))

    assert result.status == EvalStatus.FAIL
    assert all(check.startswith("benchmark.ordered[") for check in _failed(result))


@pytest.mark.parametrize(
    ("product_id", "typed"),
    [("p2048", "Good to share,"), ("p2048", "Good to share"), ("p1004", "Compact travel bag."), ("p1004", "Compact travel bag")],
)
def test_coffee_review_text_with_or_without_the_quoted_punctuation_passes(product_id: str, typed: str) -> None:
    run = Run("coffee")
    item = next(i for i in run.new_order("latest_new_order")["items"] if i["product"]["id"] == product_id)
    item["review"]["review"] = typed
    result = run.evaluate(_coffee_events(run))

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]


@pytest.mark.parametrize("typed", ["Good to share!", "Good to share, Compact travel bag.", "Good"])
def test_coffee_other_review_texts_still_fail(typed: str) -> None:
    run = Run("coffee")
    item = next(i for i in run.new_order("latest_new_order")["items"] if i["product"]["id"] == "p2048")
    item["review"]["review"] = typed
    result = run.evaluate(_coffee_events(run))

    assert result.status == EvalStatus.FAIL
    assert _failed(result) == ["recent[0] (latest_new_order).item.p2048.review.text"]


@pytest.mark.parametrize(
    ("searches", "missing"),
    [
        (SEARCHES[:2], "polar_day_search_in_bags"),
        ([*SEARCHES[:2], dict(SEARCHES[2], category="All")], "polar_day_search_in_bags"),
        ([dict(SEARCHES[0], category="All"), *SEARCHES[1:]], "mountain_isle_search_in_grocery"),
    ],
)
def test_coffee_brief_named_search_missing_or_in_wrong_category_fails(searches, missing: str) -> None:
    run = Run("coffee")
    result = run.evaluate(_coffee_events(run, searches=searches))

    assert result.status == EvalStatus.FAIL
    assert _failed(result) == [f"benchmark.required_event.{missing}"]


def test_coffee_search_typed_on_product_page_with_original_case_counts() -> None:
    run = Run("coffee")
    searches = [dict(s, query=s["query"].title()) for s in SEARCHES]
    result = run.evaluate(_coffee_events(run, searches=searches))

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]


def test_coffee_without_the_initial_four_star_review_fails() -> None:
    run = Run("coffee")
    result = run.evaluate(_coffee_events(run, initial_review=False))

    assert result.status == EvalStatus.FAIL
    assert _failed(result) == ["benchmark.precedence.initial_coffee_review_replaced"]


def test_coffee_initial_review_on_a_historical_order_does_not_count() -> None:
    run = Run("coffee")
    events = _coffee_events(run, initial_review=False)
    events.insert(-3, run.review_event("TBH-LUCAS-20260429-002", "p1005", 4))
    result = run.evaluate(events)

    assert result.status == EvalStatus.FAIL
    assert _failed(result) == ["benchmark.precedence.initial_coffee_review_replaced"]


def test_coffee_final_five_star_before_the_four_star_fails() -> None:
    run = Run("coffee")
    order_id = run.new_order("latest_new_order")["id"]
    events = _coffee_events(run, initial_review=False)
    events.append(run.review_event(order_id, "p1005", 4))
    result = run.evaluate(events)

    assert result.status == EvalStatus.FAIL
    assert _failed(result) == ["benchmark.precedence.initial_coffee_review_replaced"]
