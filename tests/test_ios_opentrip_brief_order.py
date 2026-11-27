"""iOS OpenTrip 158915 / 284952 / 638214 / 234497: no order the brief does not state.

None of the four briefs orders its records ("Create a flight booking and a hotel
booking", "Create a hotel booking, a review submission, and a flight booking",
separate paragraphs for review / flight / hotel / reschedule). The evaluators
used to require the recorded order three ways: createdAt order, the final list
order (new hotel stored before new flight), and the committed WAL progression.
Now each target record must land exactly once, in its own commit, in any order;
duplicate, extra, corrected, or wrong records still fail.

These tests use synthetic states (the bundled app assets are not needed): the
baseline hash and booking fingerprints are pinned to the synthetic objects, the
same way tests/test_ios_opentrip_wal_checkpoint.py does.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from pathlib import Path

import evaluators.ios.opentrip_nr2269_sanya_seabreeze_booking_158915 as nr2269
import evaluators.ios.opentrip_review_flight_hotel_reschedule_234497 as reschedule
import evaluators.ios.opentrip_sanya_parkline_review_mj2158_638214 as parkline
import evaluators.ios.opentrip_sc2306_grand_axis_booking_284952 as sc2306

REPO = Path(__file__).resolve().parents[1]
WINDOW_START = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 8, 3, 11, 0, tzinfo=timezone.utc)
SEED_IDS = ("OT-SEED-FLIGHT-1", "OT-SEED-HOTEL-1", "OT-SEED-FLIGHT-2", "OT-SEED-HOTEL-2")
SESSION = {
    "loggedIn": True,
    "user": {"id": "account-benchmark", "name": "Lucas Lin", "phone": "13900002026"},
}


def _at(minutes: int) -> datetime:
    return WINDOW_START + timedelta(minutes=minutes)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _booking(summary, moment: datetime) -> dict:
    millis = int(moment.timestamp() * 1000)
    return {"id": f"OT{millis:013d}", "createdAt": _iso(moment), **copy.deepcopy(summary)}


def _failed(result) -> set[str]:
    return {check["name"] for check in result.metadata["failures"]}


def _check(result, name):
    return next(check for check in result.metadata["checks"] if check["name"] == name)


def _strip(booking):
    return {key: value for key, value in booking.items() if key not in {"id", "createdAt"}}


# ---------------------------------------------------------------------------
# 158915 and 284952: one flight and one hotel booking, either order
# ---------------------------------------------------------------------------

TWO_BOOKING = {
    "158915": (nr2269, nr2269.OpenTripNr2269SanyaSeabreezeBooking158915Evaluator),
    "284952": (sc2306, sc2306.OpenTripSc2306GrandAxisBooking284952Evaluator),
}


def _two_booking_base():
    return {"session": copy.deepcopy(SESSION), "bookings": [{"id": seed} for seed in SEED_IDS]}


@pytest.fixture
def pinned_two_booking(monkeypatch):
    base = _two_booking_base()
    for module, _cls in TWO_BOOKING.values():
        monkeypatch.setattr(module, "EXPECTED_BASE_STATE_SHA256", module._canonical_json_sha256(base))
        monkeypatch.setattr(module, "EXPECTED_FLIGHT_FINGERPRINT",
                            module._canonical_json_sha256(_strip(module.FLIGHT_EXPECTED_SUMMARY)))
        monkeypatch.setattr(module, "EXPECTED_HOTEL_FINGERPRINT",
                            module._canonical_json_sha256(_strip(module.HOTEL_EXPECTED_SUMMARY)))
    return base


def _two_booking_run(module, cls, base, first, *, truncated=False, extra=None, flight_note=None):
    """first: "flight" or "hotel" - which booking the run creates first."""
    flight_summary = dict(module.FLIGHT_EXPECTED_SUMMARY)
    if flight_note is not None:
        flight_summary["note"] = flight_note
    order = ["flight", "hotel"] if first == "flight" else ["hotel", "flight"]
    made = {}
    commits = []
    bookings = []
    for minutes, kind in zip((10, 20), order):
        summary = flight_summary if kind == "flight" else module.HOTEL_EXPECTED_SUMMARY
        made[kind] = _booking(summary, _at(minutes))
        bookings = [made[kind], *bookings]  # the app prepends each new booking
        commits.append({**copy.deepcopy(base), "bookings": [*copy.deepcopy(bookings), *base["bookings"]]})
    if extra is not None:
        bookings = [extra, *bookings]
        commits.append({**copy.deepcopy(base), "bookings": [*copy.deepcopy(bookings), *base["bookings"]]})
    if truncated:
        commits = commits[-1:]
    return cls._evaluate_state_and_history(
        copy.deepcopy(commits[-1]),
        base_state=base,
        commit_states=commits,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        database_evidence={"history_truncated_by_checkpoint": truncated},
    )


@pytest.mark.parametrize("task", sorted(TWO_BOOKING))
@pytest.mark.parametrize("first", ["flight", "hotel"])
@pytest.mark.parametrize("truncated", [False, True])
def test_two_bookings_pass_in_either_order(pinned_two_booking, task, first, truncated):
    module, cls = TWO_BOOKING[task]
    result = _two_booking_run(module, cls, pinned_two_booking, first, truncated=truncated)
    assert result.status.value == "PASS", [(c["name"], c["failure_reason"]) for c in result.metadata["failures"]]
    names = {check["name"] for check in result.metadata["checks"]}
    assert "durable_events_and_required_order" in names
    assert "dynamic_identifier_and_timestamp_order_exact" not in names
    assert "wal_transaction_order_exact" not in names


@pytest.mark.parametrize("task", sorted(TWO_BOOKING))
def test_two_bookings_duplicate_hotel_still_fails(pinned_two_booking, task):
    module, cls = TWO_BOOKING[task]
    duplicate = _booking(module.HOTEL_EXPECTED_SUMMARY, _at(30))
    result = _two_booking_run(module, cls, pinned_two_booking, "hotel", extra=duplicate)
    assert result.status.value == "FAIL"
    assert {"hotel_booking_exact", "target_cardinality_and_list_order_exact",
            "durable_events_and_required_order"} <= _failed(result)


@pytest.mark.parametrize("task", sorted(TWO_BOOKING))
def test_two_bookings_wrong_field_still_fails(pinned_two_booking, task):
    module, cls = TWO_BOOKING[task]
    result = _two_booking_run(module, cls, pinned_two_booking, "hotel", flight_note="wrong note")
    assert result.status.value == "FAIL"
    assert "flight_booking_exact" in _failed(result)


@pytest.mark.parametrize("task", sorted(TWO_BOOKING))
def test_two_bookings_in_one_commit_or_inconsistent_storage_fail(pinned_two_booking, task):
    module, cls = TWO_BOOKING[task]
    base = pinned_two_booking
    flight = _booking(module.FLIGHT_EXPECTED_SUMMARY, _at(10))
    hotel = _booking(module.HOTEL_EXPECTED_SUMMARY, _at(20))
    both = {**copy.deepcopy(base), "bookings": [hotel, flight, *base["bookings"]]}
    one_commit = cls._evaluate_state_and_history(
        copy.deepcopy(both), base_state=base, commit_states=[both],
        window_start=WINDOW_START, window_end=WINDOW_END,
    )
    assert _failed(one_commit) == {"durable_events_and_required_order"}

    # Stored oldest-first: not how the app prepends new bookings.
    misordered = {**copy.deepcopy(base), "bookings": [flight, hotel, *base["bookings"]]}
    storage = cls._evaluate_state_and_history(
        copy.deepcopy(misordered), base_state=base, commit_states=[misordered],
        window_start=WINDOW_START, window_end=WINDOW_END,
        database_evidence={"history_truncated_by_checkpoint": True},
    )
    assert _failed(storage) == {"target_cardinality_and_list_order_exact"}


def test_two_booking_yaml_binds_the_new_ruleset():
    for task, (module, _cls) in TWO_BOOKING.items():
        name = module.__name__.rsplit(".", 1)[1]
        doc = yaml.safe_load((REPO / "tasks/v1/ios" / f"{name}.yaml").read_text(encoding="utf-8"))
        assert doc["evaluation"]["params"]["expected_ruleset_sha256"] == module.RULESET_SHA256, task
        assert doc["metadata"]["evaluator_ruleset_sha256"] == module.RULESET_SHA256, task
        assert module.RULESET_SPEC["business_transitions"]["required_order"] == []


# ---------------------------------------------------------------------------
# 638214: Parkline hotel, Riverlight review, MJ2158 flight in any order
# ---------------------------------------------------------------------------

PARKLINE = parkline.OpenTripSanyaParklineReviewMj2158638214Evaluator


def _parkline_base():
    bookings = [{"id": seed} for seed in SEED_IDS]
    bookings[3] = {"id": "OT-SEED-HOTEL-2", "item": {"id": "h3001", "reviews": [{"text": "old"}], "reviewCount": 1}}
    return {"session": copy.deepcopy(SESSION), "bookings": bookings}


@pytest.fixture
def pinned_parkline(monkeypatch):
    base = _parkline_base()
    monkeypatch.setattr(parkline, "EXPECTED_BASE_STATE_SHA256", parkline._canonical_json_sha256(base))
    monkeypatch.setattr(parkline, "EXPECTED_HOTEL_FINGERPRINT",
                        parkline._canonical_json_sha256(_strip(parkline.HOTEL_EXPECTED_SUMMARY)))
    monkeypatch.setattr(parkline, "EXPECTED_FLIGHT_FINGERPRINT",
                        parkline._canonical_json_sha256(_strip(parkline.FLIGHT_EXPECTED_SUMMARY)))
    return base


def _with_review(state, text="Quiet river stay"):
    state = copy.deepcopy(state)
    review = {**parkline.REVIEW_EXPECTED, "date": "2026-08-03", "text": text}
    target = next(row for row in state["bookings"] if row["id"] == "OT-SEED-HOTEL-2")
    target["review"] = review
    target["item"]["reviews"] = [copy.deepcopy(review), *target["item"]["reviews"]]
    target["item"]["reviewCount"] += 1
    return state


def _parkline_run(base, order, *, review_text="Quiet river stay", extra_commit=None):
    state = copy.deepcopy(base)
    commits = []
    minutes = 10
    for action in order:
        if action == "review":
            state = _with_review(state, review_text)
        else:
            summary = parkline.HOTEL_EXPECTED_SUMMARY if action == "hotel" else parkline.FLIGHT_EXPECTED_SUMMARY
            state = {**state, "bookings": [_booking(summary, _at(minutes)), *state["bookings"]]}
            minutes += 10
        commits.append(copy.deepcopy(state))
    if extra_commit is not None:
        state = extra_commit(state)
        commits.append(copy.deepcopy(state))
    return PARKLINE._evaluate_state_and_history(
        copy.deepcopy(state), base_state=base, commit_states=commits,
        window_start=WINDOW_START, window_end=WINDOW_END,
    )


@pytest.mark.parametrize(
    "order",
    [
        ("hotel", "review", "flight"),  # recorded order
        ("flight", "hotel", "review"),
        ("review", "flight", "hotel"),
    ],
)
def test_parkline_any_order_passes(pinned_parkline, order):
    result = _parkline_run(pinned_parkline, order)
    assert result.status.value == "PASS", [(c["name"], c["failure_reason"]) for c in result.metadata["failures"]]


def test_parkline_duplicate_flight_or_wrong_review_still_fails(pinned_parkline):
    duplicate = _parkline_run(
        pinned_parkline, ("flight", "review", "hotel"),
        extra_commit=lambda state: {
            **state, "bookings": [_booking(parkline.FLIGHT_EXPECTED_SUMMARY, _at(40)), *state["bookings"]]
        },
    )
    assert {"flight_booking_exact", "durable_events_and_required_order"} <= _failed(duplicate)

    wrong = _parkline_run(pinned_parkline, ("flight", "review", "hotel"), review_text="Quiet stay")
    assert "hotel_review_exact" in _failed(wrong)


def test_parkline_review_date_follows_the_run_not_the_recording(pinned_parkline):
    # IOS-043: the app stamps review.date at submission; any date in the window passes.
    result = _parkline_run(pinned_parkline, ("review", "hotel", "flight"))
    assert result.status.value == "PASS"
    assert parkline.REVIEW_EXPECTED["date"] == "2026-08-03"
    late = PARKLINE._evaluate_review(
        _with_review(pinned_parkline), base_state=pinned_parkline, allowed_review_dates={"2026-11-04"},
    )
    assert late["pass"] is False and "outside the causal window" in late["failure_reason"]


# ---------------------------------------------------------------------------
# 234497: review, flight, hotel, reschedule in any order
# ---------------------------------------------------------------------------

RESCHEDULE = reschedule.OpenTripReviewFlightHotelReschedule234497Evaluator


def _reschedule_base():
    return {
        "session": copy.deepcopy(SESSION),
        "bookings": [
            {"id": "OT-SEED-FLIGHT-1"},
            {"id": "OT-SEED-HOTEL-1", "guests": 2},
            {"id": "OT-SEED-FLIGHT-2"},
            {"id": "OT-SEED-HOTEL-2", "item": {"reviews": []}},
        ],
    }


def _apply(state, action, moment, *, guests=1):
    state = copy.deepcopy(state)
    rows = state["bookings"]
    if action == "review":
        review = {**reschedule.REVIEW_EXPECTED, "date": "2026-08-03"}
        target = next(row for row in rows if row["id"] == "OT-SEED-HOTEL-2")
        target["review"] = review
        target["item"]["reviews"] = [copy.deepcopy(review)]
    elif action == "reschedule":
        target = next(row for row in rows if row["id"] == "OT-SEED-HOTEL-1")
        expected = reschedule.RESCHEDULE_EXPECTED
        target.update({key: copy.deepcopy(value) for key, value in expected.items() if key != "previous"})
        target["guests"] = guests
        target["rescheduledAt"] = _iso(moment)
        target["rescheduleHistory"] = [{"previous": copy.deepcopy(expected["previous"]), "at": _iso(moment)}]
    else:
        summary = reschedule.FLIGHT_EXPECTED if action == "flight" else reschedule.HOTEL_EXPECTED
        state["bookings"] = [_booking(summary, moment), *rows]
    return state


def _reschedule_run(order, *, extra=None, guests=1):
    base = _reschedule_base()
    state = base
    commits = []
    for index, action in enumerate(order, start=1):
        state = _apply(state, action, _at(10 * index), guests=guests)
        commits.append(copy.deepcopy(state))
    if extra is not None:
        state = _apply(state, extra, _at(60))
        commits.append(copy.deepcopy(state))
    return RESCHEDULE._evaluate_state_and_history(
        copy.deepcopy(state), base_state=base, commit_states=commits,
        window_start=WINDOW_START, window_end=WINDOW_END,
    )


@pytest.mark.parametrize(
    "order",
    [
        ("review", "flight", "hotel", "reschedule"),  # recorded order
        ("reschedule", "hotel", "flight", "review"),
        ("hotel", "review", "reschedule", "flight"),
    ],
)
def test_reschedule_task_any_order_passes(order):
    result = _reschedule_run(order)
    assert result.status.value == "PASS", [(c["name"], c["failure_reason"]) for c in result.metadata["failures"]]


def test_reschedule_task_duplicate_or_wrong_record_still_fails():
    duplicate = _reschedule_run(("hotel", "flight", "review", "reschedule"), extra="hotel")
    assert {"hotel_booking_exact", "target_cardinality_exact", "durable_events_and_required_order"} <= _failed(duplicate)

    wrong = _reschedule_run(("reschedule", "hotel", "flight", "review"), guests=2)
    assert {"hotel_reschedule_exact", "durable_events_and_required_order"} <= _failed(wrong)


def test_reschedule_task_yaml_and_parkline_yaml_bind_the_new_ruleset():
    for module in (reschedule, parkline):
        name = module.__name__.rsplit(".", 1)[1]
        doc = yaml.safe_load((REPO / "tasks/v1/ios" / f"{name}.yaml").read_text(encoding="utf-8"))
        assert doc["evaluation"]["params"]["expected_ruleset_sha256"] == module.RULESET_SHA256
        assert doc["metadata"]["evaluator_ruleset_sha256"] == module.RULESET_SHA256
        assert module.RULESET_SPEC["business_transitions"]["required_order"] == []


@pytest.mark.parametrize("module", [nr2269, sc2306, parkline, reschedule], ids=lambda m: m.__name__[-6:])
def test_single_record_transitions_any_order_but_once_each(module):
    grade = module._single_record_transitions
    early, late = _at(10), _at(20)
    assert grade([(0, 1), (1, 1)], history_truncated=False, allow_idle_commits=False,
                 record_times=(late, early))[0] == []
    assert grade([(1, 1)], history_truncated=True, allow_idle_commits=False)[0] == []
    # Two records in one commit, a regression, an idle commit, or a missing record fail.
    assert grade([(1, 1)], history_truncated=False, allow_idle_commits=False)[0]
    assert grade([(1, 0), (0, 1), (1, 1)], history_truncated=False, allow_idle_commits=False)[0]
    assert grade([(1, 0), (1, 0), (1, 1)], history_truncated=False, allow_idle_commits=False)[0]
    assert grade([(1, 0)], history_truncated=False, allow_idle_commits=False)[0]
    # The record committed second may not carry the earlier app timestamp.
    assert grade([(0, 1), (1, 1)], history_truncated=False, allow_idle_commits=False,
                 record_times=(early, late))[0] == [
        "a record first committed later carries an earlier app timestamp"
    ]
