from datetime import datetime, timezone

from evaluators.ios.openshop_trip_gear_dual_checkout_review_263796 import (
    ACCOUNT_ID,
    ACCOUNT_NAME,
    ACCOUNT_PHONE,
    CHECKPOINT_SPECS,
    OpenShopTripGearDualCheckoutReview263796Evaluator,
)


WINDOW_START = datetime(2026, 10, 11, 15, 30, tzinfo=timezone.utc)


def _evaluate(session_user):
    state = {
        "session": {"loggedIn": True, "user": session_user},
        "users": {ACCOUNT_PHONE: {"cart": [], "orders": []}},
    }
    return OpenShopTripGearDualCheckoutReview263796Evaluator._evaluate_state(
        state,
        window_start=WINDOW_START,
        window_end=None,
    )


def _check(result, name):
    return next(item for item in result.metadata["checks"] if item["name"] == name)


def _completed_reference_state():
    first_spec, second_spec, review_spec = CHECKPOINT_SPECS
    now_ms = 1_791_732_640_000

    def timestamp(epoch_ms):
        value = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def order_items(spec, first_item_ms, review=False):
        items = []
        for index, expected in enumerate(spec["items"]):
            epoch_ms = first_item_ms + index * 1000
            item = {
                "id": f"cart-{epoch_ms}",
                "quantity": expected["quantity"],
                "selectedSpec": expected["selected_spec"],
                "unitPrice": expected["unit_price"],
                "lineTotal": expected["line_total"],
                "product": {
                    "id": expected["product_id"],
                    "title": expected["title"],
                    "category": expected["category"],
                },
            }
            if review and expected["product_id"] == review_spec["product_id"]:
                item["review"] = {
                    "rating": review_spec["rating"],
                    "review": review_spec["review"],
                    "reviewedAt": timestamp(now_ms + 9000),
                }
            items.append(item)
        return items

    first_order = {
        "id": f"TB{now_ms + 3000}",
        "createdAt": timestamp(now_ms + 3000),
        "address": first_spec["address"],
        "payment": first_spec["payment"],
        "note": first_spec["note"],
        "items": order_items(first_spec, now_ms),
        "total": first_spec["total"],
        "status": first_spec["status"],
    }
    second_order = {
        "id": f"TB{now_ms + 8000}",
        "createdAt": timestamp(now_ms + 8000),
        "address": second_spec["address"],
        "payment": second_spec["payment"],
        "note": second_spec["note"],
        "items": order_items(second_spec, now_ms + 5000, review=True),
        "total": second_spec["total"],
        "status": second_spec["status"],
    }
    return {
        "session": {
            "loggedIn": True,
            "user": {"name": ACCOUNT_NAME, "phone": ACCOUNT_PHONE},
        },
        "users": {
            ACCOUNT_PHONE: {
                "cart": [],
                "orders": [second_order, first_order],
            }
        },
    }


def test_accepts_current_legacy_openshop_session_shape():
    result = _evaluate({"name": ACCOUNT_NAME, "phone": ACCOUNT_PHONE})

    assert _check(result, "account_binding_exact")["pass"] is True


def test_accepts_current_login_id_when_present():
    result = _evaluate(
        {"id": ACCOUNT_ID, "name": ACCOUNT_NAME, "phone": ACCOUNT_PHONE}
    )

    assert _check(result, "account_binding_exact")["pass"] is True


def test_rejects_wrong_account_phone_or_id():
    wrong_phone = _evaluate({"name": ACCOUNT_NAME, "phone": "13800138001"})
    wrong_id = _evaluate(
        {"id": "someone-else", "name": ACCOUNT_NAME, "phone": ACCOUNT_PHONE}
    )

    assert _check(wrong_phone, "account_binding_exact")["pass"] is False
    assert _check(wrong_id, "account_binding_exact")["pass"] is False


def test_incomplete_order_state_still_fails():
    result = _evaluate({"name": ACCOUNT_NAME, "phone": ACCOUNT_PHONE})

    assert result.status.value == "FAIL"
    assert any(
        check["name"] == "first_order_exact" and not check["pass"]
        for check in result.metadata["checks"]
    )


def test_complete_reference_state_passes():
    result = OpenShopTripGearDualCheckoutReview263796Evaluator._evaluate_state(
        _completed_reference_state(),
        window_start=WINDOW_START,
        window_end=None,
    )

    assert result.status.value == "PASS"
    assert result.metadata["failures"] == []


def test_wrong_note_and_wrong_review_still_fail():
    bad_note = _completed_reference_state()
    bad_note["users"][ACCOUNT_PHONE]["orders"][1]["note"] = "Pack travel gear"
    bad_review = _completed_reference_state()
    bad_review["users"][ACCOUNT_PHONE]["orders"][0]["items"][0]["review"]["rating"] = 5

    assert OpenShopTripGearDualCheckoutReview263796Evaluator._evaluate_state(
        bad_note, window_start=WINDOW_START, window_end=None
    ).status.value == "FAIL"
    assert OpenShopTripGearDualCheckoutReview263796Evaluator._evaluate_state(
        bad_review, window_start=WINDOW_START, window_end=None
    ).status.value == "FAIL"
