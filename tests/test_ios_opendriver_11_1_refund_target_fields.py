import importlib.util
from pathlib import Path


_PATH = Path(__file__).parents[1] / "evaluators/ios/opendriver_11-1.py"
_SPEC = importlib.util.spec_from_file_location("opendriver_11_1_audit", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)
OpenDriverRiderWalletCancellationRefundEvaluator = (
    _MODULE.OpenDriverRiderWalletCancellationRefundEvaluator
)
_Walk = _MODULE._Walk

def _target_rides():
    return [
        {
            "id": "ride_three_month_home_to_work",
            "pickupAddress": "Downtown Palo Alto, CA",
            "destinationAddress": "Meta MPK 23, 300 Constitution Drive, Menlo Park, CA",
        },
        {
            "id": "ride_three_month_school_mall",
            "pickupAddress": "Stanford University, Stanford, CA",
            "destinationAddress": "Stanford Shopping Center, Palo Alto, CA",
        },
    ]


def test_seeded_refund_targets_resolve_api_address_fields():
    walk = _Walk()
    OpenDriverRiderWalletCancellationRefundEvaluator._check_refund_targets(
        walk, _target_rides()
    )

    assert [check["passed"] for check in walk.checks] == [True, True]
    assert walk.checks[0]["actual"]["destination"] == (
        "Meta MPK 23, 300 Constitution Drive, Menlo Park, CA"
    )


def test_wrong_seeded_address_still_fails_refund_target():
    rides = _target_rides()
    rides[0]["destinationAddress"] = "A different destination"
    walk = _Walk()
    OpenDriverRiderWalletCancellationRefundEvaluator._check_refund_targets(walk, rides)

    assert [check["passed"] for check in walk.checks] == [False, True]
    assert "ride_three_month_home_to_work" in walk.failure_reasons[0]


def _complete_reference_state():
    state = {
        "meta": {"seededAt": "2026-06-10T11:37:59.309Z"},
        "users": [
            {"id": "usr_rider_primary", "email": "rider@example.com", "role": "rider"}
        ],
        "sessions": [
            {"id": "session-current", "userId": "usr_rider_primary", "createdAt": "2026-10-11T12:00:00Z"}
        ],
        "rides": _target_rides(),
        "refunds": [],
        "supportTickets": [],
    }
    state["rides"].extend(
        [
            {
                "id": "ride-current-1",
                "tier": "green",
                "destination": "Meta MPK 23, 300 Constitution Drive, Menlo Park, CA",
                "paymentMethod": "pm_rider_paypal",
                "waypoints": ["Stanford University, Stanford, CA"],
                "status": "cancelled",
                "createdAt": "2026-10-11T12:01:00Z",
                "cancelledAt": "2026-10-11T12:02:00Z",
            },
            {
                "id": "ride-current-2",
                "tier": "green",
                "destination": "Downtown Palo Alto, CA",
                "paymentMethod": "pm_rider_visa",
                "waypoints": [],
                "status": "cancelled",
                "createdAt": "2026-10-11T12:03:00Z",
                "cancelledAt": "2026-10-11T12:04:00Z",
            },
        ]
    )
    state["refunds"] = [
        {"id": "refund-1", "rideId": "ride_three_month_home_to_work", "reason": "Fare review", "status": "requested", "createdAt": "2026-10-11T12:05:00Z"},
        {"id": "refund-2", "rideId": "ride_three_month_school_mall", "reason": "Fare review", "status": "requested", "createdAt": "2026-10-11T12:06:00Z"},
    ]
    state["supportTickets"] = [
        {
            "id": "ticket-1",
            "userId": "usr_rider_primary",
            "message": "Blue umbrella",
            "status": "open",
            "createdAt": "2026-10-11T12:07:00Z",
            "replies": [{"id": "reply-1", "message": "Following up on this ticket.Rear seat"}],
        }
    ]
    return state


def test_complete_reference_state_passes_and_wrong_refund_reason_fails():
    evaluator = OpenDriverRiderWalletCancellationRefundEvaluator
    assert evaluator.evaluate_state(_complete_reference_state()).status.value == "PASS"

    wrong = _complete_reference_state()
    wrong["refunds"][0]["reason"] = "Wrong reason"
    result = evaluator.evaluate_state(wrong)
    assert result.status.value == "FAIL"
    assert "exactly_two_current_session_fare_review_refunds" in result.metadata["failed_checks"]


def test_ios_action_parser_rejects_missing_code_and_accepts_python_block():
    from platforms.ios.agent.planners.reflection_pyautogui_planner import build_python_action

    missing, parsed, _, error = build_python_action(
        'Reflection: I should tap the visible destination field.'
    )
    assert missing is None and not parsed and error == "missing_python_code_block"

    action, parsed, _, error = build_python_action(
        'Reflection: tap the destination.\n```python\ndriver.tap([(220, 264)])\n```'
    )
    assert parsed and error is None
    assert action["type"] == "python_code"
