"""Evaluate Thunderbird email tasks on macOS using the deterministic bench profile."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_SCAN_SCRIPT = r'''
import email
import json
import mailbox
import os
import re
from email import policy
from pathlib import Path

params = json.loads(__PARAMS_JSON__)
profile_name = str(params.get("profile_name") or "benchprofile.default-release").strip() or "benchprofile.default-release"
profile_dir_override = str(params.get("profile_dir") or "").strip()
profile_dir = (
    Path(os.path.expanduser(profile_dir_override))
    if profile_dir_override
    else Path(os.path.expanduser(f"~/Library/Thunderbird/Profiles/{profile_name}"))
)
local_root = profile_dir / "Mail" / "Local Folders"
smtp_capture_dir = Path(os.path.expanduser(str(params.get("smtp_capture_dir") or "~/Library/Application Support/ThunderbirdBench/fake_smtp")))

result = {
    "status": "pass",
    "message": "Thunderbird email checks passed",
    "profile_dir": str(profile_dir),
    "local_root": str(local_root),
    "smtp_capture_dir": str(smtp_capture_dir),
    "mailboxes": {},
    "captured_messages": [],
}


def collect_mailbox(folder_name: str):
    path = local_root / folder_name
    messages = []
    if not path.exists():
        return path, messages
    try:
        mbox = mailbox.mbox(path, factory=lambda fp: email.message_from_binary_file(fp, policy=policy.default), create=False)
        for message in mbox:
            body = ""
            if message.is_multipart():
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body += part.get_content()
                        except Exception:
                            payload = part.get_payload(decode=True) or b""
                            body += payload.decode("utf-8", errors="ignore")
            else:
                try:
                    body = message.get_content()
                except Exception:
                    payload = message.get_payload(decode=True) or b""
                    body = payload.decode("utf-8", errors="ignore")
            messages.append({
                "subject": str(message.get("Subject") or "").strip(),
                "from": str(message.get("From") or "").strip(),
                "to": str(message.get("To") or "").strip(),
                "body": str(body or "").strip(),
                "x_mozilla_status": str(message.get("X-Mozilla-Status") or "").strip(),
                "message_id": str(message.get("Message-ID") or "").strip(),
            })
    except Exception as exc:
        result["status"] = "fail"
        result["message"] = f"Failed to parse mailbox {path}: {exc}"
    return path, messages


def _strip_quotes(value):
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1]
    return text


def parse_filter_blocks(raw_text: str):
    blocks = []
    current = None
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value)
        if key == "name":
            if current:
                blocks.append(current)
            current = {"name": value}
            continue
        if current is None:
            continue
        current[key] = value
    if current:
        blocks.append(current)
    return blocks


def required_fragment_present(rules_text: str, fragment: str) -> bool:
    if fragment in rules_text:
        return True
    if fragment.startswith('condition="OR (') and fragment.endswith(')"'):
        alternate = fragment.replace('condition="OR (', 'condition="AND (', 1)
        if alternate in rules_text:
            return True
    return False


def rule_matches(rule: dict, spec: dict):
    def normalize_expected_text(value):
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value or "").strip()

    def normalize_boolish(value):
        text = str(value or "").strip().lower()
        if text in {"yes", "true", "1", "on"}:
            return "yes"
        if text in {"no", "false", "0", "off"}:
            return "no"
        return text

    checks = {
        "name": normalize_expected_text(spec.get("name")),
        "enabled": normalize_expected_text(spec.get("enabled")),
        "action": normalize_expected_text(spec.get("action")),
        "condition": normalize_expected_text(spec.get("condition")),
        "actionValue": normalize_expected_text(spec.get("actionValue")),
    }
    for key, expected in checks.items():
        observed = str(rule.get(key) or "").strip()
        if key == "enabled":
            observed = normalize_boolish(observed)
            expected = normalize_boolish(expected)
        if expected and observed.lower() != expected.lower():
            return False

    condition_contains = str(spec.get("condition_contains") or "").strip().lower()
    if condition_contains and condition_contains not in str(rule.get("condition") or "").lower():
        return False

    action_value_contains = str(spec.get("action_value_contains") or "").strip().lower()
    if action_value_contains and action_value_contains not in str(rule.get("actionValue") or "").lower():
        return False

    return True


def normalize_body_for_match(body: str) -> str:
    text = str(body or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    meaningful_lines = [line for line in lines if line.strip()]
    return "\n".join(meaningful_lines).strip()


def body_matches(actual: str, expected: str) -> bool:
    actual_text = str(actual or "").strip()
    expected_text = str(expected or "").strip()
    return actual_text == expected_text or normalize_body_for_match(actual_text) == normalize_body_for_match(expected_text)


mode = str(params.get("mode") or "").strip()

if mode == "send_exact_body":
    if smtp_capture_dir.exists():
        for path in sorted(smtp_capture_dir.glob("*.eml")):
            try:
                msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
            except Exception:
                continue
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body += part.get_content()
                        except Exception:
                            payload = part.get_payload(decode=True) or b""
                            body += payload.decode("utf-8", errors="ignore")
            else:
                try:
                    body = msg.get_content()
                except Exception:
                    payload = msg.get_payload(decode=True) or b""
                    body = payload.decode("utf-8", errors="ignore")
            result["captured_messages"].append({
                "path": str(path),
                "subject": str(msg.get("Subject") or "").strip(),
                "to": str(msg.get("To") or "").strip(),
                "body": str(body or "").strip(),
            })
    expected_subject = str(params.get("expected_subject") or "").strip()
    expected_to = str(params.get("expected_to") or "").strip()
    expected_body = str(params.get("expected_body") or "").strip()
    matched = [
        item for item in result["captured_messages"]
        if item["subject"] == expected_subject
        and (not expected_to or expected_to in item["to"])
        and body_matches(item["body"], expected_body)
    ]
    sent_path, sent_messages = collect_mailbox(str(params.get("sent_mailbox") or "Sent"))
    result["mailboxes"][str(sent_path)] = sent_messages[:10]
    if not matched:
        result["status"] = "fail"
        result["message"] = "Expected SMTP-captured message not found"
    elif not any(msg["subject"] == expected_subject for msg in sent_messages):
        result["status"] = "fail"
        result["message"] = "Expected subject not found in Sent mailbox"

elif mode == "filter_rule":
    rules_path = local_root / str(params.get("rules_file") or "msgFilterRules.dat")
    rules_text = rules_path.read_text(encoding="utf-8", errors="ignore") if rules_path.exists() else ""
    result["rules_path"] = str(rules_path)
    result["rules_text_preview"] = rules_text[:1000]
    result["filter_rules"] = parse_filter_blocks(rules_text)
    required_contains = [str(item).strip() for item in params.get("required_contains") or [] if str(item).strip()]
    missing = [item for item in required_contains if not required_fragment_present(rules_text, item)]
    folder_must_exist = str(params.get("folder_must_exist") or "").strip()
    required_rule = dict(params.get("required_rule") or {})
    matched_rule = None
    if required_rule:
        for rule in result["filter_rules"]:
            if rule_matches(rule, required_rule):
                matched_rule = rule
                break
    result["matched_rule"] = matched_rule
    if missing:
        result["status"] = "fail"
        result["message"] = f"Missing filter rule fragments: {missing}"
    elif required_rule and matched_rule is None:
        result["status"] = "fail"
        result["message"] = "Required filter rule block not found"
    elif folder_must_exist and not (local_root / folder_must_exist).exists():
        result["status"] = "fail"
        result["message"] = f"Expected local folder missing: {folder_must_exist}"

elif mode == "send_multiple_exact_bodies":
    if smtp_capture_dir.exists():
        for path in sorted(smtp_capture_dir.glob("*.eml")):
            try:
                msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
            except Exception:
                continue
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body += part.get_content()
                        except Exception:
                            payload = part.get_payload(decode=True) or b""
                            body += payload.decode("utf-8", errors="ignore")
            else:
                try:
                    body = msg.get_content()
                except Exception:
                    payload = msg.get_payload(decode=True) or b""
                    body = payload.decode("utf-8", errors="ignore")
            result["captured_messages"].append({
                "path": str(path),
                "subject": str(msg.get("Subject") or "").strip(),
                "to": str(msg.get("To") or "").strip(),
                "body": str(body or "").strip(),
            })
    expected_to = str(params.get("expected_to") or "").strip()
    expected_messages = [
        {
            "subject": str(item.get("subject") or "").strip(),
            "body": str(item.get("body") or "").strip(),
        }
        for item in params.get("expected_messages") or []
        if isinstance(item, dict)
    ]
    expected_subject_order = [
        str(item).strip()
        for item in params.get("expected_subject_order") or []
        if str(item).strip()
    ]
    exact_captured_message_count = (
        int(params.get("exact_captured_message_count"))
        if params.get("exact_captured_message_count") is not None
        else None
    )
    exact_sent_message_count = (
        int(params.get("exact_sent_message_count"))
        if params.get("exact_sent_message_count") is not None
        else None
    )
    sent_path, sent_messages = collect_mailbox(str(params.get("sent_mailbox") or "Sent"))
    result["mailboxes"][str(sent_path)] = sent_messages[:20]
    captured_recipients = [
        item for item in result["captured_messages"]
        if not expected_to or expected_to in item["to"]
    ]
    sent_recipients = [
        item for item in sent_messages
        if not expected_to or expected_to in item["to"]
    ]
    missing_messages = []
    missing_sent_subjects = []
    for expected in expected_messages:
        matched = any(
            item["subject"] == expected["subject"]
            and (not expected_to or expected_to in item["to"])
            and body_matches(item["body"], expected["body"])
            for item in result["captured_messages"]
        )
        if not matched:
            missing_messages.append(expected["subject"])
        if not any(msg["subject"] == expected["subject"] for msg in sent_messages):
            missing_sent_subjects.append(expected["subject"])
    captured_subject_sequence = [item["subject"] for item in captured_recipients]
    sent_subject_sequence = [item["subject"] for item in sent_recipients]
    result["missing_expected_subjects"] = missing_messages
    result["missing_sent_subjects"] = missing_sent_subjects
    result["captured_subject_sequence"] = captured_subject_sequence
    result["sent_subject_sequence"] = sent_subject_sequence
    result["captured_message_count"] = len(captured_recipients)
    result["sent_message_count"] = len(sent_recipients)
    if missing_messages:
        result["status"] = "fail"
        result["message"] = f"Missing SMTP-captured messages: {missing_messages}"
    elif missing_sent_subjects:
        result["status"] = "fail"
        result["message"] = f"Missing Sent mailbox subjects: {missing_sent_subjects}"
    elif exact_captured_message_count is not None and len(captured_recipients) != exact_captured_message_count:
        result["status"] = "fail"
        result["message"] = (
            "Unexpected SMTP-captured message count: "
            f"expected {exact_captured_message_count}, observed {len(captured_recipients)}"
        )
    elif exact_sent_message_count is not None and len(sent_recipients) != exact_sent_message_count:
        result["status"] = "fail"
        result["message"] = (
            "Unexpected Sent mailbox message count: "
            f"expected {exact_sent_message_count}, observed {len(sent_recipients)}"
        )
    elif expected_subject_order and captured_subject_sequence != expected_subject_order:
        result["status"] = "fail"
        result["message"] = (
            "SMTP-captured subject order mismatch: "
            f"expected {expected_subject_order}, observed {captured_subject_sequence}"
        )
    elif expected_subject_order and sent_subject_sequence != expected_subject_order:
        result["status"] = "fail"
        result["message"] = (
            "Sent mailbox subject order mismatch: "
            f"expected {expected_subject_order}, observed {sent_subject_sequence}"
        )

elif mode == "mailbox_routing":
    checks = params.get("mailboxes") or {}
    mailbox_dump = {}
    for folder_name in sorted({str(name) for name in checks.keys()}):
        path, messages = collect_mailbox(folder_name)
        mailbox_dump[folder_name] = {
            "path": str(path),
            "subjects": [item["subject"] for item in messages],
            "messages": messages,
        }
    result["mailboxes"] = mailbox_dump
    failures = []
    for folder_name, expectations in checks.items():
        dump = mailbox_dump.get(folder_name, {})
        subjects = dump.get("subjects", [])
        must_have = [str(item).strip() for item in dict(expectations or {}).get("must_have_subjects") or [] if str(item).strip()]
        must_absent = [str(item).strip() for item in dict(expectations or {}).get("must_absent_subjects") or [] if str(item).strip()]
        for subject in must_have:
            if subject not in subjects:
                failures.append(f"{folder_name} missing subject: {subject}")
        for subject in must_absent:
            if subject in subjects:
                failures.append(f"{folder_name} still has forbidden subject: {subject}")
    if failures:
        result["status"] = "fail"
        result["message"] = "; ".join(failures)
else:
    result["status"] = "error"
    result["message"] = f"Unsupported Thunderbird email evaluation mode: {mode}"

print(json.dumps(result, ensure_ascii=False))
'''


class ThunderbirdEmailEvaluator(BaseEvaluator):
    """Guest-side evaluator for Thunderbird email tasks on macOS."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_python_script is required")

        mode = str(params.get("mode") or "").strip()
        if not mode:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation requires params.mode")

        script = dedent(_SCAN_SCRIPT).replace(
            "__PARAMS_JSON__",
            repr(json.dumps(params, ensure_ascii=False)),
        )
        try:
            result = controller.run_python_script(script, timeout=int(params.get("timeout", 60) or 60))
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Thunderbird email evaluation failed: {exc}")

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Thunderbird email evaluator returned non-JSON output",
                metadata={"runtime_result": result},
            )

        status_name = str(payload.get("status") or "").strip().lower()
        eval_status = EvalStatus.PASS if status_name == "pass" else EvalStatus.FAIL if status_name == "fail" else EvalStatus.ERROR
        return EvalResult(
            status=eval_status,
            message=str(payload.get("message") or "Thunderbird email evaluation completed"),
            metadata=payload,
        )
