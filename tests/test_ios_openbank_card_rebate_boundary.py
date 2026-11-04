"""OpenBank task events must be scoped to this run, not an old calendar window."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluators.cua_review.initializers.ios.openbank_open_app import (
    _baseline_max_event_seq,
)
from evaluators.ios.openbank_card_rebate_dispute_183183 import (
    MANUAL_WINDOW_END,
    MANUAL_WINDOW_START,
    OpenBankCardRebateDispute183183Evaluator,
)
from platforms.ios.runners.evaluation import build_evaluator_context


def test_initializer_captures_maximum_persisted_event_sequence():
    assert _baseline_max_event_seq(
        {"evaluationEvents": [{"seq": 4}, {"seq": 19}, {"seq": "bad"}, None]}
    ) == 19
    assert _baseline_max_event_seq({"evaluationEvents": []}) == -1


def test_current_run_boundary_overrides_obsolete_manual_wall_clock_window():
    boundary = OpenBankCardRebateDispute183183Evaluator._resolve_boundary(
        {"initialization": {"metadata": {"baseline_max_event_seq": 19}}},
        {
            "manual_window_start": MANUAL_WINDOW_START,
            "manual_window_end": MANUAL_WINDOW_END,
        },
    )
    assert boundary == {"mode": "automatic", "min_seq_exclusive": 19}


def test_ios_evaluation_context_receives_initializer_metadata():
    initialization = {"status": "PASS", "metadata": {"baseline_max_event_seq": 19}}
    context = build_evaluator_context(
        params={}, controller=None, final_observation=None, initialization=initialization
    )
    assert context["initialization"] == initialization


ACTIVITY_VIEW = {
    "type": "transactions_viewed", "accountId": "all", "q": "", "category": "all",
    "status": "all", "dateRange": "all", "from": "", "to": "", "page": 1,
    "pageSize": 10, "total": 597,
}
ACE_SEARCH = {**ACTIVITY_VIEW, "q": "Ace Hardware", "total": 15}
ACE_DETAILS = {
    "type": "transaction_details_viewed",
    "transactionId": "txn-daily-202605-08",
    "accountId": "checking-2381",
}
# The recorded human demo order (browsing included).
SOURCE_ORDER = [
    ACTIVITY_VIEW,
    ACE_SEARCH,
    ACE_DETAILS,
    "ace_dispute",
    ACE_DETAILS,
    "mira_recipient",
    "dana_recipient",
    "mira_transfer",
    "rainy_paperless",
    "dana_transfer",
    "payment_due_text",
    "upcoming_bill_read",
    "low_balance_text",
]


def _completed_reference_state(event_items=SOURCE_ORDER):
    dispute = {
        "id": "dispute-ref",
        "caseNumber": "D20260601-001",
        "transactionId": "txn-daily-202605-08",
        "accountId": "checking-2381",
        "merchant": "Ace Hardware",
        "amount": 25.69,
        "reason": "Canceled or returned item",
        "contactedMerchant": True,
        "details": "Return for rebate",
        "status": "Submitted",
        "submittedAt": "2026-06-01",
    }
    mira = {
        "id": "recipient-mira",
        "name": "Mira song",
        "type": "person",
        "nickname": "Card rebate",
        "bank": "OpenBank",
        "routingNumber": "021000089",
        "accountNumber": "0000007755",
        "mask": "7755",
        "favorite": False,
    }
    dana = {
        "id": "recipient-dana",
        "name": "Dana Cole",
        "type": "person",
        "nickname": "Audit fee",
        "bank": "OpenBank",
        "routingNumber": "021000089",
        "accountNumber": "0000007756",
        "mask": "7756",
        "favorite": False,
    }
    mira_transfer = {
        "id": "transfer-mira",
        "fromAccountId": "checking-2381",
        "recipientId": mira["id"],
        "recipientName": "Mira song",
        "amount": 2.75,
        "scheduledDate": "2026-07-29",
        "memo": "Card rebate",
        "status": "Scheduled",
    }
    dana_transfer = {
        "id": "transfer-dana",
        "fromAccountId": "checking-2381",
        "recipientId": dana["id"],
        "recipientName": "Dana Cole",
        "amount": 1.35,
        "scheduledDate": "2026-07-30",
        "memo": "Audit fee",
        "status": "Scheduled",
    }
    events_by_label = OpenBankCardRebateDispute183183Evaluator._expected_event_payloads(
        dispute=dispute,
        mira=mira,
        dana=dana,
        mira_transfer=mira_transfer,
        dana_transfer=dana_transfer,
    )
    events = []
    rainy_timestamp = None
    for seq, item in enumerate(event_items, start=1):
        timestamp = f"2026-10-11T10:50:{seq:02d}.000Z"
        if item == "rainy_paperless":
            rainy_timestamp = timestamp
        payload = events_by_label[item] if isinstance(item, str) else item
        events.append({**payload, "seq": seq, "timestamp": timestamp})
    return {
        "session": {
            "loggedIn": True,
            "user": {
                "id": "cust-jordan",
                "displayName": "Jordan Lee",
                "preferredName": "Jordan",
                "email": "jordan@openbank.local",
                "phone": "13900003026",
            },
        },
        "transactions": [{
            "id": "txn-daily-202605-08",
            "accountId": "checking-2381",
            "date": "2026-05-27",
            "description": "Ace Hardware home supplies",
            "merchant": "Ace Hardware",
            "category": "Home",
            "amount": -25.69,
            "status": "Posted",
            "tags": ["home"],
            "note": "",
        }],
        "disputes": [dispute],
        "recipients": [mira, dana],
        "transfers": [mira_transfer, dana_transfer],
        "paperlessSettings": [{
            "accountId": "savings-9140",
            "delivery": "Paperless",
            "eligible": True,
            "updatedAt": rainy_timestamp,
        }],
        "alertSettings": [
            {"id": "pref-payment-due", "accountId": "credit-7712", "name": "Payment due", "daysBefore": 7, "enabled": True, "email": True, "sms": True, "push": True},
            {"id": "pref-low-balance", "accountId": "checking-2381", "name": "Low balance", "threshold": 250, "enabled": True, "email": True, "sms": True, "push": True},
        ],
        "alerts": [{"id": "alert-2", "type": "cashflow", "title": "Upcoming bill", "body": "City Utilities is due on June 3.", "createdAt": "2026-05-23T12:10:00.000Z", "read": True}],
        "evaluationEvents": events,
    }


def test_current_date_correct_reference_passes_and_wrong_recipient_still_fails():
    task_state = _completed_reference_state()
    evaluator = OpenBankCardRebateDispute183183Evaluator
    boundary = evaluator._resolve_boundary(
        {"initialization": {"metadata": {"baseline_max_event_seq": 0}}},
        {"manual_window_start": MANUAL_WINDOW_START, "manual_window_end": MANUAL_WINDOW_END},
    )
    assert evaluator.evaluate_state(task_state, boundary=boundary).status.value == "PASS"

    wrong_state = _completed_reference_state()
    wrong_state["recipients"][0]["accountNumber"] = "0000000000"
    result = evaluator.evaluate_state(wrong_state, boundary=boundary)
    assert result.status.value == "FAIL"
    assert "mira_recipient_exact" in result.metadata["failed_checks"]
