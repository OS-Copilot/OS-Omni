"""iOS OpenBank 448872 / 086132: grade the events the brief requires, not the source-step order.

Neither brief fixes a sequence. The evaluators keep "every required event, nothing
unexpected" and only the logically required order (recipient before its transfer;
for 086132 also transfer and stated Activity search before the dispute).
"""

from __future__ import annotations

import copy

from evaluators.ios.openbank_2_2_transfer_security_448872 import (
    OpenBankTransferSecurity448872Evaluator as Eval448872,
)
from evaluators.ios.openbank_lena_marco_dispute_security_086132 import (
    OpenBankLenaMarcoDisputeSecurity086132Evaluator as Eval086132,
)

BOUNDARY = {"mode": "automatic", "min_seq_exclusive": 0}
SESSION = {
    "loggedIn": True,
    "user": {
        "id": "cust-jordan",
        "displayName": "Jordan Lee",
        "preferredName": "Jordan",
        "email": "jordan@openbank.local",
        "phone": "13900003026",
    },
}


def _events(payloads_in_order):
    return [
        {**payload, "seq": seq, "timestamp": f"2026-10-11T10:50:{seq:02d}.000Z"}
        for seq, payload in enumerate(payloads_in_order, start=1)
    ]


def _failed(result):
    return set(result.metadata["failed_checks"])


# ---------------------------------------------------------------------------
# 448872: two recipients, three payments, security preferences
# ---------------------------------------------------------------------------

OWEN = {
    "id": "recipient-owen", "name": "Owen Reed", "type": "person", "nickname": "Internet",
    "bank": "OpenBank", "routingNumber": "021000089", "accountNumber": "0000007799",
    "mask": "7799", "favorite": False,
}
NORA = {
    "id": "recipient-nora", "name": "Nora Vale", "type": "person", "nickname": "Cloud backup",
    "bank": "OpenBank", "routingNumber": "021000089", "accountNumber": "0000007842",
    "mask": "7842", "favorite": False,
}
OWEN_TRANSFER = {
    "id": "transfer-owen", "fromAccountId": "checking-2381", "recipientId": OWEN["id"],
    "recipientName": "Owen Reed", "amount": 3.05, "scheduledDate": "2026-06-01",
    "memo": "Internet", "status": "Completed",
}
RAINY = {
    "id": "transfer-rainy", "fromAccountId": "checking-2381", "recipientId": "rec-rainy-day",
    "recipientName": "Rainy Day Savings", "amount": 4.10, "scheduledDate": "2026-06-01",
    "memo": "Internet reserve", "status": "Completed",
}
CITY_PAYMENT = {
    "id": "payment-city", "billerId": "bill-city-utilities", "billerName": "City Utilities",
    "fromAccountId": "checking-2381", "amount": 92.35, "scheduledDate": "2026-06-02",
    "memo": "Utility June", "status": "Scheduled",
}


def _448872_payloads():
    return dict(Eval448872._expected_events(
        owen=OWEN, owen_transfer=OWEN_TRANSFER, rainy=RAINY, city_payment=CITY_PAYMENT, nora=NORA,
    ))


# The English brief's order: both recipients first, then the payments, then the
# Security section with Large purchase before the two alerts.
BRIEF_ORDER_448872 = [
    "owen_recipient", "nora_recipient", "owen_transfer", "rainy_day_transfer",
    "city_utilities_payment", "payment_due_text", "large_purchase_push",
    "upcoming_bill_read", "new_sign_in_read", "checking_card_lock",
]


def _448872_state(labels=BRIEF_ORDER_448872):
    payloads = _448872_payloads()
    events = _events([payloads[label] for label in labels])
    card_ts = next(
        (event["timestamp"] for event in events if event["type"] == "card_locked"), None
    )
    return {
        "session": copy.deepcopy(SESSION),
        "recipients": [dict(OWEN), dict(NORA)],
        "transfers": [dict(OWEN_TRANSFER), dict(RAINY)],
        "transactions": [
            {"id": "txn-owen", "date": "2026-06-01", "status": "Posted",
             "tags": ["transfer", "external-account"], "note": "Internet",
             "accountId": "checking-2381", "description": "Transfer to Owen Reed",
             "merchant": "Owen Reed", "category": "Transfer", "amount": -3.05},
            {"id": "txn-rainy-out", "date": "2026-06-01", "status": "Posted", "tags": ["transfer"],
             "note": "Internet reserve", "accountId": "checking-2381",
             "description": "Transfer to Rainy Day Savings", "merchant": "Rainy Day Savings",
             "category": "Transfer", "amount": -4.10},
            {"id": "txn-rainy-in", "date": "2026-06-01", "status": "Posted", "tags": ["transfer"],
             "note": "Internet reserve", "accountId": "savings-9140",
             "description": "Transfer from Everyday Checking", "merchant": "OpenBank Transfer",
             "category": "Transfer", "amount": 4.10},
        ],
        "accounts": [
            {"id": "checking-2381", "name": "Everyday Checking", "type": "checking", "mask": "2381",
             "balance": 4279.58, "available": 4209.58, "currency": "USD", "routing": "021000089",
             "accountNumber": "0003922381", "status": "Open"},
            {"id": "savings-9140", "name": "Rainy Day Savings", "type": "savings", "mask": "9140",
             "balance": 12344.28, "available": 12344.28, "currency": "USD", "routing": "021000089",
             "accountNumber": "0002189140", "apy": 4.12, "status": "Open"},
        ],
        "alertSettings": [
            {"id": "pref-payment-due", "accountId": "credit-7712", "name": "Payment due",
             "daysBefore": 7, "enabled": True, "email": True, "sms": True, "push": True},
            {"id": "pref-large-purchase", "accountId": "credit-7712", "name": "Large purchase",
             "threshold": 100, "enabled": True, "email": True, "sms": True, "push": False},
        ],
        "billPayments": [dict(CITY_PAYMENT)],
        "billers": [
            {"id": "bill-city-utilities", "name": "City Utilities", "category": "Utilities",
             "dueDate": "2026-06-03", "amountDue": 0, "minimumDue": 92.35, "status": "Scheduled",
             "lastPaidDate": "2026-05-03", "autopay": False},
        ],
        "alerts": [
            {"id": "alert-1", "type": "security", "title": "New sign-in from macOS",
             "body": "A sign-in was recorded from Seattle, WA.",
             "createdAt": "2026-05-24T18:30:00.000Z", "read": True},
            {"id": "alert-2", "type": "cashflow", "title": "Upcoming bill",
             "body": "City Utilities is due on June 3.",
             "createdAt": "2026-05-23T12:10:00.000Z", "read": True},
        ],
        "cardControls": [
            {"id": "card-debit-2381", "accountId": "checking-2381",
             "name": "Everyday Checking debit card", "type": "debit", "mask": "4428",
             "status": "Locked", "digitalWallet": "Apple Pay", "lastChangedAt": card_ts},
        ],
        "evaluationEvents": events,
    }


def test_448872_brief_order_passes():
    result = Eval448872.evaluate_state(_448872_state(), boundary=BOUNDARY)
    assert result.status.value == "PASS", result.metadata["failed_checks"]


def test_448872_source_step_order_still_passes():
    source_order = [
        "owen_recipient", "owen_transfer", "payment_due_text", "rainy_day_transfer",
        "city_utilities_payment", "upcoming_bill_read", "large_purchase_push",
        "new_sign_in_read", "checking_card_lock", "nora_recipient",
    ]
    result = Eval448872.evaluate_state(_448872_state(source_order), boundary=BOUNDARY)
    assert result.status.value == "PASS", result.metadata["failed_checks"]


def test_448872_identical_preference_resave_is_not_a_duplicate():
    labels = BRIEF_ORDER_448872 + ["payment_due_text"]
    result = Eval448872.evaluate_state(_448872_state(labels), boundary=BOUNDARY)
    assert result.status.value == "PASS", result.metadata["failed_checks"]


def test_448872_transfer_before_its_recipient_fails():
    labels = list(BRIEF_ORDER_448872)
    labels.remove("owen_transfer")
    labels.insert(0, "owen_transfer")
    result = Eval448872.evaluate_state(_448872_state(labels), boundary=BOUNDARY)
    assert result.status.value == "FAIL"
    assert _failed(result) == {"durable_events_and_required_order"}
    check = next(c for c in result.metadata["checks"] if c["name"] == "durable_events_and_required_order")
    assert check["actual"]["order_violations"] == [["owen_recipient", "owen_transfer"]]


def test_448872_duplicate_missing_or_unexpected_events_fail():
    duplicate = Eval448872.evaluate_state(
        _448872_state(BRIEF_ORDER_448872 + ["rainy_day_transfer"]), boundary=BOUNDARY
    )
    assert "durable_events_and_required_order" in _failed(duplicate)

    missing_labels = [label for label in BRIEF_ORDER_448872 if label != "new_sign_in_read"]
    missing = Eval448872.evaluate_state(_448872_state(missing_labels), boundary=BOUNDARY)
    assert {"new_sign_in_read_exact", "durable_events_and_required_order"} <= _failed(missing)

    extra_state = _448872_state()
    extra_state["evaluationEvents"].append(
        {"type": "alert_marked_read", "alertId": "alert-3", "seq": 99,
         "timestamp": "2026-10-11T10:51:00.000Z"}
    )
    extra = Eval448872.evaluate_state(extra_state, boundary=BOUNDARY)
    assert _failed(extra) == {"durable_events_and_required_order"}


def test_448872_wrong_final_object_still_fails():
    state = _448872_state()
    state["recipients"][1]["nickname"] = "Cloud"
    assert "nora_recipient_exact" in _failed(Eval448872.evaluate_state(state, boundary=BOUNDARY))


# ---------------------------------------------------------------------------
# 086132: Lena/Marco transfers, dispute found by Activity search, security
# ---------------------------------------------------------------------------

LENA = {
    "id": "recipient-lena", "name": "Lena Wu", "type": "person", "nickname": "Design split",
    "bank": "OpenBank", "routingNumber": "021000089", "accountNumber": "0000007766",
    "mask": "7766", "favorite": False,
}
MARCO = {
    "id": "recipient-marco", "name": "Marco Li", "type": "person", "nickname": "Studio rent",
    "bank": "OpenBank", "routingNumber": "021000089", "accountNumber": "0000007767",
    "mask": "7767", "favorite": False,
}
LENA_TRANSFER = {
    "id": "transfer-lena", "fromAccountId": "checking-2381", "recipientId": LENA["id"],
    "recipientName": "Lena Wu", "amount": 4.20, "scheduledDate": "2026-06-01",
    "memo": "Design split", "status": "Completed",
}
MARCO_TRANSFER = {
    "id": "transfer-marco", "fromAccountId": "checking-2381", "recipientId": MARCO["id"],
    "recipientName": "Marco Li", "amount": 1.25, "scheduledDate": "2026-06-01",
    "memo": "Studio rent", "status": "Completed",
}
LENA_TXN = {
    "id": "txn-lena", "date": "2026-06-01", "status": "Posted",
    "tags": ["transfer", "external-account"], "note": "Design split",
    "accountId": "checking-2381", "description": "Transfer to Lena Wu", "merchant": "Lena Wu",
    "category": "Transfer", "amount": -4.20,
}
MARCO_TXN = {
    "id": "txn-marco", "date": "2026-06-01", "status": "Posted",
    "tags": ["transfer", "external-account"], "note": "Studio rent",
    "accountId": "checking-2381", "description": "Transfer to Marco Li", "merchant": "Marco Li",
    "category": "Transfer", "amount": -1.25,
}
DISPUTE = {
    "id": "dispute-marco", "caseNumber": "D20260601-001", "transactionId": MARCO_TXN["id"],
    "accountId": "checking-2381", "merchant": "Marco Li", "amount": 1.25,
    "reason": "I don't recognize this charge", "contactedMerchant": False,
    "details": "Unknown rent debit", "status": "Submitted", "submittedAt": "2026-06-01",
}


def _view(**overrides):
    payload = {
        "type": "transactions_viewed", "accountId": "all", "q": "", "category": "all",
        "status": "all", "dateRange": "all", "from": "", "to": "", "page": 1,
        "pageSize": 10, "total": 599,
    }
    payload.update(overrides)
    return payload


FILTERED = _view(q="Studio rent", category="Transfer", status="Posted", dateRange="last30",
                 **{"from": "2026-05-03", "to": "2026-06-01"}, total=1)


def _086132_payloads():
    payloads = Eval086132._expected_event_payloads(
        lena=LENA, marco=MARCO, lena_transfer=LENA_TRANSFER, marco_transfer=MARCO_TRANSFER,
        marco_txn=MARCO_TXN, dispute=DISPUTE,
    )
    payloads["filtered_result"] = FILTERED
    return payloads


# A brief-faithful run: filters set in a different order (Time first), one search,
# details opened once, and the Security items in the brief's order.
BRIEF_ORDER_086132 = [
    "lena_recipient", "marco_recipient", "lena_transfer", "marco_transfer",
    _view(), _view(q="Studio rent", total=1),
    _view(q="Studio rent", dateRange="last30", **{"from": "2026-05-03", "to": "2026-06-01"}, total=1),
    "filtered_result", "marco_details", "marco_dispute",
    "large_purchase_push", "low_balance_text", "payment_due_text",
    "upcoming_bill_read", "credit_card_lock",
]


def _086132_state(items=BRIEF_ORDER_086132):
    payloads = _086132_payloads()
    events = _events([payloads[item] if isinstance(item, str) else item for item in items])
    card_ts = next((event["timestamp"] for event in events if event["type"] == "card_locked"), None)
    return {
        "session": copy.deepcopy(SESSION),
        "recipients": [dict(LENA), dict(MARCO)],
        "transfers": [dict(LENA_TRANSFER), dict(MARCO_TRANSFER)],
        "transactions": [dict(LENA_TXN), dict(MARCO_TXN)],
        "disputes": [dict(DISPUTE)],
        "alertSettings": [
            {"id": "pref-large-purchase", "accountId": "credit-7712", "name": "Large purchase",
             "threshold": 100, "enabled": True, "email": True, "sms": True, "push": False},
            {"id": "pref-low-balance", "accountId": "checking-2381", "name": "Low balance",
             "threshold": 250, "enabled": True, "email": True, "sms": True, "push": True},
            {"id": "pref-payment-due", "accountId": "credit-7712", "name": "Payment due",
             "daysBefore": 7, "enabled": True, "email": True, "sms": True, "push": True},
        ],
        "alerts": [
            {"id": "alert-2", "type": "cashflow", "title": "Upcoming bill",
             "body": "City Utilities is due on June 3.",
             "createdAt": "2026-05-23T12:10:00.000Z", "read": True},
        ],
        "cardControls": [
            {"id": "card-credit-7712", "accountId": "credit-7712", "name": "OpenBank Rewards Card",
             "type": "credit", "mask": "7712", "status": "Locked", "digitalWallet": "Apple Pay",
             "lastChangedAt": card_ts},
        ],
        "evaluationEvents": events,
    }


def test_086132_brief_faithful_run_with_other_filter_order_passes():
    result = Eval086132.evaluate_state(_086132_state(), boundary=BOUNDARY)
    assert result.status.value == "PASS", result.metadata["failed_checks"]


def test_086132_search_on_checking_account_counts():
    items = [
        item if item != "filtered_result" else {**FILTERED, "accountId": "checking-2381"}
        for item in BRIEF_ORDER_086132
    ]
    result = Eval086132.evaluate_state(_086132_state(items), boundary=BOUNDARY)
    assert result.status.value == "PASS", result.metadata["failed_checks"]


def test_086132_missing_stated_search_fails():
    items = [item for item in BRIEF_ORDER_086132 if item != "filtered_result"]
    result = Eval086132.evaluate_state(_086132_state(items), boundary=BOUNDARY)
    assert "activity_filter_exact" in _failed(result)


def test_086132_search_after_the_dispute_fails():
    items = [item for item in BRIEF_ORDER_086132 if item != "filtered_result"] + ["filtered_result"]
    result = Eval086132.evaluate_state(_086132_state(items), boundary=BOUNDARY)
    assert _failed(result) == {"durable_events_and_required_order"}


def test_086132_transfer_before_recipient_fails():
    items = list(BRIEF_ORDER_086132)
    items.remove("lena_transfer")
    items.insert(0, "lena_transfer")
    result = Eval086132.evaluate_state(_086132_state(items), boundary=BOUNDARY)
    assert _failed(result) == {"durable_events_and_required_order"}


def test_086132_duplicate_dispute_or_unexpected_business_event_fails():
    duplicate = Eval086132.evaluate_state(
        _086132_state(BRIEF_ORDER_086132 + ["marco_dispute"]), boundary=BOUNDARY
    )
    assert "marco_dispute_exact" in _failed(duplicate)

    wrong_setting = {
        "type": "alert_setting_updated", "settingId": "pref-large-purchase",
        "accountId": "credit-7712", "enabled": True, "email": True, "sms": False,
        "push": False, "threshold": 100,
    }
    extra = Eval086132.evaluate_state(
        _086132_state(BRIEF_ORDER_086132 + [wrong_setting]), boundary=BOUNDARY
    )
    assert "durable_events_and_required_order" in _failed(extra)


def test_086132_wrong_dispute_details_still_fails():
    state = _086132_state()
    state["disputes"][0]["details"] = "Unknown debit"
    assert "marco_dispute_exact" in _failed(Eval086132.evaluate_state(state, boundary=BOUNDARY))
