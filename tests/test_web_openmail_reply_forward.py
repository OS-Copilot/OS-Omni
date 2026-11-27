"""OpenMail contacts_receipt (Web, WEB-055): the reply / forward / RideShare checks must be met by the
messages the run sent, not by the seeded messages they start from.

The seeded inbox already holds "Receipt PDF for order 4268" and "Platform reference image for RN-2041",
and 40 seeded messages carry the Travel label, so subject or label checks over the whole mailbox passed
for a run that never replied, forwarded or sent the RideShare email.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.cua_review.evaluators.linux import openmail

TASK = Path(__file__).resolve().parents[1] / "tasks/v1/web/openmail_contacts_receipt_review_workflow.yaml"
ACCOUNT = {"name": "Anonym Tester", "email": "anonym-x2024@outlook.com"}
NORTHLINE = {"name": "Northline Market", "email": "receipts@northlinemarket.example"}


def _seeded() -> list[dict]:
    return [
        {"id": "tb-0010", "folder": "inbox", "subject": "Receipt PDF for order 4268", "from": NORTHLINE,
         "to": [ACCOUNT], "body": "Attached is the receipt PDF for order 4268.", "labels": ["Receipts", "Finance"]},
        {"id": "tb-0003", "folder": "inbox", "subject": "Platform reference image for RN-2041",
         "from": {"name": "Railway Northeast Desk", "email": "operations@railway-ne.example"}, "to": [ACCOUNT],
         "body": "Attached is the reference platform image requested for RN-2041.", "labels": ["Follow up"]},
        {"id": "tb-0120", "folder": "inbox", "subject": "Survey for RN-2041",
         "from": {"name": "Railway Northeast", "email": "service@railne.example.test"}, "to": [ACCOUNT],
         "body": "How was your trip?", "labels": ["Travel"], "starred": True, "priority": "low"},
    ]


def _completed() -> list[dict]:
    """The mailbox the brief describes, shaped like OpenMail's own Reply / Forward / Send records."""
    return _seeded() + [
        {"id": "m-3", "folder": "sent", "subject": "RideShare receipt question", "from": ACCOUNT,
         "to": [{"name": "RideShare", "email": "receipts@rideshare.example.test"}], "priority": "low",
         "starred": True, "labels": ["Travel"],
         "body": "Can you confirm the ride receipt for the travel folder? Please reply with the receipt number."},
        {"id": "m-2", "folder": "sent", "subject": "Fwd: Platform reference image for RN-2041", "from": ACCOUNT,
         "to": [{"name": "Northline Market", "email": "receipts@northline.example.test"}], "labels": ["Follow up"],
         "body": "Rail platform reference for the receipt review.\n\nForwarded message:\n..."},
        {"id": "m-1", "folder": "sent", "subject": "Re: Receipt PDF for order 4268", "from": ACCOUNT,
         "to": [NORTHLINE], "labels": ["Receipts", "Finance"],
         "body": "Northline receipt is ready for review.\n\nOn Apr 5, Northline Market wrote:\n> Attached."},
    ]


def _failures(monkeypatch, messages: list[dict]) -> list[str]:
    state = {"messages": copy.deepcopy(messages), "settings": {}}
    monkeypatch.setattr(openmail, "read_state_document", lambda context, params: (state, "leveldb"))
    params = yaml.safe_load(TASK.read_text(encoding="utf-8"))["evaluation"]["params"]
    result = openmail.OpenMailContactsReceiptReviewEvaluator().evaluate({"params": params})
    assert result.status == (EvalStatus.PASS if not result.metadata["failures"] else EvalStatus.FAIL)
    return result.metadata["failures"]


def _without(messages: list[dict], message_id: str) -> list[dict]:
    return [item for item in messages if item["id"] != message_id]


def _edited(messages: list[dict], message_id: str, **fields) -> list[dict]:
    rows = copy.deepcopy(messages)
    next(item for item in rows if item["id"] == message_id).update(fields)
    return rows


def test_the_completed_workflow_passes(monkeypatch):
    assert _failures(monkeypatch, _completed()) == []


def test_the_seeded_mailbox_alone_no_longer_passes_the_subject_and_label_checks(monkeypatch):
    # Before the fix only the three body texts failed here: both subjects and the Travel label were
    # found on seeded messages.
    failures = _failures(monkeypatch, _seeded())
    for check in ("subject:northline_reply_subject", "subject:rail_subject", "subject:rideshare_subject",
                  "label:rideshare_label", "folder:rideshare_folder", "priority:rideshare_priority",
                  "starred:rideshare_starred"):
        assert check in failures


def test_the_reply_must_be_a_sent_re_message_to_the_original_sender(monkeypatch):
    assert _failures(monkeypatch, _without(_completed(), "m-1")) == [
        "subject:northline_reply_subject", "body:northline_reply_body"]
    # still a draft: not sent
    assert "subject:northline_reply_subject" in _failures(monkeypatch, _edited(_completed(), "m-1", folder="drafts"))
    # sent somewhere else than to Northline Market
    elsewhere = _edited(_completed(), "m-1", to=[{"email": "receipts@rideshare.example.test"}])
    assert "subject:northline_reply_subject" in _failures(monkeypatch, elsewhere)
    # the reply body has to be in the reply, not in another message
    moved = _edited(_completed(), "m-1", body="Thanks.")
    moved.append({"id": "m-4", "folder": "drafts", "subject": "Note", "from": ACCOUNT, "to": [NORTHLINE],
                  "labels": [], "body": "Northline receipt is ready for review."})
    assert _failures(monkeypatch, moved) == ["body:northline_reply_body"]


def test_the_forward_must_be_a_sent_fwd_message_with_the_recipient_and_body(monkeypatch):
    assert _failures(monkeypatch, _without(_completed(), "m-2")) == [
        "subject:rail_subject", "recipient:rail_forward_to", "body:rail_forward_body"]
    wrong_to = _edited(_completed(), "m-2", to=[{"email": "operations@railway-ne.example"}])
    assert _failures(monkeypatch, wrong_to) == ["recipient:rail_forward_to"]


def test_the_rideshare_email_carries_the_label_priority_star_and_sent_folder_itself(monkeypatch):
    assert _failures(monkeypatch, _edited(_completed(), "m-3", labels=[])) == ["label:rideshare_label"]
    assert _failures(monkeypatch, _edited(_completed(), "m-3", starred=False)) == ["starred:rideshare_starred"]
    assert _failures(monkeypatch, _edited(_completed(), "m-3", priority="normal")) == ["priority:rideshare_priority"]
    assert _failures(monkeypatch, _edited(_completed(), "m-3", folder="drafts")) == ["folder:rideshare_folder"]


def test_ungrouped_expectations_keep_the_mailbox_wide_reading():
    groups = openmail._message_groups({"a_subject": "X", "a_reply_subject": "Y", "b_label": "Travel"}, [])
    assert openmail._group_of("b_label", groups) is None
    assert openmail._group_of("a_reply_body", groups) == "a_reply"
    assert openmail._group_of("a_body", groups) == "a"
