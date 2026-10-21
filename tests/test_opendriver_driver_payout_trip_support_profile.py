from evaluators.ios.opendriver_driver_payout_trip_support_profile import (
    OpenDriverDriverPayoutTripSupportProfileEvaluator as Evaluator,
)


SEED_TIME = "2026-01-01T00:00:00Z"


def correct_active_trip_reference():
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
                        "type": "license",
                        "identifier": "DL-2026-2048",
                        "expiresAt": "2028-06-30",
                        "status": "submitted",
                    }
                ],
            }
        ],
        "payouts": [
            {
                "id": "payout-ref",
                "driverId": "usr_driver_primary",
                "amount": 95.0,
                "currencyCode": "USD",
                "status": "requested",
                "note": "Moring payout",
            }
        ],
        "supportTickets": [
            {
                "id": "ticket-ref",
                "userId": "usr_driver_primary",
                "category": "rider issue",
                "message": "Pickup support help.",
                "status": "open",
            }
        ],
        "rides": [
            {
                "id": "rejected-ref",
                "createdAt": "2026-01-01T00:01:00Z",
                "status": "searching",
                "rejectedDriverIds": ["usr_driver_primary"],
            },
            {
                "id": "accepted-ref",
                "createdAt": "2026-01-01T00:02:00Z",
                "acceptedAt": "2026-01-01T00:02:05Z",
                "driverId": "usr_driver_primary",
                "status": "cancelled",
                "cancelledAt": "2026-01-01T00:03:00Z",
                "cancellationReason": "Session ended on logout",
            },
        ],
    }


def evaluate(document):
    return Evaluator.evaluate_state(document, include_runtime_binding=False)


def test_correct_logged_out_state_passes_with_online_driver_and_accepted_history():
    result = evaluate(correct_active_trip_reference())
    assert result.status.value == "PASS"
    assert result.metadata["failed_checks"] == []


def test_busy_is_not_accepted_as_final_status_after_logout():
    reference = correct_active_trip_reference()
    reference["driverProfiles"][0]["driverStatus"] = "busy"
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "driver_profile" in result.metadata["failed_checks"]


def test_wrong_payout_amount_fails():
    reference = correct_active_trip_reference()
    reference["payouts"][0]["amount"] = 96
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "morning_payout_95" in result.metadata["failed_checks"]


def test_wrong_support_text_fails():
    reference = correct_active_trip_reference()
    reference["supportTickets"][0]["message"] = "Pickup support"
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "pickup_support_help" in result.metadata["failed_checks"]


def test_missing_acceptance_timestamp_fails():
    reference = correct_active_trip_reference()
    reference["rides"][1].pop("acceptedAt")
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "accepted_generated_trip" in result.metadata["failed_checks"]


def test_rejecting_the_wrong_driver_fails():
    reference = correct_active_trip_reference()
    reference["rides"][0]["rejectedDriverIds"] = ["usr_driver_second"]
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "rejected_generated_request" in result.metadata["failed_checks"]


def test_accepting_before_rejecting_fails_request_order_check():
    reference = correct_active_trip_reference()
    reference["rides"][0]["createdAt"] = "2026-01-01T00:02:00Z"
    reference["rides"][1]["createdAt"] = "2026-01-01T00:01:00Z"
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "first_rejected_then_second_accepted" in result.metadata["failed_checks"]


def test_remaining_driver_session_fails():
    reference = correct_active_trip_reference()
    reference["sessions"] = [{"id": "active", "userId": "usr_driver_primary"}]
    result = evaluate(reference)
    assert result.status.value == "FAIL"
    assert "final_logout" in result.metadata["failed_checks"]


def test_seeded_state_does_not_pass():
    result = evaluate({"meta": {"seededAt": SEED_TIME}, "driverProfiles": [], "sessions": []})
    assert result.status.value == "FAIL"
    assert len(result.metadata["failed_checks"]) >= 5


def test_store_uses_configured_host_database_path(tmp_path, monkeypatch):
    from evaluators.cua_review.platforms.ios.opendriver_store import OpenDriverStore

    database = tmp_path / "opendriver-db.json"
    database.write_text('{"meta":{"schemaVersion":16},"users":[]}')
    monkeypatch.setenv("OSOMNI_OPENDRIVER_DB_PATH", str(database))
    store = OpenDriverStore.from_params({})
    assert store.resolve() == database
    assert store.read_state()["meta"]["schemaVersion"] == 16
