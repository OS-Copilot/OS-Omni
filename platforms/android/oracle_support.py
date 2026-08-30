"""Deterministic Android oracle completion helpers.

The Android benchmark runner normally relies on an LLM to operate the UI.
For oracle baselines we keep the regular initializer path, then apply the
expected end state through privileged host / adb operations before the first
agent step. The oracle model itself can therefore be a trivial scripted
`success` action while evaluators still exercise the real benchmark truth.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import re
import shlex
import smtplib
import tempfile
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # Python 3.8 test environment fallback.
    class ZoneInfoNotFoundError(Exception):
        pass

    def ZoneInfo(_name: str) -> dt.tzinfo:
        return dt.timezone.utc

from initializers.android.email_office_cross_app import (
    DEFAULT_DOCUMENT_DIR,
    DEFAULT_MARKOR_DOCUMENT_DIR,
    _build_odt_bytes,
    _build_text_bytes,
)
from initializers.android.fossify_calendar import DEFAULT_DATABASE_PATH as CALENDAR_DB_PATH
from initializers.android.k9_seed_inbox_open import K9SeedInboxOpenInitializer
from platforms.android.bench_storage_support import (
    ensure_directory,
    push_bytes,
    push_text,
    remove_path,
    scan_media_paths,
)
from platforms.android.bootstrap import AndroidBootstrapDriver
from platforms.android.oinkoin_support import (
    DEFAULT_APP_ACTIVITY as OINKOIN_ACTIVITY,
    DEFAULT_APP_PACKAGE as OINKOIN_PACKAGE,
    default_database_path as oinkoin_default_database_path,
    ensure_adb_root as ensure_oinkoin_adb_root,
    seed_state_directly as seed_oinkoin_state_directly,
)
from platforms.android.openshop_support import OpenShopAndroidStore, coerce_cart_item_specs
from platforms.android.spotube_support import (
    DEFAULT_APP_ACTIVITY as SPOTUBE_ACTIVITY,
    DEFAULT_APP_PACKAGE as SPOTUBE_PACKAGE,
    apply_profile_state,
    apply_queue_state,
    apply_search_artist_state,
)

ANDROID_ORACLE_MODEL_IDS = {"android_oracle_wait", "android_oracle_agent"}

_TINY_JPEG = base64.b64decode(
    b"/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxAQEBAQEA8QDw8QDw8PDw8PDw8QDw8PFREWFhURFRUYHSggGBolGxUVITEhJSkrLi4uFx8zODMsNygtLisBCgoKDg0OGhAQGi0fHyUtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEAAQMBIgACEQEDEQH/xAAXAAEBAQEAAAAAAAAAAAAAAAAAAQID/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEAMQAAAB6A//xAAZEAEAAwEBAAAAAAAAAAAAAAABAAIREjH/2gAIAQEAAT8AqW3sQ2hP/8QAFBEBAAAAAAAAAAAAAAAAAAAAEP/aAAgBAgEBPwCf/8QAFBEBAAAAAAAAAAAAAAAAAAAAEP/aAAgBAwEBPwCf/9k="
)


@dataclass(frozen=True)
class OracleCompletionResult:
    handler: str
    details: dict[str, Any]


def is_android_oracle_model(model_id: str) -> bool:
    return str(model_id or "").strip() in ANDROID_ORACLE_MODEL_IDS


def apply_android_oracle_completion(
    *,
    task: Any,
    controller: Any,
    run_dir: Path,
    logger_obj: Any | None = None,
) -> dict[str, Any]:
    del run_dir
    evaluation = getattr(task, "evaluation", None)
    evaluator_id = str(getattr(evaluation, "evaluator_id", "") or "").strip()
    params = dict(getattr(evaluation, "params", {}) or {})
    init = getattr(task, "init", None)
    init_params = dict(getattr(init, "params", {}) or {})
    task_id = str(getattr(task, "id", "") or "").strip()

    if not evaluator_id:
        return {
            "handler": "noop",
            "task_id": task_id,
            "message": "Task has no evaluator; oracle completion skipped.",
        }

    def log(message: str, *args: Any) -> None:
        if logger_obj is not None:
            logger_obj.info(message, *args)

    log("Applying Android oracle completion for %s (%s)", task_id, evaluator_id)

    if evaluator_id == "evaluators.android.k9_send_email:K9SendEmailEvaluator":
        result = _complete_greenmail_send(params)
    elif evaluator_id == "evaluators.android.k9_simple_send_email_v2:K9SimpleSendEmailV2Evaluator":
        result = _complete_k9_simple_send(params)
    elif evaluator_id == "evaluators.android.k9_forward_email:K9ForwardMeetingNotesEvaluator":
        result = _complete_k9_forward_meeting_notes(params)
    elif evaluator_id == "evaluators.android.k9_forward_email:K9ForwardAlphaBetaReportsEvaluator":
        result = _complete_k9_forward_alpha_beta(params)
    elif evaluator_id == "evaluators.android.deltachat_send_message:DeltaChatSendMessageEvaluator":
        result = _complete_deltachat_send(params)
    elif evaluator_id == "evaluators.android.deltachat_archive_and_reply:DeltaChatArchiveAndReplyEvaluator":
        result = _complete_deltachat_archive_reply(params)
    elif evaluator_id == "evaluators.android.deltachat_create_contact_send_message:DeltaChatCreateContactSendMessageEvaluator":
        result = _complete_deltachat_send(params)
    elif evaluator_id == "evaluators.android.deltachat_forward_message:DeltaChatForwardMessageEvaluator":
        result = _complete_deltachat_forward(params)
    elif evaluator_id == "evaluators.android.deltachat_search_reply:DeltaChatSearchReplyEvaluator":
        result = _complete_deltachat_search_reply(params)
    elif evaluator_id == "evaluators.android.deltachat_set_status:DeltaChatSetStatusEvaluator":
        result = _complete_deltachat_status(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.calendar_map_deltachat:CalendarMapDeltaChatEvaluator":
        result = _complete_calendar_map_deltachat(params)
    elif evaluator_id == "evaluators.android.email_office_cross_app:EmailOfficeCrossAppEvaluator":
        result = _complete_email_office(controller=controller, params=params, init_params=init_params)
    elif evaluator_id == "evaluators.android.calendar_shopping_cross_app:CalendarShoppingCrossAppEvaluator":
        result = _complete_calendar_shopping(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.fossify_calendar:FossifyCalendarEventStateEvaluator":
        result = _complete_fossify_calendar(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.filesystem_state:ExternalStoragePathStateEvaluator":
        result = _complete_external_storage(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.markor_create_note:MarkorCreateNoteEvaluator":
        result = _complete_markor(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.openshop:OpenShopStateEvaluator":
        result = _complete_openshop(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.contacts_add_contact:ContactsAddContactEvaluator":
        result = _complete_contacts(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.calculator_addition:CalculatorAdditionEvaluator":
        result = _complete_calculator(controller=controller)
    elif evaluator_id == "evaluators.android.clock_stopwatch_running:ClockStopWatchRunningEvaluator":
        result = _complete_clock(controller=controller)
    elif evaluator_id == "evaluators.android.system_bluetooth_turn_on:SystemBluetoothTurnOnEvaluator":
        result = _complete_bluetooth(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.tasks_org:TasksOrgTaskWithNoteEvaluator":
        result = _complete_tasks_org_note(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.tasks_org:TasksOrgTaskWithDueDateEvaluator":
        result = _complete_tasks_org_due_date(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.tasks_org:TasksOrgTaskWithSubtasksEvaluator":
        result = _complete_tasks_org_subtasks(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.oinkoin_create_expense:OinkoinCreateExpenseEvaluator":
        result = _complete_oinkoin_create_expense(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.oinkoin_additional:OinkoinCreateIncomeEvaluator":
        result = _complete_oinkoin_create_income(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.oinkoin_additional:OinkoinEditExpenseEvaluator":
        result = _complete_oinkoin_edit_expense(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.oinkoin_additional:OinkoinDeleteExpenseEvaluator":
        result = _complete_oinkoin_delete_expense(controller=controller)
    elif evaluator_id == "evaluators.android.oinkoin_additional:OinkoinCreateCustomCategoryAndUseItEvaluator":
        result = _complete_oinkoin_custom_category(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.libreoffice_notes_append:LibreOfficeNotesAppendEvaluator":
        result = _complete_libreoffice_notes(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.libreoffice_status_report:LibreOfficeStatusReportEvaluator":
        result = _complete_libreoffice_status(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.libreoffice_viewer_mark:LibreOfficeViewerMarkEvaluator":
        result = _complete_libreoffice_viewer_mark(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.spotube_profile_setup:SpotubeProfileSetupEvaluator":
        result = _complete_spotube_profile(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.spotube_queue_naina_zara:SpotubeQueueNainaZaraEvaluator":
        result = _complete_spotube_queue(controller=controller, params=params)
    elif evaluator_id == "evaluators.android.spotube_search_artist_play_attempt:SpotubeSearchArtistPlayAttemptEvaluator":
        result = _complete_spotube_search_artist(controller=controller, params=params)
    else:
        raise NotImplementedError(f"Android oracle completion is not implemented for {evaluator_id}")

    log("Android oracle completion handler finished: %s", result.handler)
    return {
        "task_id": task_id,
        "evaluator_id": evaluator_id,
        "handler": result.handler,
        "details": result.details,
    }


def _complete_greenmail_send(params: Mapping[str, Any]) -> OracleCompletionResult:
    recipient = str(params.get("recipient_email") or "").strip()
    sender = str(params.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
    subject = str(params.get("subject") or "Oracle message").strip() or "Oracle message"
    body_lines_unordered = params.get("body_lines_unordered") or []
    if isinstance(body_lines_unordered, Sequence) and not isinstance(body_lines_unordered, (str, bytes)):
        body_lines = [str(line) for line in body_lines_unordered]
    else:
        body_lines = []
    body = "\n".join(body_lines) if body_lines else (str(params.get("body") or "oracle_message").strip() or "oracle_message")
    _send_greenmail_message(
        recipient_email=recipient,
        sender_email=sender,
        subject=subject,
        body=body,
    )
    return OracleCompletionResult(
        handler="greenmail_send",
        details={"recipient_email": recipient, "subject": subject, "body": body, "body_line_count": len(body_lines)},
    )


def _complete_k9_simple_send(params: Mapping[str, Any]) -> OracleCompletionResult:
    recipient = str(params.get("recipient_email") or "").strip()
    sender = str(params.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
    subject = str(params.get("subject") or "Oracle message").strip() or "Oracle message"
    body = str(params.get("expected_body") or "oracle_message").replace("\r\n", "\n")
    _send_greenmail_message(
        recipient_email=recipient,
        sender_email=sender,
        subject=subject,
        body=body,
    )
    return OracleCompletionResult(
        handler="k9_simple_send",
        details={"recipient_email": recipient, "subject": subject, "body": body},
    )


def _complete_k9_forward_meeting_notes(params: Mapping[str, Any]) -> OracleCompletionResult:
    recipient = str(params.get("recipient_email") or "").strip()
    sender = str(params.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
    prefix = str(params.get("required_prefix_line") or "Please review this.").strip()
    source_subject = str(params.get("source_subject_contains") or "Meeting Notes").strip()
    source_marker = str(params.get("source_body_marker") or "meeting_notes_unique_marker").strip()
    subject = f"Fwd: {source_subject}" if source_subject else "Fwd: Oracle"
    body = f"{prefix}\n\nForwarded from {source_subject}\n{source_marker}\n"
    _send_greenmail_message(recipient_email=recipient, sender_email=sender, subject=subject, body=body)
    return OracleCompletionResult(
        handler="k9_forward_meeting_notes",
        details={"recipient_email": recipient, "subject": subject, "body_prefix": prefix},
    )


def _complete_k9_forward_alpha_beta(params: Mapping[str, Any]) -> OracleCompletionResult:
    recipient = str(params.get("recipient_email") or "").strip()
    sender = str(params.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
    sent_subjects: list[str] = []
    for item in params.get("required_forwards") or []:
        if not isinstance(item, Mapping):
            continue
        source_subject = str(item.get("source_subject_contains") or "Oracle Report").strip() or "Oracle Report"
        subject = str(item.get("expected_subject_contains") or f"Combined Reports - {source_subject}").strip()
        prefix_lines = [str(line).strip() for line in (item.get("expected_prefix_lines") or []) if str(line).strip()]
        marker = str(item.get("source_body_marker") or source_subject).strip()
        body_lines = prefix_lines or [str(params.get("required_prefix_line") or "Combined Reports").strip()]
        body_lines.extend(["", f"Forwarded from {source_subject}", marker])
        _send_greenmail_message(
            recipient_email=recipient,
            sender_email=sender,
            subject=subject,
            body="\n".join(body_lines),
        )
        sent_subjects.append(subject)
    return OracleCompletionResult(
        handler="k9_forward_alpha_beta",
        details={"recipient_email": recipient, "subjects": sent_subjects},
    )


def _complete_deltachat_send(params: Mapping[str, Any]) -> OracleCompletionResult:
    recipient = str(params.get("recipient_email") or "").strip()
    sender = str(params.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
    body = str(params.get("body") or "oracle_deltachat_message").strip() or "oracle_deltachat_message"
    _send_greenmail_message(
        recipient_email=recipient,
        sender_email=sender,
        subject="Delta Chat oracle message",
        body=body,
        headers={"Chat-Version": "1.0"},
    )
    return OracleCompletionResult(
        handler="deltachat_send",
        details={"recipient_email": recipient, "body": body},
    )


def _complete_deltachat_archive_reply(params: Mapping[str, Any]) -> OracleCompletionResult:
    recipient = str(params.get("recipient_email") or "").strip()
    sender = str(params.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
    body = str(params.get("reply_body") or "archive_reply_oracle").strip() or "archive_reply_oracle"
    _send_greenmail_message(
        recipient_email=recipient,
        sender_email=sender,
        subject="Delta Chat archived reply",
        body=body,
        headers={"Chat-Version": "1.0"},
    )
    return OracleCompletionResult(
        handler="deltachat_archive_reply",
        details={"recipient_email": recipient, "body": body},
    )


def _complete_deltachat_forward(params: Mapping[str, Any]) -> OracleCompletionResult:
    recipient = str(params.get("target_recipient_email") or "").strip()
    sender = str(params.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
    body = str(params.get("forwarded_body") or "oracle_forward").strip() or "oracle_forward"
    _send_greenmail_message(
        recipient_email=recipient,
        sender_email=sender,
        subject="Delta Chat forwarded message",
        body=body,
        headers={"Chat-Version": "1.0"},
    )
    return OracleCompletionResult(
        handler="deltachat_forward",
        details={"recipient_email": recipient, "body": body},
    )


def _complete_deltachat_search_reply(params: Mapping[str, Any]) -> OracleCompletionResult:
    recipient = str(params.get("target_recipient_email") or "").strip()
    sender = str(params.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
    reply_body = str(params.get("reply_body") or "oracle_reply").strip() or "oracle_reply"
    original_body = str(params.get("original_body") or "oracle_original").strip()
    body = reply_body if not original_body else f"{reply_body}\n\n> {original_body}\n"
    _send_greenmail_message(
        recipient_email=recipient,
        sender_email=sender,
        subject="Delta Chat search reply",
        body=body,
        headers={"Chat-Version": "1.0"},
    )
    return OracleCompletionResult(
        handler="deltachat_search_reply",
        details={"recipient_email": recipient, "reply_body": reply_body, "original_body": original_body},
    )


def _complete_deltachat_status(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    app_package = str(params.get("app_package") or "chat.delta").strip() or "chat.delta"
    expected_status = str(params.get("expected_status") or "Benchmarking in progress").strip()
    accounts_dir = f"/data/data/{app_package}/files/accounts"
    ensure_directory(controller, accounts_dir)
    push_text(controller, f"{accounts_dir}/oracle_status.txt", expected_status + "\n")
    return OracleCompletionResult(
        handler="deltachat_status",
        details={"accounts_dir": accounts_dir, "expected_status": expected_status},
    )


def _complete_calendar_map_deltachat(params: Mapping[str, Any]) -> OracleCompletionResult:
    recipient = str(params.get("recipient_email") or "").strip()
    sender = str(params.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
    substrings = [str(item).strip() for item in (params.get("required_substrings") or []) if str(item).strip()]
    if not substrings:
        substrings = ["Oracle Cafe", "Oracle Street"]
    body = " ".join(substrings)
    _send_greenmail_message(
        recipient_email=recipient,
        sender_email=sender,
        subject="Delta Chat cafe result",
        body=body,
        headers={"Chat-Version": "1.0"},
    )
    return OracleCompletionResult(
        handler="calendar_map_deltachat",
        details={"recipient_email": recipient, "body": body},
    )


def _complete_email_office(*, controller: Any, params: Mapping[str, Any], init_params: Mapping[str, Any]) -> OracleCompletionResult:
    filename = str(params.get("filename") or init_params.get("filename") or "bench_cross_app.md").strip()
    document_format = str(params.get("document_format") or init_params.get("document_format") or "markdown").strip().lower()
    remote_dir = str(init_params.get("document_dir") or (
        DEFAULT_MARKOR_DOCUMENT_DIR if document_format in {"text", "markdown", "md"} else DEFAULT_DOCUMENT_DIR
    )).strip().rstrip("/")
    written_remote_path = ""
    if filename:
        required_texts = [
            str(item).strip() for item in (params.get("required_document_texts") or []) if str(item).strip()
        ]
        absent_texts = {
            str(item).strip() for item in (params.get("absent_document_texts") or []) if str(item).strip()
        }
        init_lines = [str(item).strip() for item in (init_params.get("document_lines") or []) if str(item).strip()]
        lines = [line for line in (required_texts or init_lines or ["HelloWorld oracle document"]) if line not in absent_texts]
        payload = (
            _build_text_bytes(lines)
            if document_format in {"text", "markdown", "md"}
            else _build_odt_bytes(lines, font_size_pt=init_params.get("font_size_pt", 24))
        )
        written_remote_path = f"{remote_dir}/{filename}"
        remove_path(controller, written_remote_path)
        push_bytes(controller, written_remote_path, payload)
        scan_media_paths(controller, [written_remote_path])

    expected_emails = params.get("expected_emails") or []
    sent_emails: list[dict[str, Any]] = []
    for item in expected_emails:
        if not isinstance(item, Mapping):
            continue
        recipient = str(item.get("recipient_email") or "").strip()
        sender = str(item.get("sender_email") or "benchsender@example.test").strip() or "benchsender@example.test"
        subject = str(item.get("subject") or "Oracle email").strip() or "Oracle email"
        body_lines = [str(value).strip() for value in (item.get("body_contains") or []) if str(value).strip()]
        body = "\n".join(body_lines or ["oracle email body"])
        _send_greenmail_message(recipient_email=recipient, sender_email=sender, subject=subject, body=body)
        sent_emails.append({"recipient_email": recipient, "subject": subject})

    return OracleCompletionResult(
        handler="email_office_cross_app",
        details={"remote_path": written_remote_path, "sent_emails": sent_emails},
    )


def _complete_calendar_shopping(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    calendar_params = params.get("calendar") if isinstance(params.get("calendar"), Mapping) else {}
    openshop_params = params.get("openshop") if isinstance(params.get("openshop"), Mapping) else {}
    calendar_result = _complete_fossify_calendar(controller=controller, params=calendar_params)
    openshop_result = _complete_openshop(controller=controller, params=openshop_params)
    return OracleCompletionResult(
        handler="calendar_shopping_cross_app",
        details={
            "calendar": calendar_result.details,
            "openshop": openshop_result.details,
        },
    )


def _complete_fossify_calendar(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    database_path = str(params.get("database_path") or CALENDAR_DB_PATH).strip() or CALENDAR_DB_PATH
    timezone_name = str(params.get("timezone") or "UTC").strip() or "UTC"
    expected_events = [dict(item) for item in (params.get("expected_events") or []) if isinstance(item, Mapping)]
    absent_titles = [str(item).strip() for item in (params.get("absent_titles") or []) if str(item).strip()]

    _calendar_execute_sql(controller, database_path=database_path, sql="DELETE FROM events WHERE title LIKE 'BMK %';")
    for title in absent_titles:
        _calendar_execute_sql(
            controller,
            database_path=database_path,
            sql=f"DELETE FROM events WHERE title={_sql_quote(title)};",
        )
    for event in expected_events:
        _insert_calendar_event(controller, database_path=database_path, event=event, timezone_name=timezone_name)

    return OracleCompletionResult(
        handler="fossify_calendar",
        details={"database_path": database_path, "expected_count": len(expected_events)},
    )


def _complete_external_storage(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    expected_paths = [dict(item) for item in (params.get("expected_paths") or []) if isinstance(item, Mapping)]
    forbidden_paths = [dict(item) for item in (params.get("forbidden_paths") or []) if isinstance(item, Mapping)]
    exact_dirs = [dict(item) for item in (params.get("exact_directory_entries") or []) if isinstance(item, Mapping)]

    for spec in exact_dirs:
        remote_dir = str(spec.get("path") or "").strip()
        if not remote_dir:
            continue
        remove_path(controller, remote_dir)
        ensure_directory(controller, remote_dir)

    dir_type_map: dict[str, str] = {}
    for spec in exact_dirs:
        remote_dir = str(spec.get("path") or "").strip()
        if remote_dir:
            dir_type_map[remote_dir] = "dir"
    for spec in expected_paths:
        remote_path = str(spec.get("path") or "").strip()
        if remote_path:
            dir_type_map[remote_path] = str(spec.get("type") or "any").strip().lower() or "any"

    created_paths: list[str] = []
    for spec in exact_dirs:
        remote_dir = str(spec.get("path") or "").strip()
        if not remote_dir:
            continue
        ensure_directory(controller, remote_dir)
        created_paths.append(remote_dir)
        for entry in spec.get("entries") or []:
            name = str(entry or "").strip()
            if not name:
                continue
            child_path = f"{remote_dir.rstrip('/')}/{name}"
            child_type = dir_type_map.get(child_path, "file")
            if child_type == "dir":
                ensure_directory(controller, child_path)
            else:
                _write_placeholder_file(controller, child_path)
            created_paths.append(child_path)

    for spec in expected_paths:
        remote_path = str(spec.get("path") or "").strip()
        if not remote_path or remote_path in created_paths:
            continue
        expected_type = str(spec.get("type") or "any").strip().lower() or "any"
        if expected_type == "dir":
            ensure_directory(controller, remote_path)
        else:
            _write_placeholder_file(controller, remote_path)
        created_paths.append(remote_path)

    for spec in forbidden_paths:
        remote_path = str(spec.get("path") or "").strip()
        if remote_path:
            remove_path(controller, remote_path)

    return OracleCompletionResult(
        handler="external_storage",
        details={"created_paths": created_paths, "forbidden_count": len(forbidden_paths)},
    )


def _complete_markor(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    file_name = str(params.get("file_name") or "hello.md").strip() or "hello.md"
    text = str(params.get("text") or "Hello, world!")
    remote_path = f"{DEFAULT_MARKOR_DOCUMENT_DIR}/{file_name}"
    push_text(controller, remote_path, text + ("\n" if not text.endswith("\n") else ""))
    scan_media_paths(controller, [remote_path])
    return OracleCompletionResult(
        handler="markor_note",
        details={"remote_path": remote_path, "text": text},
    )


def _complete_openshop(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    app_package = str(params.get("app_package") or "com.killt.openshop").strip() or "com.killt.openshop"
    store = OpenShopAndroidStore(controller, app_package=app_package)
    state = build_openshop_oracle_state(store.load_seed_payload(), params)
    store.write_state(state, reload_page=True)
    return OracleCompletionResult(
        handler="openshop_state",
        details={
            "app_package": app_package,
            "cart_size": len(state.get("cart") or []),
            "order_count": len(state.get("orders") or []),
            "session_logged_in": bool(state.get("session", {}).get("loggedIn")),
        },
    )


def build_openshop_oracle_state(seed_payload: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
    seed = copy.deepcopy(dict(seed_payload))
    benchmark_account = dict(seed.get("benchmarkAccount") or {})
    session_logged_in = bool(params.get("session_logged_in"))
    state: dict[str, Any] = {
        "session": {
            "loggedIn": session_logged_in,
            "user": (
                {
                    "name": str(benchmark_account.get("name") or "Oracle User"),
                    "phone": str(benchmark_account.get("phone") or "13800000000"),
                }
                if session_logged_in
                else None
            ),
        },
        "addresses": copy.deepcopy(seed.get("addresses") or []),
        "paymentMethods": copy.deepcopy(seed.get("paymentMethods") or []),
        "cart": [],
        "orders": [],
    }

    products = {
        str(item.get("id") or "").strip(): dict(item)
        for item in (seed.get("products") or [])
        if isinstance(item, Mapping)
    }
    cart_specs = coerce_cart_item_specs(params.get("present_cart_items"))
    for index, spec in enumerate(cart_specs, start=1):
        product = products.get(spec.product_id) or {}
        default_spec = _default_product_spec(product)
        state["cart"].append(
            {
                "id": f"oracle-cart-{index}",
                "productId": spec.product_id,
                "quantity": int(spec.quantity),
                "selectedSpec": spec.selected_spec or default_spec,
            }
        )

    latest_order_raw = params.get("latest_order") if isinstance(params.get("latest_order"), Mapping) else None
    if latest_order_raw is not None:
        latest_order = dict(latest_order_raw)
        addresses = {
            str(item.get("id") or "").strip(): dict(item)
            for item in state.get("addresses") or []
            if isinstance(item, Mapping)
        }
        payments = {
            str(item.get("id") or "").strip(): dict(item)
            for item in state.get("paymentMethods") or []
            if isinstance(item, Mapping)
        }
        order_items: list[dict[str, Any]] = []
        subtotal = 0.0
        for index, spec in enumerate(coerce_cart_item_specs(latest_order.get("items")), start=1):
            product = copy.deepcopy(products.get(spec.product_id) or {"id": spec.product_id, "title": spec.product_id, "price": 0, "specs": []})
            quantity = int(spec.quantity)
            subtotal += float(product.get("price") or 0) * quantity
            order_items.append(
                {
                    "id": f"oracle-order-item-{index}",
                    "quantity": quantity,
                    "selectedSpec": spec.selected_spec or _default_product_spec(product),
                    "product": product,
                }
            )
        shipping = 12 if order_items else 0
        discount = 30 if subtotal >= 300 else 0
        total = subtotal + shipping - discount
        order = {
            "id": f"TBORACLE{int(time.time() * 1000)}",
            "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "address": copy.deepcopy(addresses.get(str(latest_order.get("address_id") or "").strip()) or {}),
            "payment": copy.deepcopy(payments.get(str(latest_order.get("payment_method_id") or "").strip()) or {}),
            "note": str(latest_order.get("note") or "").strip(),
            "items": order_items,
            "total": total,
            "status": str(latest_order.get("status") or "Awaiting Shipment").strip() or "Awaiting Shipment",
        }
        state["orders"] = [order]

    return state


def _complete_contacts(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    name = str(params.get("name") or "John Smith").strip() or "John Smith"
    number = str(params.get("number") or "555-123-4567").strip() or "555-123-4567"
    first, last = _split_name(name)
    raw_insert = str(
        controller.execute_adb(
            [
                "shell",
                "content",
                "insert",
                "--uri",
                "content://com.android.contacts/raw_contacts",
                "--bind",
                "account_type:s:",
                "--bind",
                "account_name:s:",
            ]
        )
        or ""
    )
    raw_id = _extract_trailing_int(raw_insert)
    if raw_id is None:
        query_out = str(
            controller.execute_adb(
                [
                    "shell",
                    "content",
                    "query",
                    "--uri",
                    "content://com.android.contacts/raw_contacts",
                    "--projection",
                    "_id",
                ]
            )
            or ""
        )
        raw_id = _extract_last_named_int(query_out, "_id")
    if raw_id is None:
        raise RuntimeError(f"Failed to resolve inserted raw contact id: {raw_insert!r}")

    controller.execute_adb(
        [
            "shell",
            "content",
            "insert",
            "--uri",
            "content://com.android.contacts/data",
            "--bind",
            f"raw_contact_id:i:{raw_id}",
            "--bind",
            "mimetype:s:vnd.android.cursor.item/name",
            "--bind",
            f"data2:s:{first}",
            "--bind",
            f"data3:s:{last}",
        ]
    )
    controller.execute_adb(
        [
            "shell",
            "content",
            "insert",
            "--uri",
            "content://com.android.contacts/data",
            "--bind",
            f"raw_contact_id:i:{raw_id}",
            "--bind",
            "mimetype:s:vnd.android.cursor.item/phone_v2",
            "--bind",
            f"data1:s:{number}",
            "--bind",
            "data2:i:2",
        ]
    )
    return OracleCompletionResult(
        handler="contacts_insert",
        details={"name": name, "number": number, "raw_contact_id": raw_id},
    )


def _complete_bluetooth(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    expected_state = str(params.get("expected_state") or "on").strip().lower() or "on"
    if expected_state == "on":
        controller.execute_adb(["shell", "svc", "bluetooth", "enable"])
        controller.execute_adb(["shell", "cmd", "bluetooth_manager", "enable"])
        controller.execute_adb(["shell", "settings", "put", "global", "bluetooth_on", "1"])
    else:
        controller.execute_adb(["shell", "svc", "bluetooth", "disable"])
        controller.execute_adb(["shell", "cmd", "bluetooth_manager", "disable"])
        controller.execute_adb(["shell", "settings", "put", "global", "bluetooth_on", "0"])
    return OracleCompletionResult(
        handler="bluetooth_toggle",
        details={"expected_state": expected_state},
    )


def _complete_calculator(*, controller: Any) -> OracleCompletionResult:
    driver = AndroidBootstrapDriver(controller, settle_delay_seconds=0.25, poll_interval_seconds=0.3)
    for selectors in (
        [{"text": "AC"}, {"content_description": "clear"}, {"text": "Clear"}, {"content_description": "AC"}],
        [{"text": "C"}, {"content_description": "clear"}],
    ):
        driver.tap_if_present(selectors, timeout_seconds=0.8)
    _tap_token(driver, ["1"])
    _tap_token(driver, ["2"])
    _tap_token(driver, ["+", "plus", "add"])
    _tap_token(driver, ["3"])
    _tap_token(driver, ["4"])
    _tap_token(driver, ["=", "equals", "equal"])
    return OracleCompletionResult(handler="calculator_ui", details={"expression": "12+34"})


def _complete_clock(*, controller: Any) -> OracleCompletionResult:
    driver = AndroidBootstrapDriver(controller, settle_delay_seconds=0.3, poll_interval_seconds=0.3)
    stopwatch_selectors = [
        {"resource_id": "android:id/text1", "text": "STOPWATCH"},
        {"text": "Stopwatch"},
        {"content_description": "Stopwatch"},
        {"text_contains": "Stopwatch"},
    ]
    if not driver.tap_if_present(stopwatch_selectors, timeout_seconds=1.2):
        _tap_token(driver, ["Stopwatch", "stopwatch"])

    start_selectors = [
        {"resource_id": "com.android.deskclock:id/fab", "content_description": "Start"},
        {"content_description": "Start"},
        {"text": "Start"},
        {"text_contains": "Start"},
    ]
    for _attempt in range(4):
        start_node = driver.wait_for_node(start_selectors, timeout_seconds=1.2, raise_on_timeout=False)
        if start_node is None:
            break
        x, y = driver._tap_point_for_node(start_node)
        controller.tap(x, y)
        time.sleep(0.8)
        if _clock_timer_region_is_changing(controller):
            time.sleep(0.6)
            return OracleCompletionResult(handler="clock_stopwatch", details={"status": "running", "tap": {"x": x, "y": y}})
        if driver.tap_if_present([{"resource_id": "com.android.deskclock:id/fab"}], timeout_seconds=1.0):
            time.sleep(0.8)
            if _clock_timer_region_is_changing(controller):
                time.sleep(0.6)
                return OracleCompletionResult(handler="clock_stopwatch", details={"status": "running"})
        time.sleep(0.5)

    visible_nodes = driver.summarize_nodes(driver.observe_nodes(), limit=20)
    raise RuntimeError(f"Failed to start stopwatch via oracle. Visible nodes:\n{visible_nodes}")


def _clock_timer_region_is_changing(controller: Any) -> bool:
    width = int(getattr(controller, "width", 1080) or 1080)
    height = int(getattr(controller, "height", 2400) or 2400)
    y_start = max(1, int(height * 0.10))
    y_end = min(height, int(height * 0.78))
    bytes_per_row = width * 4
    skip_bytes = 12 + y_start * bytes_per_row
    crop_bytes = max((y_end - y_start) * bytes_per_row, bytes_per_row)
    raw1_bin = "/data/local/tmp/_oracle_sw_raw1.bin"
    raw2_bin = "/data/local/tmp/_oracle_sw_raw2.bin"

    controller.execute_adb(["shell", "screencap", raw1_bin])
    time.sleep(1.1)
    controller.execute_adb(["shell", "screencap", raw2_bin])
    hash_output = str(
        controller.execute_adb(
            [
                "shell",
                (
                    f"dd if={raw1_bin} bs=1 skip={skip_bytes} count={crop_bytes} 2>/dev/null | md5sum && "
                    f"dd if={raw2_bin} bs=1 skip={skip_bytes} count={crop_bytes} 2>/dev/null | md5sum"
                ),
            ]
        )
        or ""
    )
    controller.execute_adb(["shell", "rm", "-f", raw1_bin, raw2_bin])
    lines = [line.strip() for line in hash_output.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    hash1 = lines[0].split()[0] if lines[0] else ""
    hash2 = lines[1].split()[0] if lines[1] else ""
    return bool(hash1 and hash2 and hash1 != hash2)


def _complete_tasks_org_note(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    title = str(params.get("title") or "Call landlord").strip()
    note = str(params.get("note") or "bench_tasks_note").strip()
    preserved = [
        dict(item)
        for item in (params.get("preserved_top_level_tasks") or [])
        if isinstance(item, Mapping) and str(item.get("title") or "").strip()
    ]
    if preserved:
        sql = _tasks_org_sql_top_level_specs(
            controller,
            [
                {
                    "title": title,
                    "note": note,
                    "due_ms": 0,
                    "order_index": 1,
                    "completed": 0,
                },
                *preserved,
            ],
        )
    else:
        sql = _tasks_org_sql_single(title=title, note=note, due_ms=0)
    _tasks_org_execute_sql(controller, sql)
    return OracleCompletionResult(
        handler="tasks_org_note",
        details={"title": title, "note": note, "preserved_count": len(preserved)},
    )


def _complete_tasks_org_due_date(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    title = str(params.get("title") or "Prepare slides").strip()
    note = str(params.get("note") or "bench_prepare_slides_note").strip()
    due_ms = _tasks_org_due_ms(controller, int(params.get("due_day_offset", 1) or 1))
    preserved = [
        dict(item)
        for item in (params.get("preserved_top_level_tasks") or [])
        if isinstance(item, Mapping) and str(item.get("title") or "").strip()
    ]
    if preserved:
        sql = _tasks_org_sql_top_level_specs(
            controller,
            [
                {
                    "title": title,
                    "note": note,
                    "due_ms": due_ms,
                    "order_index": 1,
                    "completed": 0,
                },
                *preserved,
            ],
        )
    else:
        sql = _tasks_org_sql_single(title=title, note=note, due_ms=due_ms)
    _tasks_org_execute_sql(controller, sql)
    return OracleCompletionResult(handler="tasks_org_due_date", details={"title": title, "note": note, "due_ms": due_ms})


def _complete_tasks_org_subtasks(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    parent_title = str(params.get("parent_title") or "Weekend errands").strip()
    parent_note = str(params.get("parent_note") or "bench_weekend_errands_note").strip()
    subtasks = [str(item).strip() for item in (params.get("subtasks") or []) if str(item).strip()]
    due_ms = _tasks_org_due_ms(controller, int(params.get("due_day_offset", 1) or 1))
    preserved = [
        dict(item)
        for item in (params.get("preserved_top_level_tasks") or [])
        if isinstance(item, Mapping) and str(item.get("title") or "").strip()
    ]
    if preserved:
        sql = _tasks_org_sql_with_subtasks_and_preserved(
            controller,
            parent_title=parent_title,
            parent_note=parent_note,
            due_ms=due_ms,
            subtasks=subtasks,
            preserved=preserved,
        )
    else:
        sql = _tasks_org_sql_with_subtasks(parent_title=parent_title, parent_note=parent_note, due_ms=due_ms, subtasks=subtasks)
    _tasks_org_execute_sql(controller, sql)
    return OracleCompletionResult(
        handler="tasks_org_subtasks",
        details={"parent_title": parent_title, "parent_note": parent_note, "subtasks": subtasks, "due_ms": due_ms},
    )


def _complete_oinkoin_create_expense(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    result = _oinkoin_apply_single_record(
        controller,
        app_package=str(params.get("app_package") or OINKOIN_PACKAGE).strip() or OINKOIN_PACKAGE,
        title=str(params.get("title") or "Coffee").strip(),
        note=str(params.get("note") or "bench_expense_note").strip(),
        category_name=str(params.get("category_name") or "Food").strip(),
        amount=float(params.get("amount") or 0.0),
        category_type=int(params.get("category_type", 0) or 0),
    )
    return OracleCompletionResult(handler="oinkoin_create_expense", details=result)


def _complete_oinkoin_create_income(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    result = _oinkoin_apply_single_record(
        controller,
        app_package=str(params.get("app_package") or OINKOIN_PACKAGE).strip() or OINKOIN_PACKAGE,
        title=str(params.get("title") or "Payday").strip(),
        note=str(params.get("note") or "bench_income_note").strip(),
        category_name=str(params.get("category_name") or "Salary").strip(),
        amount=float(params.get("amount") or 0.0),
        category_type=int(params.get("category_type", 1) or 1),
    )
    return OracleCompletionResult(handler="oinkoin_create_income", details=result)


def _complete_oinkoin_edit_expense(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    result = _oinkoin_apply_single_record(
        controller,
        app_package=str(params.get("app_package") or OINKOIN_PACKAGE).strip() or OINKOIN_PACKAGE,
        title=str(params.get("new_title") or "Coffee Beans").strip(),
        note=str(params.get("new_note") or "bench_edit_note").strip(),
        category_name=str(params.get("category_name") or "Food").strip(),
        amount=float(params.get("new_amount") or 0.0),
        category_type=int(params.get("category_type", 0) or 0),
    )
    return OracleCompletionResult(handler="oinkoin_edit_expense", details=result)


def _complete_oinkoin_delete_expense(*, controller: Any) -> OracleCompletionResult:
    app_package = OINKOIN_PACKAGE
    database_path = oinkoin_default_database_path(app_package)
    ensure_oinkoin_adb_root(controller)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    _sqlite_execute(controller, database_path=database_path, sql="DELETE FROM records; DELETE FROM categories;")
    controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{OINKOIN_ACTIVITY}"])
    time.sleep(1.0)
    return OracleCompletionResult(handler="oinkoin_delete_expense", details={"database_path": database_path})


def _complete_oinkoin_custom_category(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    expected_records = [
        dict(item)
        for item in (params.get("expected_records") or [])
        if isinstance(item, Mapping) and str(item.get("title") or "").strip()
    ]
    if expected_records:
        app_package = str(params.get("app_package") or OINKOIN_PACKAGE).strip() or OINKOIN_PACKAGE
        final_category = str(params.get("category_name") or "BenchCafe").strip() or "BenchCafe"
        category_type = int(params.get("category_type", 0) or 0)
        category_names = {
            str(item).strip()
            for item in (params.get("expected_category_names") or [])
            if str(item).strip()
        }
        category_names.add(final_category)
        categories = [
            {"name": name, "category_type": category_type, "color": "blue", "sort_order": index}
            for index, name in enumerate(sorted(category_names), start=1)
        ]
        result = seed_oinkoin_state_directly(
            controller,
            app_package=app_package,
            categories=categories,
            records=expected_records,
        )
        return OracleCompletionResult(handler="oinkoin_custom_category", details=result)

    result = _oinkoin_apply_single_record(
        controller,
        app_package=str(params.get("app_package") or OINKOIN_PACKAGE).strip() or OINKOIN_PACKAGE,
        title=str(params.get("final_title") or "Special Coffee Beans").strip(),
        note=str(params.get("final_note") or "bench_custom_category_note").strip(),
        category_name=str(params.get("category_name") or "BenchCafe").strip(),
        amount=float(params.get("final_amount") or 0.0),
        category_type=int(params.get("category_type", 0) or 0),
    )
    return OracleCompletionResult(handler="oinkoin_custom_category", details=result)


def _complete_libreoffice_notes(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    filename = str(params.get("expected_filename") or "notes.odt").strip() or "notes.odt"
    lines = [str(item).strip() for item in (params.get("required_lines") or []) if str(item).strip()] or [
        "Task A completed",
        "Task B completed",
        "Task C completed",
    ]
    remote_path = f"{DEFAULT_DOCUMENT_DIR}/{filename}"
    push_bytes(controller, remote_path, _build_odt_bytes(lines, font_size_pt=24))
    scan_media_paths(controller, [remote_path])
    return OracleCompletionResult(handler="libreoffice_notes", details={"remote_path": remote_path, "lines": lines})


def _complete_libreoffice_status(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    filename = str(params.get("expected_filename") or "status_report.odt").strip() or "status_report.odt"
    new_text = str(params.get("new_text") or "Status: Completed").strip() or "Status: Completed"
    remote_path = f"{DEFAULT_DOCUMENT_DIR}/{filename}"
    push_bytes(controller, remote_path, _build_odt_bytes([new_text], font_size_pt=24))
    scan_media_paths(controller, [remote_path])
    return OracleCompletionResult(handler="libreoffice_status", details={"remote_path": remote_path, "new_text": new_text})


def _complete_libreoffice_viewer_mark(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    filename = str(params.get("expected_filename") or "bench_read_by_viewer.odt").strip() or "bench_read_by_viewer.odt"
    marker = str(params.get("expected_marker") or "READ_BY_VIEWER").strip() or "READ_BY_VIEWER"
    remote_path = f"{DEFAULT_DOCUMENT_DIR}/{filename}"
    push_bytes(controller, remote_path, _build_odt_bytes([marker], font_size_pt=24))
    scan_media_paths(controller, [remote_path])
    return OracleCompletionResult(handler="libreoffice_viewer_mark", details={"remote_path": remote_path, "marker": marker})


def _complete_spotube_profile(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    app_package = str(params.get("app_package") or SPOTUBE_PACKAGE).strip() or SPOTUBE_PACKAGE
    result = apply_profile_state(
        controller,
        app_package=app_package,
        app_activity=SPOTUBE_ACTIVITY,
        language_code="en",
        market="AT",
        theme_mode="light",
        accent_color_scheme="rose:0xfff43f5e",
        normalize_audio=True,
        audio_source_plugin_name=str(params.get("expected_audio_source") or "Jiosaavn Audio").strip() or "Jiosaavn Audio",
    )
    _spotube_open_token(controller, tokens=["settings", "profile", "settings and preferences"])
    return OracleCompletionResult(handler="spotube_profile", details={"app_package": app_package, **result})


def _complete_spotube_queue(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    app_package = str(params.get("app_package") or SPOTUBE_PACKAGE).strip() or SPOTUBE_PACKAGE
    primary = str(params.get("primary_track_query") or "Naina").strip() or "Naina"
    queued = str(params.get("queued_track_query") or "Zara Zara").strip() or "Zara Zara"
    track_names = [
        str(item).strip()
        for item in (params.get("required_track_queries") or [])
        if str(item).strip()
    ] or [primary, queued]
    profile_result: dict[str, Any] = {}
    if any(key in params for key in ("expected_language_code", "expected_market", "expected_audio_source")):
        profile_result = apply_profile_state(
            controller,
            app_package=app_package,
            app_activity=SPOTUBE_ACTIVITY,
            language_code=str(params.get("expected_language_code") or "en").strip() or "en",
            market=str(params.get("expected_market") or "AT").strip() or "AT",
            audio_source_plugin_name=str(params.get("expected_audio_source") or "Jiosaavn Audio").strip() or "Jiosaavn Audio",
        )
    result = apply_queue_state(
        controller,
        app_package=app_package,
        app_activity=SPOTUBE_ACTIVITY,
        primary_track_name=primary,
        queued_track_name=queued,
        track_names=track_names,
    )
    _spotube_open_token(controller, tokens=["queue"])
    return OracleCompletionResult(handler="spotube_queue", details={"app_package": app_package, **profile_result, **result})


def _complete_spotube_search_artist(*, controller: Any, params: Mapping[str, Any]) -> OracleCompletionResult:
    app_package = str(params.get("app_package") or SPOTUBE_PACKAGE).strip() or SPOTUBE_PACKAGE
    artist_name = str(params.get("artist_name") or "Taylor Swift").strip() or "Taylor Swift"
    result = apply_search_artist_state(
        controller,
        app_package=app_package,
        app_activity=SPOTUBE_ACTIVITY,
        artist_name=artist_name,
    )
    driver = AndroidBootstrapDriver(controller, settle_delay_seconds=0.35, poll_interval_seconds=0.35)
    try:
        driver.tap_if_present([{"text_contains": "Search"}, {"content_description": "Search"}], timeout_seconds=1.0)
        if driver.tap_if_present([{"class_name": "android.widget.EditText"}], timeout_seconds=1.0):
            controller.input_text(artist_name)
            time.sleep(0.8)
        driver.tap_if_present([{"text_contains": artist_name}, {"content_description": artist_name}], timeout_seconds=1.2)
        driver.tap_if_present([{"text_contains": artist_name.split()[0]}, {"content_description": artist_name.split()[0]}], timeout_seconds=1.0)
    except Exception:
        pass
    return OracleCompletionResult(handler="spotube_search_artist", details={"app_package": app_package, **result, "artist_name": artist_name})


def _send_greenmail_message(
    *,
    recipient_email: str,
    sender_email: str,
    subject: str,
    body: str,
    smtp_host: str = "127.0.0.1",
    smtp_port: int = 3025,
    sender_password: str = "benchpass",
    headers: Mapping[str, str] | None = None,
) -> None:
    K9SeedInboxOpenInitializer._ensure_greenmail_ready("http://127.0.0.1:8081")
    message = EmailMessage()
    message["From"] = sender_email
    message["To"] = recipient_email
    message["Subject"] = subject
    for key, value in (headers or {}).items():
        if str(key).strip() and str(value).strip():
            message[str(key).strip()] = str(value).strip()
    message.set_content(body)
    with smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=10.0) as client:
        try:
            client.login(sender_email, sender_password)
        except smtplib.SMTPException:
            pass
        client.send_message(message)


def _calendar_execute_sql(controller: Any, *, database_path: str, sql: str) -> str:
    return _sqlite_execute(controller, database_path=database_path, sql=sql)


def _insert_calendar_event(controller: Any, *, database_path: str, event: Mapping[str, Any], timezone_name: str) -> None:
    title = str(event.get("title") or "").strip()
    if not title:
        raise RuntimeError(f"Calendar oracle event requires title: {event!r}")
    expected_type = int(event.get("type", 0) or 0)
    start_raw = str(event.get("start") or "").strip()
    end_raw = str(event.get("end") or "").strip()
    date_raw = str(event.get("date") or "").strip()
    if date_raw and not start_raw:
        start_dt = dt.datetime.fromisoformat(f"{date_raw}T00:00:00")
        end_dt = start_dt + dt.timedelta(hours=1)
        start_raw = start_dt.isoformat()
        end_raw = end_dt.isoformat()
    if not start_raw:
        raise RuntimeError(f"Calendar oracle event requires start or date: {event!r}")
    if not end_raw:
        parsed_start = dt.datetime.fromisoformat(start_raw)
        end_raw = (parsed_start + dt.timedelta(hours=1)).isoformat()

    now_ms = int(time.time() * 1000)
    start_ts = _datetime_to_seconds(start_raw, timezone_name)
    end_ts = _datetime_to_seconds(end_raw, timezone_name)
    columns = (
        "start_ts,end_ts,title,location,description,reminder_1_minutes,"
        "reminder_2_minutes,reminder_3_minutes,reminder_1_type,reminder_2_type,"
        "reminder_3_type,repeat_interval,repeat_rule,repeat_limit,repetition_exceptions,"
        "attendees,import_id,time_zone,flags,event_type,parent_id,last_updated,source,"
        "availability,access_level,color,type,status"
    )
    values = [
        str(start_ts),
        str(end_ts),
        _sql_quote(title),
        _sql_quote(str(event.get("location") or "").strip()),
        _sql_quote(str(event.get("description") or "").strip()),
        "10",
        "-1",
        "-1",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        _sql_quote("[]"),
        _sql_quote("[]"),
        _sql_quote(f"oracle-{int(time.time() * 1000)}-{title}"),
        _sql_quote(timezone_name),
        "0",
        "1",
        "0",
        str(now_ms),
        _sql_quote("simple-calendar"),
        "0",
        "0",
        "0",
        str(expected_type),
        "1",
    ]
    _calendar_execute_sql(
        controller,
        database_path=database_path,
        sql=f"INSERT INTO events ({columns}) VALUES ({','.join(values)});",
    )


def _tasks_org_execute_sql(controller: Any, sql: str) -> None:
    _sqlite_execute(controller, database_path="/data/user/0/org.tasks/databases/database", sql=sql)
    controller.execute_adb(["shell", "am", "force-stop", "org.tasks"])
    controller.execute_adb(["shell", "am", "start", "-n", "org.tasks/com.todoroo.astrid.activity.TaskListActivity"])
    time.sleep(1.0)


def _tasks_org_sql_single(*, title: str, note: str, due_ms: int) -> str:
    created_ms = int(time.time() * 1000)
    values = _tasks_org_values_sql(
        title=title,
        note=note,
        due_ms=due_ms,
        parent=0,
        order_index=1,
        created_ms=created_ms,
    )
    return (
        "DELETE FROM tasks;"
        "DELETE FROM sqlite_sequence WHERE name='tasks';"
        f"INSERT INTO tasks ({_TASKS_ORG_COLUMNS_SQL}) VALUES ({values});"
    )


def _tasks_org_sql_with_subtasks(*, parent_title: str, parent_note: str, due_ms: int, subtasks: Sequence[str]) -> str:
    created_ms = int(time.time() * 1000)
    statements = [
        "DELETE FROM tasks;",
        "DELETE FROM sqlite_sequence WHERE name='tasks';",
        f"INSERT INTO tasks ({_TASKS_ORG_COLUMNS_SQL}) VALUES ({_tasks_org_values_sql(title=parent_title, note=parent_note, due_ms=due_ms, parent=0, order_index=1, created_ms=created_ms)});",
    ]
    for index, subtask in enumerate(subtasks, start=1):
        statements.append(
            f"INSERT INTO tasks ({_TASKS_ORG_COLUMNS_SQL}) VALUES ({_tasks_org_values_sql(title=subtask, note='', due_ms=0, parent=1, order_index=index, created_ms=created_ms + index)});"
        )
    return "".join(statements)


def _tasks_org_sql_top_level_specs(controller: Any, specs: Sequence[Mapping[str, Any]]) -> str:
    created_ms = int(time.time() * 1000)
    statements = [
        "DELETE FROM tasks;",
        "DELETE FROM sqlite_sequence WHERE name='tasks';",
    ]
    for index, spec in enumerate(specs, start=1):
        due_ms = int(spec.get("due_ms", 0) or 0)
        if "due_day_offset" in spec and spec.get("due_day_offset") not in (None, ""):
            due_ms = _tasks_org_due_ms(controller, int(spec.get("due_day_offset") or 0))
        statements.append(
            f"INSERT INTO tasks ({_TASKS_ORG_COLUMNS_SQL}) VALUES "
            f"({_tasks_org_values_sql(title=str(spec.get('title') or '').strip(), note=str(spec.get('note') or '').strip(), due_ms=due_ms, parent=0, order_index=int(spec.get('order_index', index) or index), created_ms=created_ms + index, completed=int(spec.get('completed', 0) or 0), importance=int(spec.get('importance', 0) or 0))});"
        )
    return "".join(statements)


def _tasks_org_sql_with_subtasks_and_preserved(
    controller: Any,
    *,
    parent_title: str,
    parent_note: str,
    due_ms: int,
    subtasks: Sequence[str],
    preserved: Sequence[Mapping[str, Any]],
) -> str:
    created_ms = int(time.time() * 1000)
    statements = [
        "DELETE FROM tasks;",
        "DELETE FROM sqlite_sequence WHERE name='tasks';",
    ]
    for index, spec in enumerate(preserved, start=1):
        spec_due_ms = 0
        if "due_day_offset" in spec and spec.get("due_day_offset") not in (None, ""):
            spec_due_ms = _tasks_org_due_ms(controller, int(spec.get("due_day_offset") or 0))
        statements.append(
            f"INSERT INTO tasks ({_TASKS_ORG_COLUMNS_SQL}) VALUES "
            f"({_tasks_org_values_sql(title=str(spec.get('title') or '').strip(), note=str(spec.get('note') or '').strip(), due_ms=spec_due_ms, parent=0, order_index=int(spec.get('order_index', index) or index), created_ms=created_ms + index, completed=int(spec.get('completed', 0) or 0), importance=int(spec.get('importance', 0) or 0))});"
        )
    parent_id = len(preserved) + 1
    statements.append(
        f"INSERT INTO tasks ({_TASKS_ORG_COLUMNS_SQL}) VALUES "
        f"({_tasks_org_values_sql(title=parent_title, note=parent_note, due_ms=due_ms, parent=0, order_index=parent_id, created_ms=created_ms + parent_id)});"
    )
    for index, subtask in enumerate(subtasks, start=1):
        statements.append(
            f"INSERT INTO tasks ({_TASKS_ORG_COLUMNS_SQL}) VALUES "
            f"({_tasks_org_values_sql(title=subtask, note='', due_ms=0, parent=parent_id, order_index=index, created_ms=created_ms + parent_id + index)});"
        )
    return "".join(statements)


_TASKS_ORG_COLUMNS_SQL = (
    "title,importance,dueDate,hideUntil,created,modified,completed,deleted,"
    "notes,estimatedSeconds,elapsedSeconds,timerStart,notificationFlags,lastNotified,"
    "recurrence,repeat_from,calendarUri,remoteId,collapsed,parent,\"order\",read_only"
)


def _tasks_org_values_sql(
    *,
    title: str,
    note: str,
    due_ms: int,
    parent: int,
    order_index: int,
    created_ms: int,
    completed: int = 0,
    importance: int = 0,
) -> str:
    return ",".join(
        [
            _sql_quote(title),
            str(int(importance)),
            str(int(due_ms)),
            "0",
            str(created_ms),
            str(created_ms),
            str(int(completed)),
            "0",
            _sql_quote(note),
            "0",
            "0",
            "0",
            "0",
            "0",
            "NULL",
            "0",
            "NULL",
            "NULL",
            "0",
            str(parent),
            str(order_index),
            "0",
        ]
    )


def _tasks_org_due_ms(controller: Any, offset_days: int) -> int:
    device_now = _device_now(controller)
    expected_day = (device_now + dt.timedelta(days=offset_days)).date()
    due_dt = dt.datetime.combine(expected_day, dt.time(hour=9, minute=0), tzinfo=device_now.tzinfo)
    return int(due_dt.timestamp() * 1000)


def _oinkoin_apply_single_record(
    controller: Any,
    *,
    app_package: str,
    title: str,
    note: str,
    category_name: str,
    amount: float,
    category_type: int,
) -> dict[str, Any]:
    database_path = oinkoin_default_database_path(app_package)
    ensure_oinkoin_adb_root(controller)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    signed_value = abs(float(amount)) if int(category_type) == 1 else -abs(float(amount))
    now_ms = int(time.time() * 1000)
    sql = f"""
INSERT INTO profiles (name, is_default, color)
SELECT 'Default Profile', 1, NULL
WHERE NOT EXISTS (SELECT 1 FROM profiles);
UPDATE profiles
SET is_default = CASE
    WHEN id = COALESCE(
        (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1),
        (SELECT id FROM profiles ORDER BY id LIMIT 1)
    )
    THEN 1 ELSE 0
END;
INSERT INTO wallets (
    name, color, icon, icon_emoji, initial_amount, is_archived, is_default,
    is_predefined, sort_order, currency, profile_id
)
SELECT
    'Default Wallet', NULL, NULL, NULL, 0, 0, 1, 0, 0, NULL,
    (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM wallets);
UPDATE wallets
SET
    is_default = CASE
        WHEN id = COALESCE(
            (SELECT id FROM wallets WHERE is_default = 1 ORDER BY id LIMIT 1),
            (SELECT id FROM wallets ORDER BY id LIMIT 1)
        )
        THEN 1 ELSE 0
    END,
    profile_id = COALESCE(
        profile_id,
        (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1)
    );
DELETE FROM records;
DELETE FROM categories;
INSERT INTO categories (
    name, color, icon, category_type, last_used, record_count, is_archived, sort_order, icon_emoji
) VALUES (
    {_sql_quote(category_name)}, 'blue', 0, {int(category_type)}, 0, 0, 0, 0, NULL
);
INSERT INTO records (
    datetime, timezone, value, title, description, category_name, category_type,
    recurrence_id, wallet_id, transfer_wallet_id, transfer_value, profile_id
) VALUES (
    {now_ms}, 'Asia/Shanghai', {signed_value:.2f}, {_sql_quote(title)}, {_sql_quote(note)},
    {_sql_quote(category_name)}, {int(category_type)}, NULL,
    (SELECT id FROM wallets WHERE is_default = 1 ORDER BY id LIMIT 1),
    NULL, NULL,
    (SELECT id FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1)
);
UPDATE categories
SET record_count = (
    SELECT COUNT(*)
    FROM records
    WHERE records.category_name = categories.name
      AND records.category_type = categories.category_type
)
WHERE name = {_sql_quote(category_name)} AND category_type = {int(category_type)};
"""
    _sqlite_execute(controller, database_path=database_path, sql=sql)
    controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{OINKOIN_ACTIVITY}"])
    time.sleep(1.0)
    return {
        "app_package": app_package,
        "database_path": database_path,
        "title": title,
        "note": note,
        "category_name": category_name,
        "value": signed_value,
        "category_type": int(category_type),
    }


def _sqlite_execute(controller: Any, *, database_path: str, sql: str) -> str:
    encoded_sql = base64.b64encode(sql.encode("utf-8")).decode("ascii")
    command = f"printf %s {encoded_sql} | base64 -d | sqlite3 {shlex.quote(database_path)}"
    return str(controller.execute_adb(["shell", command]) or "")


def _write_placeholder_file(controller: Any, remote_path: str) -> None:
    payload = _TINY_JPEG if remote_path.lower().endswith((".jpg", ".jpeg")) else b"oracle\n"
    push_bytes(controller, remote_path, payload)


def _tap_token(driver: AndroidBootstrapDriver, tokens: Sequence[str]) -> None:
    selectors: list[dict[str, Any]] = []
    for token in tokens:
        text = str(token).strip()
        if not text:
            continue
        selectors.extend(
            [
                {"text": text},
                {"content_description": text},
                {"text_contains": text},
            ]
        )
    driver.tap_selector(selectors, timeout_seconds=8.0)


def _spotube_open_token(controller: Any, *, tokens: Sequence[str]) -> bool:
    driver = AndroidBootstrapDriver(controller, settle_delay_seconds=0.35, poll_interval_seconds=0.35)
    selectors: list[dict[str, Any]] = []
    for token in tokens:
        text = str(token).strip()
        if not text:
            continue
        selectors.extend([
            {"text": text},
            {"content_description": text},
            {"text_contains": text},
        ])
    if driver.tap_if_present(selectors, timeout_seconds=1.0):
        return True
    try:
        _tap_token(driver, tokens)
        return True
    except Exception:
        return False


def _default_product_spec(product: Mapping[str, Any]) -> str:
    specs = product.get("specs") if isinstance(product.get("specs"), list) else []
    return str(specs[0]).strip() if specs else ""


def _split_name(name: str) -> tuple[str, str]:
    parts = [part for part in name.split() if part]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    if parts:
        return parts[0], parts[0]
    return "John", "Smith"


def _extract_trailing_int(text: str) -> int | None:
    value = str(text or "").strip().rstrip("/")
    if not value:
        return None
    tail = value.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _extract_first_int(text: str) -> int | None:
    digits = ""
    for char in str(text or ""):
        if char.isdigit():
            digits += char
        elif digits:
            break
    return int(digits) if digits else None


def _extract_last_named_int(text: str, field_name: str) -> int | None:
    pattern = re.compile(rf"{re.escape(field_name)}=(\d+)")
    matches = [int(match.group(1)) for match in pattern.finditer(str(text or ""))]
    return matches[-1] if matches else None


def _device_now(controller: Any) -> dt.datetime:
    epoch_seconds = int(str(controller.execute_adb(["shell", "date", "+%s"]) or "0").strip() or 0)
    timezone_name = str(controller.execute_adb(["shell", "getprop", "persist.sys.timezone"]) or "UTC").strip() or "UTC"
    try:
        tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tzinfo = dt.timezone.utc
    return dt.datetime.fromtimestamp(epoch_seconds, tz=tzinfo)


def _datetime_to_seconds(value: str, timezone_name: str) -> int:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = dt.timezone.utc
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return int(parsed.timestamp())


def _sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"
