"""Evaluators for Android K-9 forward-email tasks."""

from __future__ import annotations

import json
import time
from email import policy
from email.parser import Parser
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class _K9ForwardEvaluatorBase(BaseEvaluator):
    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_MAILBOX = "INBOX"
    DEFAULT_TIMEOUT_SECONDS = 30.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0

    @staticmethod
    def _normalize_newlines(value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n")

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

    @classmethod
    def _body_has_required_prefix(cls, body: str, required_prefix_line: str) -> bool:
        normalized_body = cls._normalize_newlines(body)
        first_line = normalized_body.split("\n", 1)[0].strip()
        return first_line == required_prefix_line

    @classmethod
    def _body_starts_with_lines(cls, body: str, required_lines: list[str]) -> bool:
        if not required_lines:
            return True
        normalized_body = cls._normalize_newlines(body)
        body_lines = [line.strip() for line in normalized_body.split("\n")]
        if len(body_lines) < len(required_lines):
            return False
        for idx, expected in enumerate(required_lines):
            if body_lines[idx] != expected.strip():
                return False
        return True

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

    @classmethod
    def _match_forwarded_email(
        cls,
        *,
        message: dict[str, Any],
        recipient_email: str,
        sender_email: str,
        required_prefix_line: str,
        source_subject_contains: str,
        source_body_marker: str,
        expected_subject_contains: str = "",
        expected_prefix_lines: list[str] | None = None,
    ) -> bool:
        mime_message = str(message.get("mimeMessage") or "")
        if f"To: {recipient_email}" not in mime_message:
            return False
        if sender_email and sender_email not in mime_message:
            return False

        subject_value = str(message.get("subject") or "")
        if expected_subject_contains:
            if expected_subject_contains not in subject_value:
                return False
        if source_subject_contains not in subject_value and source_subject_contains not in mime_message:
            return False

        parsed_body = cls._extract_text_plain_body(mime_message)
        if parsed_body is None:
            return False
        normalized_body = cls._normalize_newlines(parsed_body)
        if source_body_marker not in normalized_body:
            return False
        normalized_prefix_lines = [line.strip() for line in (expected_prefix_lines or []) if str(line).strip()]
        if normalized_prefix_lines:
            if not cls._body_starts_with_lines(normalized_body, normalized_prefix_lines):
                return False
        elif not cls._body_has_required_prefix(normalized_body, required_prefix_line):
            return False
        return True


class K9ForwardMeetingNotesEvaluator(_K9ForwardEvaluatorBase):
    """Validate forwarding one target email with a required prepended line."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        recipient_email = str(params.get("recipient_email") or "").strip()
        sender_email = str(params.get("sender_email") or "").strip()
        required_prefix_line = str(params.get("required_prefix_line") or "").strip()
        source_subject_contains = str(params.get("source_subject_contains") or "").strip()
        source_body_marker = str(params.get("source_body_marker") or "").strip()
        mailbox = str(params.get("mailbox") or self.DEFAULT_MAILBOX).strip() or self.DEFAULT_MAILBOX
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        if not all((recipient_email, required_prefix_line, source_subject_contains, source_body_marker)):
            return EvalResult(
                status=EvalStatus.ERROR,
                message=(
                    "evaluation.params recipient_email, required_prefix_line, "
                    "source_subject_contains, and source_body_marker are required"
                ),
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

            for message in last_messages:
                if self._match_forwarded_email(
                    message=message,
                    recipient_email=recipient_email,
                    sender_email=sender_email,
                    required_prefix_line=required_prefix_line,
                    source_subject_contains=source_subject_contains,
                    source_body_marker=source_body_marker,
                ):
                    return EvalResult(
                        status=EvalStatus.PASS,
                        message="Forwarded meeting-notes email with required prefix was delivered",
                        metadata={
                            "recipient_email": recipient_email,
                            "uid": message.get("uid"),
                            "attempts": attempts,
                        },
                    )

            if time.time() >= deadline:
                break
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Expected forwarded meeting-notes email was not found",
            metadata={
                "recipient_email": recipient_email,
                "attempts": attempts,
                "mailbox_size": len(last_messages),
            },
        )


class K9ForwardAlphaBetaReportsEvaluator(_K9ForwardEvaluatorBase):
    """Validate forwarding two different reports with the same required prefix."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        recipient_email = str(params.get("recipient_email") or "").strip()
        sender_email = str(params.get("sender_email") or "").strip()
        required_prefix_line = str(params.get("required_prefix_line") or "").strip()
        mailbox = str(params.get("mailbox") or self.DEFAULT_MAILBOX).strip() or self.DEFAULT_MAILBOX
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )
        required_forwards = params.get("required_forwards") or []

        if not recipient_email or not required_prefix_line or not isinstance(required_forwards, list):
            return EvalResult(
                status=EvalStatus.ERROR,
                message=(
                    "evaluation.params recipient_email, required_prefix_line, and "
                    "required_forwards(list) are required"
                ),
            )

        normalized_requirements: list[dict[str, str]] = []
        normalized_requirement_payload: list[dict[str, Any]] = []
        for item in required_forwards:
            if not isinstance(item, Mapping):
                continue
            source_subject_contains = str(item.get("source_subject_contains") or "").strip()
            source_body_marker = str(item.get("source_body_marker") or "").strip()
            expected_subject_contains = str(item.get("expected_subject_contains") or "").strip()
            expected_prefix_lines_raw = item.get("expected_prefix_lines") or []
            expected_prefix_lines = (
                [str(line).strip() for line in expected_prefix_lines_raw if str(line).strip()]
                if isinstance(expected_prefix_lines_raw, list)
                else []
            )
            if source_subject_contains and source_body_marker:
                normalized_requirements.append(
                    {
                        "source_subject_contains": source_subject_contains,
                        "source_body_marker": source_body_marker,
                    }
                )
                normalized_requirement_payload.append(
                    {
                        "source_subject_contains": source_subject_contains,
                        "source_body_marker": source_body_marker,
                        "expected_subject_contains": expected_subject_contains,
                        "expected_prefix_lines": expected_prefix_lines,
                    }
                )

        if not normalized_requirements:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params required_forwards must include at least one valid requirement",
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

            matched_markers: set[str] = set()
            for req in normalized_requirement_payload:
                for message in last_messages:
                    if self._match_forwarded_email(
                        message=message,
                        recipient_email=recipient_email,
                        sender_email=sender_email,
                        required_prefix_line=required_prefix_line,
                        source_subject_contains=req["source_subject_contains"],
                        source_body_marker=req["source_body_marker"],
                        expected_subject_contains=str(req.get("expected_subject_contains") or ""),
                        expected_prefix_lines=list(req.get("expected_prefix_lines") or []),
                    ):
                        matched_markers.add(req["source_body_marker"])
                        break

            if len(matched_markers) == len(normalized_requirements):
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="All required forwarded reports with prefix were delivered",
                    metadata={
                        "recipient_email": recipient_email,
                        "attempts": attempts,
                        "matched_markers": sorted(matched_markers),
                    },
                )

            if time.time() >= deadline:
                break
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Not all required forwarded reports were found",
            metadata={
                "recipient_email": recipient_email,
                "attempts": attempts,
                "mailbox_size": len(last_messages),
                "required_count": len(normalized_requirements),
            },
        )
