"""Evaluator for Android K-9 simple send-email v2 task."""

from __future__ import annotations

from email import policy
from email.parser import Parser
import json
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class K9SimpleSendEmailV2Evaluator(BaseEvaluator):
    """Validate delivery with exact subject and exact parsed text body."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_MAILBOX = "INBOX"
    DEFAULT_TIMEOUT_SECONDS = 20.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        recipient_email = str(params.get("recipient_email") or "").strip()
        subject = str(params.get("subject") or "").strip()
        sender_email = str(params.get("sender_email") or "").strip()
        mailbox = str(params.get("mailbox") or self.DEFAULT_MAILBOX).strip() or self.DEFAULT_MAILBOX
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        expected_body = str(params.get("expected_body") or "")

        if not recipient_email or not subject or not expected_body:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params recipient_email, subject, and expected_body are required",
            )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_messages: list[dict[str, Any]] = []

        while True:
            attempts += 1
            try:
                last_messages = self._fetch_mailbox_messages(
                    api_base_url=api_base_url,
                    recipient_email=recipient_email,
                    mailbox=mailbox,
                )
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to query GreenMail: {type(exc).__name__}: {exc}",
                    metadata={"api_base_url": api_base_url, "recipient_email": recipient_email},
                )

            match = self._find_matching_message(
                messages=last_messages,
                recipient_email=recipient_email,
                sender_email=sender_email,
                subject=subject,
                expected_body=expected_body,
            )
            if match is not None:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Expected message with exact parsed body was delivered to GreenMail",
                    metadata={
                        "recipient_email": recipient_email,
                        "subject": subject,
                        "expected_body": expected_body,
                        "uid": match.get("uid"),
                        "message_id": match.get("Message-ID"),
                        "attempts": attempts,
                    },
                )

            if time.time() >= deadline:
                break

            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Expected message was not found in GreenMail",
            metadata={
                "recipient_email": recipient_email,
                "subject": subject,
                "expected_body": expected_body,
                "attempts": attempts,
                "mailbox_size": len(last_messages),
            },
        )

    @staticmethod
    def _fetch_mailbox_messages(
        *,
        api_base_url: str,
        recipient_email: str,
        mailbox: str,
    ) -> list[dict[str, Any]]:
        encoded_user = quote(recipient_email, safe="")
        encoded_mailbox = quote(mailbox, safe="")
        request = Request(
            f"{api_base_url}/api/user/{encoded_user}/messages/{encoded_mailbox}",
            method="GET",
        )
        try:
            with urlopen(request, timeout=5.0) as response:
                payload = response.read()
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"GET mailbox failed: {exc}") from exc

        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, list):
            raise RuntimeError(f"GreenMail mailbox payload must be a list, got {type(data)!r}")
        return [msg for msg in data if isinstance(msg, dict)]

    @staticmethod
    def _find_matching_message(
        *,
        messages: list[dict[str, Any]],
        recipient_email: str,
        sender_email: str,
        subject: str,
        expected_body: str,
    ) -> dict[str, Any] | None:
        for message in messages:
            if str(message.get("subject") or "").strip() != subject:
                continue

            mime_message = str(message.get("mimeMessage") or "")
            if f"To: {recipient_email}" not in mime_message:
                continue
            if sender_email and sender_email not in mime_message:
                continue

            parsed_body = K9SimpleSendEmailV2Evaluator._extract_text_plain_body(mime_message)
            if parsed_body is None:
                continue

            # Strict match against parsed text body. Only tolerate a single trailing newline.
            if not K9SimpleSendEmailV2Evaluator._is_exact_body_match(parsed_body, expected_body):
                continue

            return message
        return None

    @staticmethod
    def _extract_text_plain_body(mime_message: str) -> str | None:
        try:
            email_message = Parser(policy=policy.default).parsestr(mime_message)
        except Exception:
            return None

        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() != "text/plain":
                    continue
                if str(part.get_content_disposition() or "").lower() == "attachment":
                    continue
                try:
                    return str(part.get_content())
                except Exception:
                    return None
            return None

        if email_message.get_content_type() != "text/plain":
            return None

        try:
            return str(email_message.get_content())
        except Exception:
            return None

    @staticmethod
    def _normalize_newlines(value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _is_exact_body_match(parsed_body: str, expected_body: str) -> bool:
        normalized_parsed_body = K9SimpleSendEmailV2Evaluator._normalize_newlines(parsed_body)
        normalized_expected_body = K9SimpleSendEmailV2Evaluator._normalize_newlines(expected_body)
        return (
            normalized_parsed_body == normalized_expected_body
            or normalized_parsed_body == f"{normalized_expected_body}\n"
        )
