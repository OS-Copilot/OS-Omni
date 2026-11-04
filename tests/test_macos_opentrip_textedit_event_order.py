"""macOS OpenTrip + TextEdit tasks: grade the briefed bookings, not the click ledger.

scan.CSV MAC-046/049/051/053: ``opentrip_final_state`` used to require the app's
ordered benchmark event ledger (login, search/view/book x3 with exact search
parameters), which the English briefs never impose.  The ledger is now a
diagnostic unless a task opts in with ``require_benchmark_event_sequence``.

The family-flights return booking also required a traveler (Maya Chen) and a
cabin the brief never names; the checkout form defaults to the first saved
traveler (Lucas Lin), so a faithful run failed on it.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

from core.evaluation import EvalStatus
from evaluators.cua_review.evaluators.macos.opentrip_textedit import OpenTripTextEditEvaluator

ROOT = Path(__file__).resolve().parents[1]
TASKS = sorted((ROOT / "tasks/v1/macos").glob("opentrip_macos1_*_textedit.yaml"))
FAMILY_FLIGHTS = ROOT / "tasks/v1/macos/opentrip_macos1_sanya_family_flights_textedit.yaml"
LUCAS = {"id": "traveler-lucas", "name": "Lucas Lin", "documentType": "ID Card"}


def _task(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _evaluator(task: dict):
    module_name, class_name = task["evaluation"]["evaluator_id"].split(":")
    return getattr(importlib.import_module(module_name), class_name)()


def _record(spec: dict, index: int) -> dict:
    """A persisted /api/bookings record that satisfies ``spec``."""
    helper = OpenTripTextEditEvaluator()
    record: dict = {"id": f"OT-{index}", "traveler": dict(LUCAS), "cabin": "economy"}
    for key, value in spec.items():
        if key in {helper.LABEL_FIELD, helper.BAGGAGE_FIELD}:
            continue
        *parents, leaf = helper._booking_path(key)
        node = record
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    token = spec.get(helper.BAGGAGE_FIELD)
    if token:
        record["baggageAddOn"] = {"id": f"bag-{token}", "label": f"Add {token} checked bag"}
    return record


def _collected(params: dict, *, events: list | None = None) -> dict:
    return {
        "api_session": {
            "session": {
                "loggedIn": True,
                "user": {"name": params["session"]["name"], "phone": params["session"]["phone"]},
            }
        },
        "api_bookings": {
            "bookings": [_record(spec, index) for index, spec in enumerate(params["required_bookings"])]
        },
        "api_benchmark": {"events": list(events or [])},
        "file": "\n".join(params["expected_text_lines"]) + "\n",
    }


def _run(task: dict, params: dict, collected: dict):
    return _evaluator(task).evaluate(
        {
            "params": params,
            "collected_state": collected,
            "final_observation": {"foreground_app": "TextEdit", "foreground_window": "Sanya"},
        }
    )


def test_all_four_macos_opentrip_tasks_are_covered() -> None:
    assert len(TASKS) == 4
    for path in TASKS:
        params = _task(path)["evaluation"]["params"]
        assert params["benchmark_event_sequence"], path.name
        assert not params.get("require_benchmark_event_sequence"), path.name


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.stem)
@pytest.mark.parametrize("ledger", ["empty", "reversed"])
def test_briefed_final_state_passes_without_the_scripted_ledger(path: Path, ledger: str) -> None:
    task = _task(path)
    params = task["evaluation"]["params"]
    events = [] if ledger == "empty" else [
        {"type": entry["type"], **entry.get("match", {})} for entry in params["benchmark_event_sequence"][::-1]
    ]
    result = _run(task, params, _collected(params, events=events))

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]
    diagnostic = result.metadata["observed"]["opentrip"]["metadata"]["benchmark_sequence_diagnostic"]
    assert diagnostic == {"required": False, "matched": False, "checks": diagnostic["checks"]}


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.stem)
def test_opt_in_restores_the_old_ledger_gate(path: Path) -> None:
    # The pre-fix behaviour: the same correct bookings FAILed on the ledger alone.
    task = _task(path)
    params = dict(task["evaluation"]["params"], require_benchmark_event_sequence=True)
    result = _run(task, params, _collected(params))

    assert result.status == EvalStatus.FAIL
    assert result.metadata["failure_reasons"] == [
        "OpenTrip checks failed: ordered OpenTrip benchmark event sequence does not match"
    ]


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.stem)
@pytest.mark.parametrize("defect", ["missing_booking", "wrong_phone", "no_bag", "signed_out", "wrong_file"])
def test_deliverable_defects_still_fail(path: Path, defect: str) -> None:
    task = _task(path)
    params = task["evaluation"]["params"]
    collected = _collected(params)
    bookings = collected["api_bookings"]["bookings"]
    if defect == "missing_booking":
        bookings.pop()
    elif defect == "wrong_phone":
        bookings[0]["contactPhone"] = "13900000000"
    elif defect == "no_bag":
        for booking in bookings:
            booking.pop("baggageAddOn", None)
    elif defect == "signed_out":
        collected["api_session"]["session"]["loggedIn"] = False
    else:
        collected["file"] = "DATES=WRONG\n"
    result = _run(task, params, collected)

    assert result.status == EvalStatus.FAIL


def test_family_flights_return_is_not_graded_on_an_unstated_traveler_or_cabin() -> None:
    task = _task(FAMILY_FLIGHTS)
    params = task["evaluation"]["params"]
    assert "traveler" not in task["instruction"].split("The return flight reservation")[1].split("A new plain")[0]
    (return_spec,) = [spec for spec in params["required_bookings"] if spec.get("flight_from") == "SYX"]
    assert not {"cabin", "traveler_id", "traveler_name", "traveler_document_type"} & set(return_spec)

    collected = _collected(params)
    (record,) = [item for item in collected["api_bookings"]["bookings"] if item["item"].get("from") == "SYX"]
    assert record["traveler"] == LUCAS  # the checkout form's default traveler
    record["cabin"] = "business"
    assert _run(task, params, collected).status == EvalStatus.PASS

    # The old spec (Maya Chen on the return) failed this faithful run.
    old_params = yaml.safe_load(yaml.safe_dump(params))
    for spec in old_params["required_bookings"]:
        if spec.get("flight_from") == "SYX":
            spec.update(
                cabin="economy",
                traveler_id="traveler-maya",
                traveler_name="Maya Chen",
                traveler_document_type="Passport",
            )
    assert _run(task, old_params, collected).status == EvalStatus.FAIL

    # The outbound traveler the brief does state is still required.
    (outbound,) = [item for item in collected["api_bookings"]["bookings"] if item["item"].get("from") == "SHA"]
    outbound["traveler"] = dict(LUCAS)
    assert _run(task, params, collected).status == EvalStatus.FAIL
