"""Windows OpenBank task01-04: only stated or logically necessary orders gate a run.

The briefs list the business actions without temporal language, except
task04 ("Submit four transfers in the following order").  A transfer needs its
recipient first.  Each business action still has to happen exactly once.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from evaluators.windows import (
    openbank_task01_551454 as task01,
    openbank_task02_056264 as task02,
    openbank_task03_702660 as task03,
    openbank_task04_140186 as task04,
)
from evaluators.windows.openbank_events import check_precedence

ROOT = Path(__file__).resolve().parents[1]


class Ledger:
    """A minimal /api/evaluation payload: business rows plus the session event log."""

    def __init__(self):
        self.state = {"events": [{"seq": 1, "type": "session_login_success"}], "recipients": [], "transfers": [],
                      "billPayments": [], "disputes": [], "alerts": [], "cardControls": [], "alertSettings": [],
                      "paperlessSettings": []}
        self.actions: dict[str, list] = {}

    def event(self, kind, **values):
        row = {"seq": len(self.state["events"]) + 1, "type": kind, **values}
        self.state["events"].append(row)
        return row

    def action(self, name, *rows):
        self.actions[name] = list(rows)

    def replay(self, order):
        """Append each named action's events in ``order``, renumbering seq."""
        events = [self.state["events"][0]]
        for name in order:
            for row in self.actions[name]:
                events.append({**row, "seq": len(events) + 1})
        state = deepcopy(self.state)
        state["events"] = events
        return state


def recipient(ledger, name, want, rid):
    ledger.state["recipients"].append({**want, "id": rid, "type": "person"})
    ledger.action(name, {"type": "transfer_recipient_added", "recipientId": rid, "recipientName": want["name"],
                         "bank": want["bank"], "mask": want["mask"]})


def transfer(ledger, name, want, rid, tid):
    ledger.state["transfers"].append({**want, "id": tid, "recipientId": rid})
    ledger.action(name, {"type": "transfer_scheduled", "transferId": tid, "recipientId": rid,
                         "fromAccountId": want["fromAccountId"], "amount": want["amount"],
                         "scheduledDate": want["scheduledDate"], "memo": want["memo"]})


def bill(ledger, name, want, pid):
    ledger.state["billPayments"].append({**want, "id": pid, "status": "Scheduled"})
    ledger.action(name, {"type": "bill_payment_scheduled", "paymentId": pid, "billerId": want["billerId"],
                         "fromAccountId": want["fromAccountId"], "amount": want["amount"],
                         "scheduledDate": want["scheduledDate"]})


def dispute(ledger, name, want, index):
    row = {"id": f"disp-{index}", "transactionId": f"txn-{index}", "merchant": want["merchant"],
           "reason": want["reason"], "details": want["details"], "contactedMerchant": True, "status": "Submitted"}
    ledger.state["disputes"].append(row)
    ledger.action(name,
                  {"type": "transactions_viewed", "q": want["query"], "total": 3},
                  {"type": "transaction_details_viewed", "transactionId": row["transactionId"]},
                  {"type": "transaction_dispute_submitted", "disputeId": row["id"],
                   "transactionId": row["transactionId"], "reason": want["reason"]})


def task01_ledger():
    spec, ledger = task01.RULESET_SPEC, Ledger()
    for i, (key, want) in enumerate(zip(["elliot", "nora", "priya"], spec["recipients"])):
        recipient(ledger, f"recipient_{key}", want, f"rec-{key}")
        transfer(ledger, f"transfer_{key}", spec["transfers"][i], f"rec-{key}", f"transfer-{key}")
    for key, want in zip(["northstar", "rewards"], spec["bill_payments"]):
        bill(ledger, f"bill_{key}", want, f"pay-{key}")
    for i, (key, want) in enumerate(zip(["ace", "caffe"], spec["disputes"])):
        dispute(ledger, f"dispute_{key}", want, i)
    return ledger


def task01_result(order):
    return task01.OpenBankTask01551454Evaluator.evaluate_state(task01_ledger().replay(order))


DEMO01 = list(task01.STEP_GROUPS)


def failed(result):
    return result.metadata["failed_checks"]


def test_task01_demonstrated_order_passes():
    assert task01_result(DEMO01).status.value == "PASS"


def test_task01_disputes_first_and_interleaved_transfers_pass():
    # The brief enumerates the four kinds of work; it states no order between them.
    order = ["dispute_caffe", "dispute_ace", "bill_rewards", "recipient_priya", "transfer_priya",
             "recipient_elliot", "bill_northstar", "transfer_elliot", "recipient_nora", "transfer_nora"]
    result = task01_result(order)
    assert result.status.value == "PASS", failed(result)


def test_task01_transfer_before_its_recipient_fails():
    order = [n for n in DEMO01 if n != "recipient_nora"]
    order.insert(order.index("transfer_nora") + 1, "recipient_nora")
    assert failed(task01_result(order)) == ["openbank.task01.business_order"]


def test_task01_duplicate_transfer_fails():
    ledger = task01_ledger()
    ledger.actions["transfer_nora"] *= 2
    result = task01.OpenBankTask01551454Evaluator.evaluate_state(ledger.replay(DEMO01))
    assert "openbank.task01.transfer_nora" in failed(result)


def test_task01_wrong_transfer_record_fails():
    ledger = task01_ledger()
    ledger.state["transfers"][1]["amount"] = 126.41
    result = task01.OpenBankTask01551454Evaluator.evaluate_state(ledger.replay(DEMO01))
    assert "openbank.task01.transfer_nora" in failed(result)


def task02_ledger():
    spec, ledger = task02.RULESET_SPEC, Ledger()
    ledger.state["alertSettings"].append(dict(spec["alert_settings"][0]))
    for key, want in zip(["alert_signin", "alert_bill"], spec["alerts"]):
        ledger.state["alerts"].append(dict(want))
        ledger.action(key, {"type": "alert_marked_read", "alertId": want["id"]})
    for key, want in zip(["card_debit", "card_credit"], spec["cards"]):
        ledger.state["cardControls"].append(dict(want))
        ledger.action(key, {"type": "card_locked", "cardId": want["id"], "accountId": want["accountId"], "status": "Locked"})
    for key, want in zip(["setting_large", "setting_payment", "setting_deposit"], spec["alert_settings"][1:]):
        ledger.state["alertSettings"].append(dict(want))
        ledger.action(key, {"type": "alert_setting_updated", "settingId": want["id"],
                            **{k: want[k] for k in ("accountId", "threshold", "enabled", "email", "sms", "push") if k in want}})
    for key, want in zip(["paper_checking", "paper_savings", "paper_credit"], spec["paperless"]):
        ledger.state["paperlessSettings"].append(dict(want))
        ledger.action(key, {"type": "paperless_setting_updated", "accountId": want["accountId"], "delivery": want["delivery"]})
    for key, want in zip(["download_savings", "download_credit", "download_checking"], spec["statement_downloads"]):
        ledger.action(key, {"type": "statement_downloaded", "accountId": want["accountId"], "month": want["month"],
                            "filename": f"{want['accountId']}_{want['month']}.csv"})
    for key, want in zip(["recipient_mateo", "recipient_grace", "recipient_owen", "recipient_sofia"], spec["recipients"]):
        recipient(ledger, key, want, f"rec-{key}")
    transfer(ledger, "transfer_mateo", spec["transfer"], "rec-recipient_mateo", "transfer-mateo")
    bill(ledger, "bill_rewards", spec["bill_payment"], "pay-rewards")
    return ledger


DEMO02 = [name for name in task02.STEP_GROUPS if name != "setting_low_final"]


def test_task02_recipients_and_payments_first_pass():
    order = ["recipient_sofia", "recipient_mateo", "transfer_mateo", "bill_rewards", "download_checking",
             "paper_credit", "card_credit", "alert_bill", "setting_deposit", "recipient_grace", "download_savings",
             "paper_savings", "setting_large", "alert_signin", "card_debit", "recipient_owen", "download_credit",
             "paper_checking", "setting_payment"]
    assert sorted(order) == sorted(DEMO02)
    result = task02.OpenBankTask02056264Evaluator.evaluate_state(task02_ledger().replay(order))
    assert result.status.value == "PASS", failed(result)


def test_task02_card_locked_twice_still_fails():
    ledger = task02_ledger()
    ledger.actions["card_credit"] *= 2
    result = task02.OpenBankTask02056264Evaluator.evaluate_state(ledger.replay(DEMO02))
    assert failed(result) == ["openbank.task02.card.2"]


def task03_ledger():
    spec, ledger = task03.RULESET_SPEC, Ledger()
    for i, (key, want) in enumerate(zip(["dispute_elm", "dispute_rei", "dispute_parking", "dispute_cloudbox"], spec["disputes"])):
        dispute(ledger, key, want, i)
    for key, want in zip(["bill_northstar_65", "bill_rewards_350", "bill_northstar_7"], spec["bill_payments"]):
        bill(ledger, key, want, f"pay-{key}")
    recipient(ledger, "recipient_caleb", spec["recipient"], "rec-caleb")
    transfer(ledger, "transfer_caleb", spec["transfer"], "rec-caleb", "transfer-caleb")
    return ledger


def test_task03_transfer_first_then_disputes_pass():
    order = ["recipient_caleb", "transfer_caleb", "bill_northstar_7", "dispute_cloudbox", "bill_rewards_350",
             "dispute_rei", "dispute_elm", "bill_northstar_65", "dispute_parking"]
    result = task03.OpenBankTask03702660Evaluator.evaluate_state(task03_ledger().replay(order))
    assert result.status.value == "PASS", failed(result)


def test_task03_duplicate_bill_payment_fails():
    ledger = task03_ledger()
    ledger.actions["bill_rewards_350"] *= 2
    result = task03.OpenBankTask03702660Evaluator.evaluate_state(ledger.replay(list(task03.STEP_GROUPS)))
    assert failed(result) == ["openbank.task03.bill_rewards_350"]


def task04_ledger():
    spec, ledger = task04.RULESET_SPEC, Ledger()
    for key, want in zip(["download_savings", "download_credit", "download_checking"], spec["statement_downloads"]):
        ledger.action(key, {"type": "statement_downloaded", "accountId": want["accountId"], "month": want["month"],
                            "filename": f"{want['accountId']}_{want['month']}.csv"})
    ledger.state["paperlessSettings"].append(dict(spec["paperless"]))
    ledger.action("paperless_savings", {"type": "paperless_setting_updated", "accountId": "savings-9140", "delivery": "Paperless"})
    ids = {}
    for key, want in zip(["recipient_amina", "recipient_theo"], spec["recipients"]):
        ids[want["name"]] = f"rec-{key}"
        recipient(ledger, key, want, ids[want["name"]])
    for key, want in zip(["transfer_amina", "transfer_theo", "transfer_avery", "transfer_maya"], spec["transfers"]):
        rid = ids.get(want["recipientName"], want["recipientId"])
        transfer(ledger, key, {**want, "recipientId": rid}, rid, f"transfer-{key}")
    for key, want in zip(["alert_signin", "alert_bill"], spec["alerts"]):
        ledger.state["alerts"].append(dict(want))
        ledger.action(key, {"type": "alert_marked_read", "alertId": want["id"]})
    ledger.state["cardControls"].append(dict(spec["card"]))
    ledger.action("card_credit", {"type": "card_locked", "cardId": spec["card"]["id"], "accountId": spec["card"]["accountId"], "status": "Locked"})
    for key, want in zip(["setting_low", "setting_large", "setting_payment", "setting_direct"], spec["alert_settings"]):
        ledger.state["alertSettings"].append(dict(want))
        ledger.action(key, {"type": "alert_setting_updated", "settingId": want["id"],
                            **{k: want[k] for k in ("accountId", "threshold", "enabled", "email", "sms", "push") if k in want}})
    return ledger


def task04_result(order, ledger=None):
    return task04.OpenBankTask04140186Evaluator.evaluate_state((ledger or task04_ledger()).replay(order))


DEMO04 = list(task04.STEP_GROUPS)


def test_task04_statements_and_security_in_any_order_pass():
    # WIN-026: the brief states no order for the statement downloads.
    order = ["setting_direct", "card_credit", "download_checking", "recipient_theo", "alert_bill",
             "recipient_amina", "transfer_amina", "download_savings", "transfer_theo", "setting_low",
             "paperless_savings", "transfer_avery", "alert_signin", "download_credit", "transfer_maya",
             "setting_payment", "setting_large"]
    assert sorted(order) == sorted(DEMO04)
    result = task04_result(order)
    assert result.status.value == "PASS", failed(result)


@pytest.mark.parametrize("swap", [("transfer_amina", "transfer_theo"), ("transfer_avery", "transfer_maya")])
def test_task04_stated_transfer_order_violated_fails(swap):
    order = list(DEMO04)
    a, b = order.index(swap[0]), order.index(swap[1])
    order[a], order[b] = order[b], order[a]
    assert failed(task04_result(order)) == ["openbank.task04.business_order"]


def test_task04_duplicate_transfer_fails():
    ledger = task04_ledger()
    ledger.actions["transfer_maya"] *= 2
    assert "openbank.task04.transfer.4" in failed(task04_result(DEMO04, ledger))


def test_precedence_needs_both_events():
    ok, rows = check_precedence({"a": {"seq": 2}, "b": None}, [("a", "b")])
    assert not ok and rows[0]["after_seq"] is None
    assert check_precedence({}, [])[0]


@pytest.mark.parametrize("module", [task01, task02, task03, task04])
def test_ruleset_digest_and_task_pins_agree(module):
    digest = hashlib.sha256(json.dumps(module.RULESET_SPEC, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest()
    assert module.RULESET_SHA256 == digest
    stem = module.__name__.rsplit(".", 1)[1]
    for folder in ("tasks/v1/windows", "tasks/windows"):
        task = yaml.safe_load((ROOT / folder / f"{stem}.yaml").read_text(encoding="utf8"))
        assert task["evaluation"]["params"]["expected_ruleset_sha256"] == digest
