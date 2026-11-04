"""macOS OpenBank + TextEdit tasks: the business-event order is diagnostic.

The English briefs of the June-home and reserve-plan tasks list the bill
payments and transfers but never the order they are created in (scan.CSV
MAC-014 / MAC-015).  The durable record, count, session, file and foreground
checks grade the deliverables; a correct final state reached in another order
must pass, while missing or duplicated records still fail.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from core.evaluation import EvalStatus
from evaluators.cua_review.evaluators.macos.openbank_june_home_textedit import (
    OpenBankJuneHomeTextEditEvaluator as SharedJuneHomeEvaluator,
)

ROOT = Path(__file__).resolve().parents[1]
TASKS = {
    "june_home": ROOT / "tasks/v1/macos/openbank_macos1_june_home_bills_transfer_textedit.yaml",
    "reserve_plan": ROOT / "tasks/v1/macos/openbank_macos1_reserve_plan_bills_transfers_textedit.yaml",
}


def _task(name: str) -> dict:
    return yaml.safe_load(TASKS[name].read_text(encoding="utf-8"))


def _evaluator(task: dict):
    module_name, class_name = task["evaluation"]["evaluator_id"].split(":")
    return getattr(importlib.import_module(module_name), class_name)()


class _Controller:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def run_python_script(self, code: str, timeout: int = 0) -> dict:
        return {"returncode": 0, "stdout": json.dumps(self.payload)}


def _final_state(params: dict, *, order: str) -> dict:
    session = params["session"]
    bills = [dict(item, id=f"bill-{index}") for index, item in enumerate(params["required_bill_payments"])]
    transfers = [dict(item, id=f"xfer-{index}") for index, item in enumerate(params["required_transfers"])]
    login = {"type": "session_login_success", "customerId": session["customer_id"]}
    bill_events = [
        {"type": "bill_payment_scheduled", **{k: v for k, v in item.items() if k != "id"}} for item in bills
    ]
    transfer_events = [
        {"type": "transfer_scheduled", **{k: v for k, v in item.items() if k != "id"}} for item in transfers
    ]
    if order == "brief":
        events = [login, *bill_events, *transfer_events]
    else:  # transfers first, bills in reverse: same final state, different order
        events = [login, *transfer_events[::-1], *bill_events[::-1]]
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
            "billPayments": bills,
            "transfers": transfers,
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


@pytest.mark.parametrize("name", sorted(TASKS))
@pytest.mark.parametrize("order", ["brief", "other"])
def test_correct_final_state_passes_in_any_creation_order(name: str, order: str) -> None:
    task = _task(name)
    params = task["evaluation"]["params"]
    result = _run(_evaluator(task), params, _final_state(params, order=order))

    assert result.status == EvalStatus.PASS, result.message
    check_ids = [check["check_id"] for check in result.metadata["checks"]]
    assert "events.ordered_business_sequence" not in check_ids
    (diagnostic,) = result.metadata["diagnostics"]
    assert diagnostic["diagnostic_id"] == "events.ordered_business_sequence"
    assert diagnostic["blocking"] is False
    assert diagnostic["passed"] is (order == "brief")


@pytest.mark.parametrize("name", sorted(TASKS))
def test_explicit_opt_in_keeps_the_old_ordered_gate(name: str) -> None:
    # The pre-fix behaviour: the same correct final state FAILed on order alone.
    task = _task(name)
    params = dict(task["evaluation"]["params"], require_event_sequence=True)
    result = _run(_evaluator(task), params, _final_state(params, order="other"))

    assert result.status == EvalStatus.FAIL
    failed = [check["check_id"] for check in result.metadata["checks"] if not check["passed"]]
    assert failed == ["events.ordered_business_sequence"]


@pytest.mark.parametrize("name", sorted(TASKS))
@pytest.mark.parametrize("defect", ["duplicate_bill", "missing_transfer", "wrong_amount", "signed_out"])
def test_record_defects_still_fail(name: str, defect: str) -> None:
    task = _task(name)
    params = task["evaluation"]["params"]
    payload = _final_state(params, order="other")
    api = payload["api"]
    if defect == "duplicate_bill":
        api["billPayments"].append(dict(api["billPayments"][0], id="bill-dup"))
    elif defect == "missing_transfer":
        api["transfers"].pop()
    elif defect == "wrong_amount":
        api["billPayments"][0]["amount"] = 1.0
    else:
        api["session"]["loggedIn"] = False
    result = _run(_evaluator(task), params, payload)

    assert result.status == EvalStatus.FAIL


def test_shared_june_home_base_matches_the_task_copy() -> None:
    task = _task("june_home")
    params = task["evaluation"]["params"]
    result = _run(SharedJuneHomeEvaluator(), params, _final_state(params, order="other"))

    assert result.status == EvalStatus.PASS, result.message
    assert result.metadata["diagnostics"][0]["blocking"] is False
