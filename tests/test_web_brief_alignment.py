"""Web tasks whose evaluators asked for more than the brief (Opus 5.5 audit, WEB-003/006/014/026/051).

Each test builds the end state a run that follows the English brief leaves, and checks the evaluator
grades what the brief asks for and no more.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from evaluators.cua_review.core.evaluation import EvalStatus

REPO = Path(__file__).resolve().parents[1]


def _task(name: str) -> dict:
    return yaml.safe_load((REPO / "tasks/v1/web" / name).read_text(encoding="utf-8"))


# --- OpenBank: the second transfer has no date in the brief ------------------------------------

from evaluators.linux import openbank_nina_evan_transfers_city_utilities_tessa_1787714989601_855205 as openbank  # noqa: E402


def _bank_document() -> dict:
    document: dict = {"recipients": [], "transfers": [], "billPayments": [], "alerts": []}
    for collection, expected in openbank.DECLARED:
        document[collection].append({"id": "row-%d" % len(document[collection]), **expected})
    return document


def _bank_verdict(monkeypatch, document: dict):
    monkeypatch.setattr(openbank, "_read_document", lambda controller, key, directories: (document, "leveldb"))
    task = _task("openbank_nina_evan_transfers_city_utilities_tessa_1787714989601_855205.yaml")
    evaluator = openbank.LinuxOpenBankNinaEvanTransfersCityUtilitiesTessa1787714989601855205Evaluator()
    return evaluator.evaluate({"params": task["evaluation"]["params"], "controller": None})


def test_openbank_second_transfer_keeps_whatever_date_the_form_had(monkeypatch):
    document = _bank_document()
    evan = next(row for row in document["transfers"] if row["recipientName"] == "Evan Holt")
    evan["scheduledDate"] = "2026-06-05"
    assert _bank_verdict(monkeypatch, document).status == EvalStatus.PASS


def test_openbank_first_transfer_date_and_second_transfer_fields_still_count(monkeypatch):
    document = _bank_document()
    nina = next(row for row in document["transfers"] if row["recipientName"] == "Nina park")
    nina["scheduledDate"] = "2026-06-05"  # the brief gives this one's date
    assert _bank_verdict(monkeypatch, document).status == EvalStatus.FAIL
    document = _bank_document()
    evan = next(row for row in document["transfers"] if row["recipientName"] == "Evan Holt")
    evan["memo"] = "June rent"
    assert _bank_verdict(monkeypatch, document).status == EvalStatus.FAIL


# --- OpenBlender: the brief names no workspace -------------------------------------------------

from evaluators.linux.openblender_client_camera_review import OpenBlenderStateEvaluator  # noqa: E402


def _blender_state(params: dict, workspace: str) -> dict:
    materials = [{"id": "mat-matte", "name": "Matte Rubber"}]
    objects = []
    for item in params["objects"]:
        row = {key: item[key] for key in ("name", "type", "collection", "location", "rotation") if key in item}
        row["scale"] = item.get("scale", [1.0, 1.0, 1.0])
        if "material_name" in item:
            row["materialId"] = "mat-matte"
        row["modifiers"] = [
            {"name": mod["name"], "type": mod["type"], "settings": {"amount": mod["amount"], "segments": mod["segments"]}}
            for mod in item.get("modifiers", [])
        ]
        objects.append(row)
    project = {"id": params["project_id"], "name": params["project_name"], "output": dict(params["output"]),
               "objects": objects}
    return {"activeWorkspace": workspace, "currentProjectId": project["id"], "projects": [project],
            "materials": materials}


def _blender_verdict(params: dict, workspace: str):
    evaluator = OpenBlenderStateEvaluator()
    evaluator._read_document = lambda context, params_: {"state": _blender_state(params, workspace)}
    return evaluator.evaluate({"params": params})


def test_openblender_client_camera_review_accepts_the_layout_workspace_the_source_steps_use():
    params = _task("openblender_client_camera_review.yaml")["evaluation"]["params"]
    assert "active_workspace" not in params
    result = _blender_verdict(params, "Layout")
    assert result.status == EvalStatus.PASS, result.metadata["failures"]
    assert _blender_verdict(dict(params, active_workspace="Rendering"), "Layout").status == EvalStatus.FAIL  # the old gate


# --- OpenCode: the brief names three tabs -----------------------------------------------------

def _opencode_script(leveldb: Path) -> str:
    command = _task("opencode_sk2_trendcard_loading_label_commit.yaml")["evaluation"]["params"]["command"]
    script = command.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    return script.replace('Path("/home/user/.config/google-chrome/Default/Local Storage/leveldb")', "Path(%r)" % str(leveldb))


def _opencode_run(tmp_path: Path, tabs: list[str]) -> dict:
    state = {
        "files": {"src/components/TrendCard.jsx": {"content": '<div className="skeleton" aria-label="Loading" role="status" />'}},
        "git": {"timeline": ["Now Fix loading label"], "changes": []},
        "terminal": ["$ npm run lint", "$ npm run lint"],
        "tabs": tabs,
        "activeFile": "src/components/TrendCard.jsx",
        "assistant": [{"role": "user", "text": "tests for loading"}],
        "view": "scm",
    }
    (tmp_path / "000003.log").write_bytes(b"\x00_file://\x00\x01opencode.workspace.v1\x01" + json.dumps(state).encode())
    done = subprocess.run([sys.executable, "-I", "-c", _opencode_script(tmp_path)], capture_output=True, text=True, timeout=60)
    payload = json.loads(done.stdout)
    return {check["name"]: check for check in payload["checks"]}


def test_opencode_trendcard_requires_only_the_tabs_the_brief_names(tmp_path):
    named = ["package.json", "src/views/RevenueDashboard.jsx", "src/components/TrendCard.jsx"]
    checks = _opencode_run(tmp_path, named)  # useForecast.js (open in the seed) was closed
    assert all(check["passed"] for check in checks.values()), [name for name, check in checks.items() if not check["passed"]]
    assert not _opencode_run(tmp_path, named[1:])["required_tabs_opened"]["passed"]  # package.json closed


# --- OpenDoc: the Review by EOD comment itself must be resolved --------------------------------

from evaluators.cua_review.evaluators.linux import opendoc  # noqa: E402


def _launch_review(comments: list[dict]) -> dict:
    html = ("<h1>Launch Review</h1><p>Launch</p><h2>Action notes</h2><ul><li>Alex owns copy</li><li>Maya checks risk</li>"
            "<li>Design signs off</li></ul><p>2026-09-21</p><nav>Table of contents</nav><p>Page 1</p>")
    return {"title": "Launch Review", "html": html, "header": "", "footer": "", "settings": {"ruler": True},
            "comments": comments}


def _doc_verdict(monkeypatch, comments: list[dict]):
    monkeypatch.setattr(opendoc, "_read_documents", lambda controller, params: ([_launch_review(comments)], "leveldb"))
    exports = [{"path": "/home/user/Downloads/launch-review.%s" % ext, "text": "Launch Review"} for ext in ("doc", "txt")]
    monkeypatch.setattr(opendoc, "_scan_files", lambda *args, **kwargs: (2, exports))
    params = _task("opendoc_launch_review_duplicate_hard.yaml")["evaluation"]["params"]
    return opendoc.OpenDocLaunchReviewEvaluator().evaluate({"params": params, "controller": None})


def _comments(resolved: str) -> list[dict]:
    return [{"text": text, "resolved": text == resolved} for text in ("Review by EOD", "Reviewing", "OK")]


def test_opendoc_launch_review_resolved_comment_is_graded_on_that_comment(monkeypatch):
    result = _doc_verdict(monkeypatch, _comments("Review by EOD"))
    assert result.status == EvalStatus.PASS, result.message
    result = _doc_verdict(monkeypatch, _comments("OK"))  # another comment resolved instead
    assert result.status == EvalStatus.FAIL
    assert [check["name"] for check in result.metadata["checks"] if not check["passed"]] == ["comment.resolved_text"]


def test_opendoc_launch_review_rules_no_longer_call_the_resolved_comment_auxiliary():
    params = _task("opendoc_launch_review_duplicate_hard.yaml")["evaluation"]["params"]
    assert params["resolved_comment_text"] == "Review by EOD"
    assert not any("auxiliary" in rule for rule in params["verifier_rules"]["checks"])


# --- OpenMail: a discarded draft only has to leave Drafts ---------------------------------------

from evaluators.cua_review.evaluators.linux import openmail  # noqa: E402

DRAFT = {"subject": "Northline contact note", "body": "Contact card compose route verified for receipts."}


def _mailbox(draft_folder: str | None) -> dict:
    messages = [
        {"folder": "sent", "subject": "Re: Receipt PDF for order 4268", "body": "Northline receipt is ready for review.",
         "to": [{"email": "orders@northline.example.test"}], "labels": []},
        {"folder": "inbox", "subject": "Receipt PDF for order 4268", "body": "Attached.", "to": [], "labels": []},
        {"folder": "inbox", "subject": "Platform reference image for RN-2041", "body": "See image.", "to": [], "labels": []},
        {"folder": "sent", "subject": "Fwd: Platform reference image for RN-2041",
         "body": "Rail platform reference for the receipt review.", "to": [{"email": "receipts@northline.example.test"}],
         "labels": []},
        {"folder": "sent", "subject": "RideShare receipt question", "priority": "low", "starred": True,
         "body": "Can you confirm the ride receipt for the travel folder? Please reply with the receipt number.",
         "to": [{"email": "support@rideshare.example.test"}], "labels": ["Travel"]},
    ]
    if draft_folder:
        messages.append(dict(DRAFT, folder=draft_folder, to=[{"email": "orders@northline.example.test"}], labels=[]))
    return {"messages": messages, "settings": {}}


def _mail_failures(monkeypatch, state: dict) -> list[str]:
    monkeypatch.setattr(openmail, "read_state_document", lambda context, params: (state, "leveldb"))
    params = _task("openmail_contacts_receipt_review_workflow.yaml")["evaluation"]["params"]
    result = openmail.OpenMailContactsReceiptReviewEvaluator().evaluate({"params": params})
    return result.metadata["failures"]


def test_openmail_discarded_draft_may_be_gone_or_in_trash(monkeypatch):
    assert _mail_failures(monkeypatch, _mailbox(None)) == []  # Discard removes the saved draft
    assert _mail_failures(monkeypatch, _mailbox("trash")) == []  # Delete moves it to Trash: no longer in Drafts


def test_openmail_draft_left_in_drafts_or_sent_is_not_discarded(monkeypatch):
    absent = ["absent:discarded_draft_subject", "absent:discarded_draft_body"]
    assert _mail_failures(monkeypatch, _mailbox("drafts")) == absent
    assert _mail_failures(monkeypatch, _mailbox("sent")) == absent
    renamed = _mailbox("drafts")
    renamed["messages"][-1]["subject"] = "Northline note"  # the body still identifies the kept draft
    assert _mail_failures(monkeypatch, renamed) == ["absent:discarded_draft_body"]
