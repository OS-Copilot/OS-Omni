from evaluators.ios.opendriver_driver_requests_insurance_support_payout import (
    OpenDriverIOSDriverWorkflowEvaluator as Evaluator,
)


SEED_TIME = "2026-01-01T00:00:00Z"


def correct_logged_out_reference():
    return {
        "meta": {"seededAt": SEED_TIME},
        "sessions": [],
        "driverProfiles": [
            {
                "id": "driver-primary",
                "userId": "usr_driver_primary",
                "licenseNumber": "NY-DL-100492",
                "vehicleMake": "Tesla",
                "vehicleModel": "Model Y",
                "vehicleYear": 2023,
                "licensePlate": "8XJR214",
                "vehicleColor": "Pearl White",
                "verificationStatus": "approved",
                "driverStatus": "online",
                "documents": [
                    {
                        "type": "insurance",
                        "identifier": "INS-2026-4096",
                        "expiresAt": "2028-09-30",
                        "status": "submitted",
                    }
                ],
            }
        ],
        "payouts": [
            {
                "id": "payout-reference",
                "driverId": "usr_driver_primary",
                "amount": 135.0,
                "currencyCode": "USD",
                "status": "requested",
                "note": "Weekend transfer",
            }
        ],
        "supportTickets": [
            {
                "id": "ticket-reference",
                "userId": "usr_driver_primary",
                "category": "rider issue",
                "message": "Route support help.",
                "status": "open",
            }
        ],
        "rides": [
            {
                "id": "rejected-reference",
                "createdAt": "2026-01-01T00:01:00Z",
                "status": "searching",
                "rejectedDriverIds": ["usr_driver_primary"],
            },
            {
                "id": "accepted-reference",
                "createdAt": "2026-01-01T00:02:00Z",
                "acceptedAt": "2026-01-01T00:02:05Z",
                "cancelledAt": "2026-01-01T00:03:00Z",
                "driverId": "usr_driver_primary",
                "status": "cancelled",
                "timeline": [
                    {"status": "accepted", "at": "2026-01-01T00:02:05Z"},
                    {"status": "cancelled", "at": "2026-01-01T00:03:00Z"},
                ],
            },
        ],
    }


def evaluate(document):
    return Evaluator.evaluate_state(document, include_runtime_binding=False)


def test_correct_logged_out_state_passes_with_cancelled_accepted_trip():
    result = evaluate(correct_logged_out_reference())
    assert result.status.value == "PASS"
    assert result.metadata["failed_checks"] == []


def test_wrong_insurance_document_fails():
    reference = correct_logged_out_reference()
    reference["driverProfiles"][0]["documents"][0]["identifier"] = "INS-OTHER"
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "insurance_2028" in result.metadata["failed_checks"]


def test_wrong_payout_amount_or_note_fails():
    reference = correct_logged_out_reference()
    reference["payouts"][0]["amount"] = 136
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "weekend_transfer_135" in result.metadata["failed_checks"]


def test_wrong_support_text_fails():
    reference = correct_logged_out_reference()
    reference["supportTickets"][0]["message"] = "Route help"
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "route_support_help" in result.metadata["failed_checks"]


def test_missing_acceptance_history_fails():
    reference = correct_logged_out_reference()
    reference["rides"][1].pop("acceptedAt")
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "accepted_generated_trip" in result.metadata["failed_checks"]


def test_active_session_after_logout_fails():
    reference = correct_logged_out_reference()
    reference["sessions"] = [{"id": "active", "userId": "usr_driver_primary"}]
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "final_logout" in result.metadata["failed_checks"]


def test_seeded_state_does_not_pass():
    result = evaluate({"meta": {"seededAt": SEED_TIME}, "sessions": []})
    assert result.status.value == "FAIL"
    assert len(result.metadata["failed_checks"]) >= 5
