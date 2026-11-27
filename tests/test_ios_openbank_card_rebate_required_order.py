"""iOS OpenBank 183183: grade the business events the brief asks for, not the demo order.

The brief enumerates the dispute, two recipients, two transfers, the paperless
setting and the Security changes with no temporal language, and never asks for
an Activity search. The evaluator keeps every business event exactly once (an
identical alert-setting re-save is idempotent), fails unexpected business
events, and only orders each recipient before its transfer.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from evaluators.ios import openbank_card_rebate_dispute_183183 as module
from tests.test_ios_openbank_card_rebate_boundary import (
    ACE_DETAILS,
    ACTIVITY_VIEW,
    _completed_reference_state,
)

EVAL = module.OpenBankCardRebateDispute183183Evaluator
BOUNDARY = {"mode": "automatic", "min_seq_exclusive": 0}
REPO = Path(__file__).resolve().parents[1]

# Security first, then Statements, recipients/transfers interleaved, and the
# dispute last; the Ace Hardware entry is opened from Activity without a search.
BRIEF_FAITHFUL_OTHER_ORDER = [
    "payment_due_text",
    "upcoming_bill_read",
    "low_balance_text",
    "rainy_paperless",
    "mira_recipient",
    "mira_transfer",
    "dana_recipient",
    "dana_transfer",
    ACTIVITY_VIEW,
    ACE_DETAILS,
    ACE_DETAILS,
    "ace_dispute",
    ACE_DETAILS,
]


def _failed(result):
    return set(result.metadata["failed_checks"])


def _evaluate(items):
    return EVAL.evaluate_state(_completed_reference_state(items), boundary=BOUNDARY)


def test_brief_faithful_run_in_another_order_without_search_passes():
    result = _evaluate(BRIEF_FAITHFUL_OTHER_ORDER)
    assert result.status.value == "PASS", result.metadata["failed_checks"]


def test_identical_alert_setting_resave_is_not_a_duplicate():
    result = _evaluate(BRIEF_FAITHFUL_OTHER_ORDER + ["low_balance_text"])
    assert result.status.value == "PASS", result.metadata["failed_checks"]


def test_transfer_before_its_recipient_fails():
    items = list(BRIEF_FAITHFUL_OTHER_ORDER)
    items.remove("dana_transfer")
    items.insert(0, "dana_transfer")
    result = _evaluate(items)
    assert _failed(result) == {"durable_events_and_required_order"}
    check = next(
        c for c in result.metadata["checks"] if c["name"] == "durable_events_and_required_order"
    )
    assert check["actual"]["order_violations"] == [["dana_recipient", "dana_transfer"]]


def test_duplicate_transfer_or_dispute_event_fails():
    duplicate_transfer = _evaluate(BRIEF_FAITHFUL_OTHER_ORDER + ["mira_transfer"])
    assert "mira_transfer_exact" in _failed(duplicate_transfer)
    duplicate_dispute = _evaluate(BRIEF_FAITHFUL_OTHER_ORDER + ["ace_dispute"])
    assert "ace_dispute_exact" in _failed(duplicate_dispute)


def test_unexpected_business_event_fails():
    other_setting = {
        "type": "alert_setting_updated", "settingId": "pref-large-purchase",
        "accountId": "credit-7712", "enabled": True, "email": True, "sms": True,
        "push": True, "threshold": 100,
    }
    result = _evaluate(BRIEF_FAITHFUL_OTHER_ORDER + [other_setting])
    assert _failed(result) == {"durable_events_and_required_order"}


def test_missing_business_event_or_wrong_record_fails():
    missing = _evaluate([item for item in BRIEF_FAITHFUL_OTHER_ORDER if item != "upcoming_bill_read"])
    assert "upcoming_bill_read_exact" in _failed(missing)

    state = _completed_reference_state(BRIEF_FAITHFUL_OTHER_ORDER)
    state["disputes"][0]["details"] = "Return"
    wrong = EVAL.evaluate_state(state, boundary=BOUNDARY)
    assert "ace_dispute_exact" in _failed(wrong)


def test_task_binds_the_updated_ruleset():
    doc = yaml.safe_load(
        (REPO / "tasks/v1/ios/openbank_card_rebate_dispute_183183.yaml").read_text(encoding="utf-8")
    )
    assert doc["evaluation"]["params"]["expected_ruleset_sha256"] == module.RULESET_SHA256
    assert doc["metadata"]["verifier_rules"]["ruleset_sha256"] == module.RULESET_SHA256
