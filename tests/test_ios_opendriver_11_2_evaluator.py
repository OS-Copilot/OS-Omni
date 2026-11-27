import importlib.util
from pathlib import Path


_PATH = Path(__file__).parents[1] / "evaluators/ios/opendriver_11-2.py"
_SPEC = importlib.util.spec_from_file_location("opendriver_11_2_audit", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)


def test_seeded_refund_targets_accept_real_address_fields_and_reject_wrong_route():
    evaluator = _MODULE.OpenDriverCardDefaultPaymentRefundEvaluator
    rides = [
        {
            "id": target["ride_id"],
            "pickupAddress": target["pickup"],
            "destinationAddress": target["destination"],
            "status": target["status"],
        }
        for target in _MODULE.REFUND_TARGETS
    ]
    walk = _MODULE._Walk()
    evaluator._check_refund_targets(walk, rides)
    assert [check["passed"] for check in walk.checks] == [True, True]

    rides[0]["destinationAddress"] = "Incorrect destination"
    wrong_walk = _MODULE._Walk()
    evaluator._check_refund_targets(wrong_walk, rides)
    assert [check["passed"] for check in wrong_walk.checks] == [False, True]


def test_default_uniqueness_is_scoped_to_the_primary_rider():
    evaluator = _MODULE.OpenDriverCardDefaultPaymentRefundEvaluator
    methods = [
        {"id": "pm_rider_paypal", "userId": "usr_rider_primary", "label": "PayPal rider@example.com", "isDefault": True},
        {"id": "pm_rider_visa", "userId": "usr_rider_primary", "label": "Visa ending 4242", "isDefault": False},
        {"id": "pm_second_rider", "userId": "usr_rider_second", "label": "PayPal rider2@example.com", "isDefault": True},
        {"id": "pm_driver", "userId": "usr_driver_primary", "label": "Visa ending 1881", "isDefault": True},
    ]
    walk = _MODULE._Walk()
    evaluator._check_default_payment(walk, methods)
    assert walk.checks[0]["passed"] is True
    assert walk.checks[0]["actual"]["default_count"] == 1

    methods[1]["isDefault"] = True
    wrong_walk = _MODULE._Walk()
    evaluator._check_default_payment(wrong_walk, methods)
    assert wrong_walk.checks[0]["passed"] is False


def test_support_ticket_requires_exact_task_text():
    evaluator = _MODULE.OpenDriverCardDefaultPaymentRefundEvaluator
    tickets = [
        {"id": "ticket-card", "userId": "usr_rider_primary", "category": "safety concern", "message": "Card charged", "status": "open", "createdAt": "2026-10-11T12:31:00Z"},
        {"id": "ticket-followup", "userId": "usr_rider_primary", "category": "safety concern", "message": "Fare follow-up", "status": "open", "createdAt": "2026-10-11T12:32:00Z"},
        {"id": "ticket-other-user", "userId": "usr_rider_second", "category": "general", "message": "Unrelated", "status": "open", "createdAt": "2026-10-11T12:33:00Z"},
    ]
    walk = _MODULE._Walk()
    evaluator._check_tickets(walk, tickets, "2026-10-11T12:30:00Z")
    assert walk.checks[0]["passed"] is True

    tickets[0]["message"] = "I need help with my ride.Card charged"
    wrong_walk = _MODULE._Walk()
    evaluator._check_tickets(wrong_walk, tickets, "2026-10-11T12:30:00Z")
    assert wrong_walk.checks[0]["passed"] is False


def _complete_reference_state():
    state = {
        "users": [{"id": "usr_rider_primary", "email": "rider@example.com", "role": "rider"}],
        "sessions": [{"id": "session-current", "userId": "usr_rider_primary", "createdAt": "2026-10-11T12:30:00Z"}],
        "rides": [], "paymentMethods": [], "refunds": [], "supportTickets": [],
    }
    card = {
        "id": "pm-reference-1111", "userId": "usr_rider_primary", "type": "card",
        "brand": "Visa", "label": "Visa ending 1111", "last4": "1111",
        "isDefault": False, "status": "active", "createdAt": "2026-10-11T12:30:30Z",
    }
    state["paymentMethods"] = [
        card,
        {"id": "pm_rider_paypal", "userId": "usr_rider_primary", "label": "PayPal rider@example.com", "isDefault": True},
        {"id": "pm_rider_visa", "userId": "usr_rider_primary", "label": "Visa ending 4242", "isDefault": False},
        {"id": "pm_other_default", "userId": "usr_rider_second", "label": "Other account", "isDefault": True},
    ]
    for target in _MODULE.REFUND_TARGETS:
        state["rides"].append({
            "id": target["ride_id"], "pickupAddress": target["pickup"],
            "destinationAddress": target["destination"], "status": target["status"],
        })
    state["rides"].append({
        "id": "ride-reference", "riderId": "usr_rider_primary", "tier": "green",
        "destination": "Stanford University, Stanford, CA",
        "waypoints": ["Downtown Palo Alto, CA"], "status": "cancelled",
        "paymentMethod": card["id"], "createdAt": "2026-10-11T12:31:00Z",
        "cancelledAt": "2026-10-11T12:32:00Z",
    })
    for index, target in enumerate(_MODULE.REFUND_TARGETS, 1):
        state["refunds"].append({
            "id": f"refund-reference-{index}", "userId": "usr_rider_primary",
            "rideId": target["ride_id"], "reason": "Fare review", "status": "requested",
            "createdAt": f"2026-10-11T12:3{index}:00Z",
        })
    for index, message in enumerate(("Card charged", "Fare follow-up"), 1):
        state["supportTickets"].append({
            "id": f"ticket-reference-{index}", "userId": "usr_rider_primary",
            "category": "safety concern", "message": message, "status": "open",
            "createdAt": f"2026-10-11T12:4{index}:00Z",
        })
    state["supportTickets"].append({
        "id": "ticket-other-user", "userId": "usr_rider_second",
        "category": "general", "message": "Unrelated", "status": "open",
        "createdAt": "2026-10-11T12:45:00Z",
    })
    return state


def test_full_correct_state_passes_and_wrong_message_fails():
    evaluator = _MODULE.OpenDriverCardDefaultPaymentRefundEvaluator
    assert evaluator.evaluate_state(_complete_reference_state()).status.value == "PASS"

    wrong = _complete_reference_state()
    next(ticket for ticket in wrong["supportTickets"] if ticket["id"] == "ticket-reference-1")["message"] = "I need help with my ride.Card charged"
    result = evaluator.evaluate_state(wrong)
    assert result.status.value == "FAIL"
    assert "exactly_two_current_session_open_tickets_with_messages" in result.metadata["failed_checks"]
