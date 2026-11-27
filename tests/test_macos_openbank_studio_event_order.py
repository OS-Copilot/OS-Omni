"""macOS OpenBank studio recipients task: Sofia/Ethan order is a record label.

The brief says "The first recipient record must be named Sofia Reed ... The
second recipient record must be named Ethan Cole" and "A transfer ... A second
transfer ...".  Those are labels, not chronology, so creating Ethan's recipient
or transfer first must pass; the old evaluator failed it on
``events.ordered_business_sequence``.  Sign-in before the transfers stays
blocking, and duplicate or wrong records still fail on the durable state.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from core.evaluation import EvalStatus
from evaluators.cua_review.evaluators.macos.openbank_studio_recipients_textedit import (
    OpenBankStudioRecipientsTextEditEvaluator as SharedStudioEvaluator,
)

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tasks/v1/macos/openbank_macos1_studio_recipients_transfers_textedit.yaml"
SEEDED_RECIPIENTS = [
    {"id": "rec-maya", "name": "Maya Patel"},
    {"id": "rec-avery", "name": "Avery Brooks"},
    {"id": "rec-rainy-day", "name": "Rainy Day Savings"},
]


def _task() -> dict:
    return yaml.safe_load(TASK.read_text(encoding="utf-8"))


def _evaluator(task: dict):
    module_name, class_name = task["evaluation"]["evaluator_id"].split(":")
    return getattr(importlib.import_module(module_name), class_name)()


class _Controller:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def run_python_script(self, code: str, timeout: int = 0) -> dict:
        return {"returncode": 0, "stdout": json.dumps(self.payload)}


def _final_state(params: dict, *, ethan_first: bool) -> dict:
    session = params["session"]
    new_recipients = [
        dict(item, id=f"rec-new-{index}") for index, item in enumerate(params["required_recipients"])
    ]
    by_name = {item["name"]: item["id"] for item in new_recipients}
    transfers = [
        dict(item, id=f"transfer-{index}", recipientId=by_name[item["recipientName"]])
        for index, item in enumerate(params["required_transfers"])
    ]
    login = {"type": "session_login_success", "customerId": session["customer_id"]}
    recipient_events = [
        {"type": "transfer_recipient_added", "recipientId": item["id"], "recipientName": item["name"]}
        for item in new_recipients
    ]
    transfer_events = [
        {
            "type": "transfer_scheduled",
            "transferId": item["id"],
            "fromAccountId": item["fromAccountId"],
            "recipientId": item["recipientId"],
            "amount": item["amount"],
            "scheduledDate": item["scheduledDate"],
            "memo": item["memo"],
        }
        for item in transfers
    ]
    if ethan_first:
        recipient_events.reverse()
        transfer_events.reverse()
    events = [login, recipient_events[0], transfer_events[0], recipient_events[1], transfer_events[1]]
    return {
        "api": {
            "session": {
                "loggedIn": True,
                "user": {
                    "id": session["customer_id"],
                    "displayName": session["display_name"],
                    "email": session["email"],
                },
            },
            "recipients": [*new_recipients[::-1], *SEEDED_RECIPIENTS],
            "transfers": transfers[::-1],
            "events": events,
        },
        "file": {
            "path": params["guest_text_file"],
            "exists": True,
            "is_rtf": False,
            "lines": list(params["expected_text_lines"]),
        },
    }


def _run(evaluator, params: dict, payload: dict):
    return evaluator.evaluate(
        {
            "params": params,
            "controller": _Controller(payload),
            "final_observation": SimpleNamespace(foreground_app="TextEdit", foreground_window=""),
        }
    )


def _failed(result) -> list[str]:
    return [check["check_id"] for check in result.metadata["checks"] if not check["passed"]]


@pytest.mark.parametrize("ethan_first", [False, True])
@pytest.mark.parametrize("shared", [False, True])
def test_either_recipient_order_passes(ethan_first: bool, shared: bool) -> None:
    task = _task()
    params = task["evaluation"]["params"]
    evaluator = SharedStudioEvaluator() if shared else _evaluator(task)
    result = _run(evaluator, params, _final_state(params, ethan_first=ethan_first))

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]
    check_ids = [check["check_id"] for check in result.metadata["checks"]]
    assert "events.ordered_business_sequence" not in check_ids
    assert "events.login_before_business_actions" in check_ids
    (diagnostic,) = result.metadata["diagnostics"]
    assert diagnostic["diagnostic_id"] == "events.ordered_business_sequence"
    assert diagnostic["blocking"] is False
    assert diagnostic["passed"] is (not ethan_first)


def test_opt_in_restores_the_old_sofia_then_ethan_gate() -> None:
    # Pre-fix behaviour: the same correct final state FAILed on order alone.
    task = _task()
    params = dict(task["evaluation"]["params"], require_event_sequence=True)
    result = _run(_evaluator(task), params, _final_state(params, ethan_first=True))

    assert result.status == EvalStatus.FAIL
    assert _failed(result) == ["events.ordered_business_sequence"]


def test_transfers_recorded_before_sign_in_fail() -> None:
    task = _task()
    params = task["evaluation"]["params"]
    payload = _final_state(params, ethan_first=True)
    events = payload["api"]["events"]
    payload["api"]["events"] = [*events[1:], events[0]]
    result = _run(_evaluator(task), params, payload)

    assert result.status == EvalStatus.FAIL
    assert _failed(result) == ["events.login_before_business_actions"]


@pytest.mark.parametrize(
    "defect", ["duplicate_transfer", "duplicate_recipient", "transfer_to_wrong_recipient", "wrong_memo"]
)
def test_duplicate_or_wrong_records_still_fail(defect: str) -> None:
    task = _task()
    params = task["evaluation"]["params"]
    payload = _final_state(params, ethan_first=True)
    api = payload["api"]
    if defect == "duplicate_transfer":
        api["transfers"].append(dict(api["transfers"][0], id="transfer-dup"))
    elif defect == "duplicate_recipient":
        api["recipients"].insert(0, dict(api["recipients"][0], id="rec-dup"))
    elif defect == "transfer_to_wrong_recipient":
        for transfer in api["transfers"]:
            if transfer["recipientName"] == "Sofia Reed":
                transfer["recipientName"] = "Ethan Cole"
    else:
        api["transfers"][0]["memo"] = "Studio share"
    result = _run(_evaluator(task), params, payload)

    assert result.status == EvalStatus.FAIL
    assert "events.login_before_business_actions" not in _failed(result)
