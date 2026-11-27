"""iOS OpenDriver 11-1 / 11-2: the Rear seat reply and the persisted ride schema.

scan rows IOS-016 (11-1 reply text), IOS-018 (11-1 rides) and IOS-019 (11-2 ride).

* The brief asks for "a reply with the text Rear seat".  The rider reply dialog
  pre-fills "Following up on this ticket." and the app sends ``message.trim()``,
  so both "Rear seat" (prefill replaced) and the prefill followed by "Rear seat"
  are faithful; the grader used to accept only the latter.
* The backend persists a requested ride as ``rideTier`` plus waypoint objects
  ``{id, cityId, address, latitude, longitude}`` and ``destinationAddress``
  (server.js rideInput / POST /rides), not the check-level ``tier`` and string
  waypoints.  An app-shaped ride must match; a wrong tier or stop must not.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


E111 = _load("opendriver_11_1_reply_schema", "evaluators/ios/opendriver_11-1.py")
E112 = _load("opendriver_11_2_reply_schema", "evaluators/ios/opendriver_11-2.py")


def _waypoint(address: str) -> dict:
    return {"id": "waypoint_1", "cityId": "palo_alto", "address": address,
            "latitude": 37.43, "longitude": -122.17}


def _app_ride(ride_id: str, destination: str, payment: str, stops: list[str], created: str) -> dict:
    """A cancelled Green ride exactly as the vendored backend stores it."""
    return {
        "id": ride_id, "riderId": "usr_rider_primary", "driverId": None,
        "pickupAddress": "Current location", "destinationAddress": destination,
        "waypoints": [_waypoint(stop) for stop in stops],
        "paymentMethod": payment, "rideTier": "green", "rideTierTitle": "Green",
        "status": "cancelled", "createdAt": created, "cancelledAt": created.replace(":00Z", ":30Z"),
    }


# ---------------------------------------------------------------------------
# 11-1
# ---------------------------------------------------------------------------

def _state_11_1(reply: str) -> dict:
    history = [
        {"id": target["ride_id"], "pickupAddress": target["pickup"],
         "destinationAddress": target["destination"], "status": "completed"}
        for target in E111.REFUND_TARGETS
    ]
    return {
        "meta": {"seededAt": "2026-06-10T11:37:59.309Z"},
        "users": [{"id": "usr_rider_primary", "email": "rider@example.com", "role": "rider"}],
        "sessions": [{"id": "session-current", "userId": "usr_rider_primary",
                      "createdAt": "2026-10-11T12:00:00Z"}],
        "rides": history + [
            _app_ride("ride_app_1", "Meta MPK 23, 300 Constitution Drive, Menlo Park, CA",
                      "pm_rider_paypal", ["Stanford University, Stanford, CA"], "2026-10-11T12:01:00Z"),
            _app_ride("ride_app_2", "Downtown Palo Alto, CA", "pm_rider_visa", [],
                      "2026-10-11T12:03:00Z"),
        ],
        "refunds": [
            {"id": f"refund-{index}", "rideId": target["ride_id"], "reason": "Fare review",
             "status": "requested", "createdAt": f"2026-10-11T12:0{4 + index}:00Z"}
            for index, target in enumerate(E111.REFUND_TARGETS, 1)
        ],
        "supportTickets": [{
            "id": "ticket-1", "userId": "usr_rider_primary", "message": "Blue umbrella",
            "status": "open", "createdAt": "2026-10-11T12:07:00Z",
            "replies": [{"id": "reply-1", "message": reply}],
        }],
    }


def _failed_11_1(state: dict) -> list[str]:
    result = E111.OpenDriverRiderWalletCancellationRefundEvaluator.evaluate_state(state)
    return [] if result.status.value == "PASS" else list(result.metadata["failed_checks"])


def test_11_1_reply_with_exactly_rear_seat_passes():
    # Old grader: exact equality with the prefill-concatenated string only.
    assert "Rear seat" != "Following up on this ticket.Rear seat"
    assert _failed_11_1(_state_11_1("Rear seat")) == []


def test_11_1_reply_appended_to_prefill_still_passes():
    assert _failed_11_1(_state_11_1("Following up on this ticket.Rear seat")) == []
    assert _failed_11_1(_state_11_1("Following up on this ticket. Rear seat")) == []


def test_11_1_wrong_or_missing_reply_text_fails():
    check = "one_current_open_blue_umbrella_ticket_with_rear_seat_reply"
    for reply in ("Following up on this ticket.", "Front seat", "Rear seat please",
                  "rear seat", "Note: Rear seat", ""):
        assert check in _failed_11_1(_state_11_1(reply)), reply


def test_11_1_app_shaped_green_rides_match_and_wrong_tier_or_stop_fails():
    assert _failed_11_1(_state_11_1("Rear seat")) == []

    wrong_tier = _state_11_1("Rear seat")
    wrong_tier["rides"][-2]["rideTier"] = "standard"
    assert "first_green_paypal_ride" in _failed_11_1(wrong_tier)

    wrong_stop = _state_11_1("Rear seat")
    wrong_stop["rides"][-2]["waypoints"] = [_waypoint("Downtown Palo Alto, CA")]
    assert "first_green_paypal_ride" in _failed_11_1(wrong_stop)

    no_stop = _state_11_1("Rear seat")
    no_stop["rides"][-2]["waypoints"] = []
    assert "first_green_paypal_ride" in _failed_11_1(no_stop)

    second_wrong_tier = _state_11_1("Rear seat")
    second_wrong_tier["rides"][-1]["rideTier"] = "xl"
    assert "second_green_visa_ride" in _failed_11_1(second_wrong_tier)


def test_11_1_raw_app_ride_did_not_match_the_check_schema_before_normalization():
    ride = _state_11_1("Rear seat")["rides"][-2]
    assert E111._record_matches(ride, E111.FIRST_RIDE) is False
    assert E111._record_matches(E111._normalize_ride(ride), E111.FIRST_RIDE) is True


# ---------------------------------------------------------------------------
# 11-2
# ---------------------------------------------------------------------------

def test_11_2_app_shaped_green_ride_matches_and_wrong_stop_fails():
    ride = _app_ride("ride_app", "Stanford University, Stanford, CA", "pm-new-card",
                     ["Downtown Palo Alto, CA"], "2026-10-11T12:31:00Z")
    assert E112._record_matches(ride, E112.RIDE) is False  # old matcher
    assert E112._record_matches(E112._normalize_ride(ride), E112.RIDE) is True

    wrong_tier = copy.deepcopy(ride)
    wrong_tier["rideTier"] = "standard"
    assert E112._record_matches(E112._normalize_ride(wrong_tier), E112.RIDE) is False

    wrong_stop = copy.deepcopy(ride)
    wrong_stop["waypoints"] = [_waypoint("Stanford Shopping Center, Palo Alto, CA")]
    assert E112._record_matches(E112._normalize_ride(wrong_stop), E112.RIDE) is False
