"""Evaluator for the Android K-9 send-email task."""

from __future__ import annotations

import json
import time
from collections import Counter
from email import policy
from email.parser import Parser
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class K9SendEmailEvaluator(BaseEvaluator):
    """Validate that K-9 delivered the expected message to GreenMail."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_MAILBOX = "INBOX"
    DEFAULT_TIMEOUT_SECONDS = 15.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        recipient_email = str(params.get("recipient_email") or "").strip()
        subject = str(params.get("subject") or "").strip()
        body = str(params.get("body") or "").strip()
        body_lines_unordered = params.get("body_lines_unordered") or []
        sender_email = str(params.get("sender_email") or "").strip()
        mailbox = str(params.get("mailbox") or self.DEFAULT_MAILBOX).strip() or self.DEFAULT_MAILBOX
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        if not isinstance(body_lines_unordered, list):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params body_lines_unordered must be a list when provided",
            )
        expected_lines = [str(line).strip() for line in body_lines_unordered]

        if not recipient_email or not subject or (not body and not expected_lines):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params recipient_email, subject, and body or body_lines_unordered are required",
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
                body=body,
                body_lines_unordered=expected_lines,
            )
            if match is not None:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Expected message was delivered to GreenMail",
                    metadata={
                        "recipient_email": recipient_email,
                        "subject": subject,
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
        body: str,
        body_lines_unordered: list[str] | None = None,
    ) -> dict[str, Any] | None:
        expected_lines = list(body_lines_unordered or [])
        for message in messages:
            if str(message.get("subject") or "").strip() != subject:
                continue

            mime_message = str(message.get("mimeMessage") or "")
            parsed_message = K9SendEmailEvaluator._parse_mime_message(mime_message)
            to_header = str(parsed_message.get("to") if parsed_message else "")
            from_header = str(parsed_message.get("from") if parsed_message else "")

            if recipient_email not in (to_header or mime_message):
                continue
            if sender_email and sender_email not in (from_header or mime_message):
                continue

            body_candidates = K9SendEmailEvaluator._extract_body_candidates(
                parsed_message=parsed_message,
                raw_mime=mime_message,
            )
            if expected_lines:
                if not any(
                    K9SendEmailEvaluator._body_lines_match_unordered(candidate, expected_lines)
                    for candidate in body_candidates
                ):
                    continue
            elif not any(K9SendEmailEvaluator._body_matches(candidate, body) for candidate in body_candidates):
                continue
            return message
        return None

    @staticmethod
    def _parse_mime_message(mime_message: str):
        if not mime_message.strip():
            return None
        try:
            return Parser(policy=policy.default).parsestr(mime_message)
        except Exception:
            return None

    @staticmethod
    def _extract_body_candidates(*, parsed_message: Any, raw_mime: str) -> list[str]:
        candidates: list[str] = []
        if parsed_message is not None:
            if parsed_message.is_multipart():
                for part in parsed_message.walk():
                    content_type = str(part.get_content_type() or "").lower()
                    disposition = str(part.get_content_disposition() or "").lower()
                    if content_type.startswith("text/") and disposition != "attachment":
                        try:
                            payload = part.get_content()
                        except Exception:
                            payload = ""
                        if payload:
                            candidates.append(str(payload))
            else:
                try:
                    payload = parsed_message.get_content()
                except Exception:
                    payload = ""
                if payload:
                    candidates.append(str(payload))
        candidates.append(raw_mime)
        return candidates

    @staticmethod
    def _body_matches(candidate: str, expected_body: str) -> bool:
        candidate_text = str(candidate or "")
        expected = str(expected_body or "")
        if expected in candidate_text:
            return True
        normalized_candidate = candidate_text.replace("\r\n", "\n").replace("\r", "\n")
        normalized_expected = expected.replace("\r\n", "\n").replace("\r", "\n")
        if normalized_expected in normalized_candidate:
            return True
        if "\n" not in normalized_expected:
            return normalized_expected in normalized_candidate.replace("\n", "")
        return False

    @staticmethod
    def _body_lines_match_unordered(candidate: str, expected_lines: list[str]) -> bool:
        normalized = str(candidate or "").replace("\r\n", "\n").replace("\r", "\n")
        actual_lines = [line.strip() for line in normalized.split("\n") if line.strip()]
        return not (Counter(expected_lines) - Counter(actual_lines))
