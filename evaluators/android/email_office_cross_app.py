"""Evaluators for Android K-9 + document-editor cross-app tasks."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class EmailOfficeCrossAppEvaluator(BaseEvaluator):
    """Validate saved document content and optional GreenMail deliveries."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_REMOTE_CANDIDATES = (
        "/sdcard/Documents/markor",
        "/storage/emulated/0/Documents/markor",
        "/sdcard/Documents/QuickNote",
        "/storage/emulated/0/Documents/QuickNote",
        "/sdcard/Documents",
        "/sdcard/Download",
        "/sdcard/Downloads",
        "/sdcard",
    )

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.execute_adb is required for Email+Office evaluation",
            )

        filename = str(params.get("filename") or "").strip()
        document_format = str(params.get("document_format") or "").strip().lower()
        required_texts = _coerce_text_list(params.get("required_document_texts"))
        absent_texts = _coerce_text_list(params.get("absent_document_texts"))
        expected_messages = params.get("expected_emails") or []
        if expected_messages and not isinstance(expected_messages, list):
            return EvalResult(status=EvalStatus.ERROR, message="expected_emails must be a list")

        failures: list[str] = []
        metadata: dict[str, Any] = {}

        if filename or required_texts or absent_texts:
            if not filename:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message="filename is required when document text checks are configured",
                )
            remote_path = self._find_remote_document(controller=controller, filename=filename)
            metadata["remote_path"] = remote_path
            if not remote_path:
                failures.append(f"Could not locate {filename} on device storage")
            else:
                document_text, local_path = self._pull_document_text(
                    controller=controller,
                    remote_path=remote_path,
                    document_format=document_format,
                )
                metadata["local_pulled_path"] = local_path
                metadata["document_text_size"] = len(document_text)
                normalized_document_text = _normalize_eval_text(document_text)
                for text in required_texts:
                    if _normalize_eval_text(text) not in normalized_document_text:
                        failures.append(f"Missing document text: {text}")
                for text in absent_texts:
                    if _normalize_eval_text(text) in normalized_document_text:
                        failures.append(f"Unexpected document text still present: {text}")

        if expected_messages:
            email_result = self._validate_expected_emails(params=params, expected_messages=expected_messages)
            metadata["email_checks"] = email_result
            failures.extend(email_result.get("failures", []))

        if failures:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Email+document cross-app checks did not pass",
                metadata={**metadata, "failures": failures},
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Email+document cross-app checks passed",
            metadata=metadata,
        )

    @classmethod
    def _find_remote_document(cls, *, controller: Any, filename: str) -> str:
        for base in cls.DEFAULT_REMOTE_CANDIDATES:
            remote = f"{base.rstrip('/')}/{filename}"
            out = str(controller.execute_adb(["shell", "ls", remote]) or "").strip()
            if out == remote or out.endswith(filename):
                return remote
        lookup = f"find /sdcard -type f -name '{filename}' 2>/dev/null | head -n 1"
        out = str(controller.execute_adb(["shell", "sh", "-c", lookup]) or "").strip()
        return out if out.endswith(filename) else ""

    @staticmethod
    def _pull_document_text(*, controller: Any, remote_path: str, document_format: str = "") -> tuple[str, str]:
        local_dir = Path.cwd() / "_evaluator"
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / Path(remote_path).name
        controller.execute_adb(["pull", remote_path, str(local_path)])
        if not local_path.exists() or local_path.stat().st_size <= 0:
            return "", str(local_path)
        if document_format in {"text", "markdown", "md"} or local_path.suffix.lower() not in {".odt", ".ods", ".odp"}:
            return local_path.read_text(encoding="utf-8", errors="ignore"), str(local_path)
        try:
            with zipfile.ZipFile(local_path, "r") as zf:
                with zf.open("content.xml") as f:
                    return f.read().decode("utf-8", errors="ignore"), str(local_path)
        except Exception:
            return "", str(local_path)

    def _validate_expected_emails(
        self,
        *,
        params: Mapping[str, Any],
        expected_messages: list[Any],
    ) -> dict[str, Any]:
        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        timeout_seconds = float(params.get("email_timeout_seconds", 20) or 0)
        poll_interval_seconds = float(params.get("email_poll_interval_seconds", 1) or 0)
        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_mailbox_sizes: dict[str, int] = {}
        failures: list[str] = []

        while True:
            attempts += 1
            failures = []
            last_mailbox_sizes = {}
            for item in expected_messages:
                if not isinstance(item, Mapping):
                    continue
                recipient = str(item.get("recipient_email") or "").strip()
                subject = str(item.get("subject") or "").strip()
                body_contains = _coerce_text_list(item.get("body_contains"))
                sender = str(item.get("sender_email") or "").strip()
                mailbox = str(item.get("mailbox") or "INBOX").strip() or "INBOX"
                if not recipient or not subject:
                    failures.append("Expected email requires recipient_email and subject")
                    continue
                try:
                    messages = _fetch_mailbox_messages(
                        api_base_url=api_base_url,
                        recipient_email=recipient,
                        mailbox=mailbox,
                    )
                except Exception as exc:
                    failures.append(f"Failed to query GreenMail for {recipient}: {type(exc).__name__}: {exc}")
                    continue
                last_mailbox_sizes[recipient] = len(messages)
                if not _has_matching_message(
                    messages,
                    recipient_email=recipient,
                    sender_email=sender,
                    subject=subject,
                    body_contains=body_contains,
                ):
                    failures.append(f"Missing expected email to {recipient} with subject {subject}")
            if not failures or time.time() >= deadline:
                break
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return {
            "attempts": attempts,
            "mailbox_sizes": last_mailbox_sizes,
            "failures": failures,
        }


def _fetch_mailbox_messages(*, api_base_url: str, recipient_email: str, mailbox: str) -> list[dict[str, Any]]:
    encoded_user = quote(recipient_email, safe="")
    encoded_mailbox = quote(mailbox, safe="")
    request = Request(f"{api_base_url}/api/user/{encoded_user}/messages/{encoded_mailbox}", method="GET")
    try:
        with urlopen(request, timeout=5.0) as response:
            payload = response.read()
    except HTTPError as exc:
        if exc.code == 400:
            return []
        raise RuntimeError(f"GET mailbox failed: {exc}") from exc
    except URLError as exc:
        raise RuntimeError(f"GET mailbox failed: {exc}") from exc
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"GreenMail mailbox payload must be a list, got {type(data)!r}")
    return [msg for msg in data if isinstance(msg, dict)]


def _has_matching_message(
    messages: list[dict[str, Any]],
    *,
    recipient_email: str,
    sender_email: str,
    subject: str,
    body_contains: list[str],
) -> bool:
    for message in messages:
        if str(message.get("subject") or "").strip() != subject:
            continue
        mime_message = str(message.get("mimeMessage") or "")
        if f"To: {recipient_email}" not in mime_message:
            continue
        if sender_email and sender_email not in mime_message:
            continue
        normalized_mime = _normalize_eval_text(mime_message)
        if any(_normalize_eval_text(text) not in normalized_mime for text in body_contains):
            continue
        return True
    return False


def _coerce_text_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _normalize_eval_text(value: Any) -> str:
    return " ".join(str(value or "").split())
