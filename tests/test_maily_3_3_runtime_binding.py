from datetime import datetime, timedelta, timezone
import hashlib
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from evaluators.ios.maily_instruction_3_3 import (
    DEFAULT_WINDOW_START,
    EXPECTED_DEVICE_TYPE_IDENTIFIER,
    MESSAGE_SPECS,
    RULESET_SHA256,
    RULESET_SPEC,
    MailyInstruction33Round9StateEvaluator as Evaluator,
    _simulator_matches_expected_device,
)


def _reference_row(spec, *, uid, index, wrong_attachment=False):
    msg = EmailMessage()
    msg["From"] = "alex.rivera@example.test"
    msg["To"] = spec["mailbox"]
    msg["Subject"] = spec["subject"]
    msg["Date"] = format_datetime(datetime(2026, 10, 12, tzinfo=timezone.utc) + timedelta(minutes=index))
    msg["Message-ID"] = f"<reference-{index}@example.test>"
    source_id = spec.get("source_message_id")
    if source_id:
        msg["In-Reply-To"] = source_id
        msg["References"] = source_id
    body = spec["body"]
    if spec["source_subject"]:
        body += f"\n{spec['source_subject']}"
    msg.set_content(body)
    attachment = spec.get("attachment")
    if attachment:
        filename = attachment.get("filename") or f"reference-{index}.jpg"
        asset = next(
            path
            for path in Path("assets/ios/maily").iterdir()
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == attachment["sha256"]
        )
        data = asset.read_bytes()
        if attachment.get("filename"):
            filename = attachment["filename"]
        if wrong_attachment:
            data = b"wrong attachment bytes"
        maintype, subtype = attachment["content_type"].split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return {"uid": uid, "subject": spec["subject"], "mimeMessage": msg.as_string()}


def test_maily3_runtime_binding_uses_device_type_not_mutable_simulator_name():
    info = {
        "name": "OS-Omni iOS v3",
        "state": "Booted",
        "isAvailable": True,
        "deviceTypeIdentifier": EXPECTED_DEVICE_TYPE_IDENTIFIER,
    }
    assert _simulator_matches_expected_device(info, EXPECTED_DEVICE_TYPE_IDENTIFIER)


def test_maily3_runtime_binding_rejects_wrong_device_type_and_unbooted_simulator():
    base = {
        "name": "OS-Omni iOS v3",
        "state": "Booted",
        "isAvailable": True,
        "deviceTypeIdentifier": EXPECTED_DEVICE_TYPE_IDENTIFIER,
    }
    assert not _simulator_matches_expected_device(
        {**base, "deviceTypeIdentifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-17"},
        EXPECTED_DEVICE_TYPE_IDENTIFIER,
    )
    assert not _simulator_matches_expected_device(
        {**base, "state": "Shutdown"}, EXPECTED_DEVICE_TYPE_IDENTIFIER
    )


def test_maily3_valid_reference_messages_pass_every_business_check():
    evaluator = Evaluator()
    booted_at = Evaluator._parse_required_datetime(DEFAULT_WINDOW_START, field="window_start")
    cutoff = datetime(2026, 10, 13, tzinfo=timezone.utc)
    rows_by_mailbox = {}
    next_uid = {}
    for index, spec in enumerate(MESSAGE_SPECS, 1):
        mailbox = spec["mailbox"]
        next_uid[mailbox] = next_uid.get(mailbox, 0) + 1
        rows_by_mailbox.setdefault(mailbox, []).append(
            _reference_row(spec, uid=next_uid[mailbox], index=index)
        )
    matched = {}
    for spec in MESSAGE_SPECS:
        check, parsed = evaluator._check_message(
            spec=spec,
            rows=rows_by_mailbox[spec["mailbox"]],
            booted_at=booted_at,
            evaluation_cutoff=cutoff,
        )
        assert check["pass"], check
        matched[spec["key"]] = parsed
    assert evaluator._check_business_order(matched)["pass"]


def test_maily3_wrong_attachment_bytes_fail_reference_message():
    evaluator = Evaluator()
    spec = next(spec for spec in MESSAGE_SPECS if spec["key"] == "field_fwd_forward")
    row = _reference_row(spec, uid=1, index=3, wrong_attachment=True)
    booted_at = Evaluator._parse_required_datetime(DEFAULT_WINDOW_START, field="window_start")
    check, _ = evaluator._check_message(
        spec=spec,
        rows=[row],
        booted_at=booted_at,
        evaluation_cutoff=datetime(2026, 10, 13, tzinfo=timezone.utc),
    )
    assert not check["pass"]
    assert "attachment_sha256" in check["failed_requirements"]


def test_maily3_ruleset_hash_binds_the_revised_device_identity_contract():
    import hashlib
    import json

    canonical = json.dumps(RULESET_SPEC, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert RULESET_SHA256 == hashlib.sha256(canonical).hexdigest()
    assert "expected_device_type_identifier" in RULESET_SPEC
