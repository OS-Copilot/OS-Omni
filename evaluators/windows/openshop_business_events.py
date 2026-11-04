"""Business-event contract for the Windows OpenShop order/review evaluators.

The briefs ask for orders and reviews, not for the recorded click path.  From
the app's ``/api/benchmark`` log these checks keep only the business actions
the brief asks for, and only the orders it states or that logic forces:

* a sign-in for the task account before the first checkout (an order belongs
  to the signed-in account); a task may also require it before the first
  cart addition when its brief says "sign in ..., then ...";
* every item of an order added to the cart with its expected spec before that
  order's checkout;
* exactly one ``checkout_submitted`` per expected order, bound to that order's
  id, note and item count, and no other checkout in the session;
* exactly one ``order_item_reviewed`` per expected review, bound to its order
  id and rating, after that order's checkout, and no other review;
* first additions in a stated sequence, when the brief says the items were
  "added in that exact sequence".

Browsing (catalog and product views, searches), the checkout address/payment
clicks and the cart stepper are never required or counted: the order record
decides address, payment, specs and quantities, so a quantity reached by
repeated "Add to Cart" or by the stepper both pass.  Orders labelled "first" or
"second" in a brief are bound by their note, not by when they were placed.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

TASK_PHONE = "13800138000"

POLICY = {
    "required": [
        "session_login_success before the first checkout",
        "cart_item_added (expected spec) for every order item before that order's checkout",
        "exactly one checkout_submitted per expected order, bound to its order id, note and item count",
        "exactly one order_item_reviewed per expected review, bound to its order id and rating, after that order's checkout",
    ],
    "never_required_or_counted": [
        "catalog_view",
        "product_view",
        "checkout_address_selected",
        "checkout_payment_selected",
        "cart_quantity_updated",
    ],
    "order_binding": "orders are bound by their order note, not by when they were placed",
}


def _of_type(events: Sequence[Mapping[str, Any]], kind: str) -> list[tuple[int, Mapping[str, Any]]]:
    return [(index, event) for index, event in enumerate(events) if str(event.get("type") or "") == kind]


def _brief(event: Mapping[str, Any] | None, *keys: str) -> dict[str, Any]:
    if not event:
        return {}
    return {key: event.get(key) for key in ("seq", "type", *keys) if key in event}


def bind_orders_by_note(
    orders: Sequence[Mapping[str, Any]], expected_orders: Sequence[Mapping[str, Any]]
) -> list[tuple[Mapping[str, Any] | None, list[Mapping[str, Any]]]]:
    """Bind each expected order to the one stored order carrying its note.

    Returns ``(order or None, candidates)`` per expected order; ``None`` when no
    order, or more than one, carries the note.
    """
    bound = []
    for expected in expected_orders:
        candidates = [order for order in orders if str(order.get("note") or "") == str(expected.get("note") or "")]
        bound.append((candidates[0] if len(candidates) == 1 else None, candidates))
    return bound


def has_task_checkouts(events: Iterable[Mapping[str, Any]], notes: Iterable[str]) -> bool:
    """True when the log holds a checkout for every one of the task's order notes."""
    seen = {str(event.get("note") or "") for event in events if event.get("type") == "checkout_submitted"}
    return all(str(note) in seen for note in notes)


def check_business_events(
    events: Sequence[Mapping[str, Any]],
    bound_orders: Sequence[tuple[str, Mapping[str, Any] | None, Mapping[str, Any]]],
    *,
    phone: str = TASK_PHONE,
    item_sequences: Sequence[Sequence[str]] = (),
    login_before_first_add: bool = False,
) -> list[dict[str, Any]]:
    """Return one check record per business-event contract.

    ``bound_orders`` holds ``(label, stored order projection or None, expected
    order)``; the projection and the expectation carry ``id``/``note`` and
    ``items`` keyed by product id with ``selected_spec`` and ``rating`` (``None``
    for an item the brief does not review).
    """
    events = [dict(event or {}) for event in events]
    records: list[dict[str, Any]] = []

    def record(check_id: str, contract: str, passed: bool, expected: Any, actual: Any) -> None:
        records.append({
            "check_id": check_id,
            "value_contract_id": contract,
            "match_mode": "BUSINESS_EVENT_CONTRACT",
            "expected": expected,
            "actual": actual,
            "passed": bool(passed),
        })

    logins = [(i, e) for i, e in _of_type(events, "session_login_success") if str(e.get("phone") or "") == phone]
    checkouts = _of_type(events, "checkout_submitted")
    reviews = _of_type(events, "order_item_reviewed")
    adds = _of_type(events, "cart_item_added")

    first_login = logins[0][0] if logins else None
    login_deadline = checkouts[0][0] if checkouts else None
    if login_before_first_add:
        order_products = {pid for _, _, expected in bound_orders for pid in dict(expected.get("items") or {})}
        first_adds = [i for i, e in adds if str(e.get("productId") or "") in order_products]
        if first_adds:
            login_deadline = min(first_adds) if login_deadline is None else min(login_deadline, min(first_adds))
    login_ok = first_login is not None and (login_deadline is None or first_login < login_deadline)
    record(
        "events.login", "session_login_before_business_actions", login_ok,
        {"phone": phone, "before": "first cart addition" if login_before_first_add else "first checkout"},
        {"login": _brief(logins[0][1] if logins else None, "phone"), "first_login_index": first_login, "deadline_index": login_deadline},
    )

    record(
        "events.checkout_count", "one_checkout_per_expected_order", len(checkouts) == len(bound_orders),
        len(bound_orders), [_brief(e, "orderId", "note", "itemCount") for _, e in checkouts],
    )
    expected_review_total = sum(
        1 for _, _, expected in bound_orders for item in dict(expected.get("items") or {}).values() if item.get("rating") is not None
    )
    record(
        "events.review_count", "one_review_per_expected_review", len(reviews) == expected_review_total,
        expected_review_total, [_brief(e, "orderId", "productId", "rating") for _, e in reviews],
    )

    for label, order, expected in bound_orders:
        items = dict(expected.get("items") or {})
        order_id = str((order or {}).get("id") or "")
        own = [(i, e) for i, e in checkouts if order_id and str(e.get("orderId") or "") == order_id]
        checkout_ok = (
            len(own) == 1
            and str(own[0][1].get("note") or "") == str(expected.get("note") or "")
            and int(own[0][1].get("itemCount") or 0) == len(items)
        )
        checkout_index = own[0][0] if len(own) == 1 else None
        record(
            f"{label}.checkout_event", f"{label}_checkout_binding", checkout_ok,
            {"orderId": order_id or "<bound order>", "note": expected.get("note"), "itemCount": len(items)},
            [_brief(e, "orderId", "note", "itemCount") for _, e in own],
        )

        missing = []
        for product_id, item in items.items():
            spec = str(item.get("selected_spec") or "")
            if not any(
                str(e.get("productId") or "") == product_id and str(e.get("selectedSpec") or "") == spec
                and (checkout_index is None or i < checkout_index)
                for i, e in adds
            ):
                missing.append({"productId": product_id, "selectedSpec": spec})
        record(
            f"{label}.items_added", f"{label}_items_added_before_checkout",
            checkout_index is not None and not missing,
            sorted(items), {"missing_before_checkout": missing},
        )

        review_rows = []
        reviews_ok = checkout_index is not None
        for product_id, item in items.items():
            if item.get("rating") is None:
                continue
            mine = [(i, e) for i, e in reviews if order_id and str(e.get("orderId") or "") == order_id
                    and str(e.get("productId") or "") == product_id]
            ok = (
                len(mine) == 1
                and int(mine[0][1].get("rating") or 0) == int(item["rating"])
                and checkout_index is not None and mine[0][0] > checkout_index
            )
            reviews_ok = reviews_ok and ok
            review_rows.append({"productId": product_id, "rating": item["rating"], "events": [_brief(e, "orderId", "rating") for _, e in mine], "passed": ok})
        record(f"{label}.review_events", f"{label}_reviews_after_checkout", reviews_ok, "one review per expected item after the checkout", review_rows)

    for number, sequence in enumerate(item_sequences, 1):
        spec_by_product = {pid: str(item.get("selected_spec") or "") for _, _, exp in bound_orders for pid, item in dict(exp.get("items") or {}).items()}
        positions = []
        for product_id in sequence:
            first = next((i for i, e in adds if str(e.get("productId") or "") == product_id
                          and str(e.get("selectedSpec") or "") == spec_by_product.get(product_id, str(e.get("selectedSpec") or ""))), None)
            positions.append(first)
        ok = all(p is not None for p in positions) and all(a < b for a, b in zip(positions, positions[1:]))
        record(
            f"events.stated_item_sequence_{number}", "stated_first_addition_sequence", ok,
            list(sequence), [{"productId": pid, "first_add_index": pos} for pid, pos in zip(sequence, positions)],
        )
    return records
