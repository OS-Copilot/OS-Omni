"""Windows OpenShop order/review tasks: grade business actions, not the click path.

Browsing, checkout clicks and cart-stepper events are never required; a
quantity reached by repeated "Add to Cart" or by the stepper both count.  Only
the core bundle states an order ("sign in ..., then"; items "added in that
exact sequence"); every review follows its own order's checkout.  Each order
and review still happens exactly once.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

import pytest
import yaml

from evaluators.windows import (
    openshop_baby_care_order_574732 as baby,
    openshop_core_bundle_reviews_403191 as core,
    openshop_music_category_order_100114 as music,
    openshop_two_stage_travel_orders_150970 as travel,
)

ROOT = Path(__file__).resolve().parents[1]
PHONE = "13800138000"


class Shop:
    """Serves /api/session, /api/cart, /api/orders and /api/benchmark on port 4310."""

    def __init__(self):
        self.events = []
        self.orders = []  # oldest first; served newest first

    def run_python_script(self, script, timeout=None):
        match = re.search(r"http://127\.0\.0\.1:(\d+)(/api/\w+)", script)
        port, path = int(match.group(1)), match.group(2)
        if port != 4310:
            return {"returncode": 0, "stdout": "OSOMNI_UNREADABLE URLError"}
        payload = {
            "/api/session": {"session": {"loggedIn": True, "user": {"phone": PHONE}}},
            "/api/cart": {"items": []},
            "/api/orders": {"orders": list(reversed(self.orders))},
            "/api/benchmark": {"events": [{**e, "seq": i + 1} for i, e in enumerate(self.events)]},
        }[path]
        return {"returncode": 0, "stdout": json.dumps(payload)}

    def emit(self, kind, **values):
        self.events.append({"type": kind, **values})

    def login(self):
        self.emit("session_login_success", phone=PHONE)

    def browse(self, product_id=None):
        self.emit("catalog_view", query="", category="All")
        if product_id:
            self.emit("product_view", productId=product_id)

    def add(self, product_id, spec, times=1):
        for _ in range(times):
            self.emit("cart_item_added", productId=product_id, selectedSpec=spec, quantity=1)

    def stepper(self, product_id, quantity):
        self.emit("cart_quantity_updated", productId=product_id, quantity=quantity)

    def checkout(self, expected, *, address=None, payment=None, total=None):
        order_id = f"TB{len(self.orders) + 1:04d}"
        items = []
        for pid, item in expected["items"].items():
            items.append({"product": {"id": pid, "title": item["title"]}, "quantity": item["quantity"],
                          "selectedSpec": item["selected_spec"], "review": None})
        self.orders.append({"id": order_id, "address": {"label": address or expected.get("address", "Office")},
                            "payment": {"label": payment or expected.get("payment", "WeChat Pay")},
                            "note": expected["note"], "status": expected["status"],
                            "total": total if total is not None else expected.get("total", 0), "items": items})
        self.emit("checkout_submitted", orderId=order_id, note=expected["note"], itemCount=len(items))
        return order_id

    def review(self, order_id, product_id, rating, text):
        order = next(o for o in self.orders if o["id"] == order_id)
        item = next(i for i in order["items"] if i["product"]["id"] == product_id)
        item["review"] = {"rating": rating, "review": text}
        self.emit("order_item_reviewed", orderId=order_id, productId=product_id, rating=rating)

    def review_all(self, order_id, expected, skip=()):
        for pid, item in expected["items"].items():
            if item["rating"] is not None and pid not in skip:
                self.review(order_id, pid, item["rating"], item["review"])


def complete(shop, expected, *, order=None, stepper=(), address=None, payment=None):
    """Add every item (repeated adds unless listed in ``stepper``), check out, review."""
    for pid in order or list(expected["items"]):
        item = expected["items"][pid]
        shop.browse(pid)
        if pid in stepper:
            shop.add(pid, item["selected_spec"])
            if item["quantity"] > 1:
                shop.stepper(pid, item["quantity"])
        else:
            shop.add(pid, item["selected_spec"], times=item["quantity"])
    order_id = shop.checkout(expected, address=address, payment=payment)
    shop.review_all(order_id, expected)
    return order_id


def run(evaluator_cls, shop, stem):
    params = yaml.safe_load((ROOT / "tasks/v1/windows" / f"{stem}.yaml").read_text(encoding="utf8"))["evaluation"]["params"]
    return evaluator_cls().evaluate({"controller": shop, "params": params})


BABY = baby.OpenShopBabyCareOrderEvaluator.EXPECTED["order"]
CORE = core.OpenShopCoreBundleReviewsEvaluator.EXPECTED["order"]
BABY_STEM, CORE_STEM = "openshop_baby_care_order_574732", "openshop_core_bundle_reviews_403191"
MUSIC_STEM, TRAVEL_STEM = "openshop_music_category_order_100114", "openshop_two_stage_travel_orders_150970"


def run_baby(shop):
    return run(baby.OpenShopBabyCareOrderEvaluator, shop, BABY_STEM)


def test_baby_other_item_order_searches_and_repeated_adds_pass():
    shop = Shop()
    shop.login()
    shop.emit("catalog_view", query="SoftSprout", category="All")
    # p2220 reaches quantity 2 by two adds, p2221 by the stepper; no address/payment clicks.
    complete(shop, BABY, order=["p2627", "p2626", "p2221", "p2220", "p2223", "p2222"], stepper={"p2221", "p2626"})
    shop.browse("p2220")
    result = run_baby(shop)
    assert result.status.value == "PASS", result.message


def baby_shop(**kwargs):
    shop = Shop()
    shop.login()
    return shop, complete(shop, BABY, **kwargs)


def test_baby_duplicate_review_fails():
    shop, order_id = baby_shop()
    shop.review(order_id, "p2223", 3, "BibWipesClean")
    result = run_baby(shop)
    assert result.status.value == "FAIL" and "events.review_count" in result.message


def test_baby_second_checkout_fails():
    shop, _ = baby_shop()
    complete(shop, BABY)
    result = run_baby(shop)
    assert result.status.value == "FAIL" and "events.checkout_count" in result.message


def test_baby_review_bound_to_another_order_fails():
    shop, order_id = baby_shop()
    review = next(e for e in shop.events if e["type"] == "order_item_reviewed" and e["productId"] == "p2222")
    review["orderId"] = "TB-other"
    result = run_baby(shop)
    assert result.status.value == "FAIL" and "order.review_events" in result.message


def test_baby_missing_sixth_product_fails():
    expected = deepcopy(BABY)
    del expected["items"]["p2627"]
    shop = Shop()
    shop.login()
    complete(shop, expected)
    shop.orders[-1]["total"] = BABY["total"]
    assert run_baby(shop).message.startswith("latest_order.items")


def run_core(shop):
    return run(core.OpenShopCoreBundleReviewsEvaluator, shop, CORE_STEM)


CORE_SEQUENCE = ["p1001", "p1005", "p1003", "p1004", "p2071", "p2640"]


def test_core_stated_sequence_with_other_browsing_and_repeated_adds_passes():
    shop = Shop()
    shop.login()
    shop.emit("catalog_view", query="", category="Music")
    shop.emit("product_view", productId="p2304")
    complete(shop, CORE, order=CORE_SEQUENCE, stepper={"p1005"}, address="Home", payment="Cash on Delivery")
    result = run_core(shop)
    assert result.status.value == "PASS", result.message


def test_core_items_added_out_of_the_stated_sequence_fail():
    shop = Shop()
    shop.login()
    order = ["p1005", "p1001", *CORE_SEQUENCE[2:]]
    complete(shop, CORE, order=order, address="Home", payment="Cash on Delivery")
    result = run_core(shop)
    assert result.status.value == "FAIL" and "events.stated_item_sequence_1" in result.message


def test_core_sign_in_after_the_first_addition_fails():
    shop = Shop()
    complete(shop, CORE, order=CORE_SEQUENCE, address="Home", payment="Cash on Delivery")
    shop.events.insert(3, {"type": "session_login_success", "phone": PHONE})
    result = run_core(shop)
    assert result.status.value == "FAIL" and "events.login" in result.message


MUSIC_ORDERS = music.RULESET_SPEC["orders"]


def run_music(shop):
    return run(music.OpenShopMusicCategoryOrder100114Evaluator, shop, MUSIC_STEM)


def test_music_orders_placed_in_another_order_pass():
    # "The first/second/third order" are labels; each review follows its own order.
    shop = Shop()
    shop.login()
    third, first, second = MUSIC_ORDERS[2], MUSIC_ORDERS[0], MUSIC_ORDERS[1]
    complete(shop, third, stepper={"p2305"})
    shop.emit("catalog_view", query="PulseTone", category="All")
    complete(shop, first)
    complete(shop, second, stepper={"p2302"})
    result = run_music(shop)
    assert result.status.value == "PASS", result.message


def music_shop():
    shop = Shop()
    shop.login()
    ids = [complete(shop, MUSIC_ORDERS[0]), complete(shop, MUSIC_ORDERS[1]),
           complete(shop, MUSIC_ORDERS[2], address="Home", payment="Cash on Delivery")]
    return shop, ids


def test_music_duplicate_first_order_fails():
    shop, _ = music_shop()
    complete(shop, MUSIC_ORDERS[0])
    result = run_music(shop)
    assert result.status.value == "FAIL" and result.message.startswith("first_order")


def test_music_third_order_without_stated_payment_fails():
    shop = Shop()
    shop.login()
    complete(shop, MUSIC_ORDERS[0])
    complete(shop, MUSIC_ORDERS[1])
    complete(shop, MUSIC_ORDERS[2], address="Home", payment="Alipay")
    assert run_music(shop).message.startswith("third_order")


def test_music_review_must_follow_its_own_order():
    shop, ids = music_shop()
    # Move the first review ahead of its own checkout.
    review = next(e for e in shop.events if e["type"] == "order_item_reviewed" and e["orderId"] == ids[0])
    shop.events.remove(review)
    checkout = next(i for i, e in enumerate(shop.events) if e["type"] == "checkout_submitted" and e["orderId"] == ids[0])
    shop.events.insert(checkout, review)
    result = run_music(shop)
    assert result.status.value == "FAIL" and "first.review_events" in result.message


TRAVEL_ORDERS = travel.RULESET_SPEC["orders"]


def run_travel(shop):
    return run(travel.OpenShopTwoStageTravelOrders150970Evaluator, shop, TRAVEL_STEM)


def test_travel_second_order_first_passes():
    shop = Shop()
    shop.login()
    complete(shop, TRAVEL_ORDERS[1], address="Home", payment="Alipay")
    complete(shop, TRAVEL_ORDERS[0], stepper={"p2447"}, address="Home", payment="Cash on Delivery")
    result = run_travel(shop)
    assert result.status.value == "PASS", result.message


def test_travel_first_order_placed_twice_fails():
    shop = Shop()
    shop.login()
    complete(shop, TRAVEL_ORDERS[0], address="Home", payment="Cash on Delivery")
    complete(shop, TRAVEL_ORDERS[0], address="Home", payment="Cash on Delivery")
    complete(shop, TRAVEL_ORDERS[1], address="Home", payment="Alipay")
    result = run_travel(shop)
    assert result.status.value == "FAIL" and result.message.startswith("first_order")


def test_travel_missing_review_fails():
    shop = Shop()
    shop.login()
    complete(shop, TRAVEL_ORDERS[0], address="Home", payment="Cash on Delivery")
    for pid in TRAVEL_ORDERS[1]["items"]:
        shop.add(pid, "Trail Kit")
    order_id = shop.checkout(TRAVEL_ORDERS[1], address="Home", payment="Alipay")
    shop.review_all(order_id, TRAVEL_ORDERS[1], skip={"p2449"})
    assert run_travel(shop).message.startswith("second_order")


@pytest.mark.parametrize("module,stem", [(baby, BABY_STEM), (core, CORE_STEM), (music, MUSIC_STEM), (travel, TRAVEL_STEM)])
def test_ruleset_digest_and_task_pins_agree(module, stem):
    digest = hashlib.sha256(json.dumps(module.RULESET_SPEC, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest()
    assert module.RULESET_SHA256 == digest
    for folder in ("tasks/v1/windows",):
        task = yaml.safe_load((ROOT / folder / f"{stem}.yaml").read_text(encoding="utf8"))
        assert task["evaluation"]["params"]["expected_ruleset_sha256"] == digest
