"""Evaluator for the Fossify Calendar -> Organic Maps -> Delta Chat scene."""

from __future__ import annotations

import json
import time
from email.parser import Parser
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class CalendarMapDeltaChatEvaluator(BaseEvaluator):
    """Validate that Delta Chat delivered the expected cafe name and address."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_MAILBOX = "INBOX"
    DEFAULT_TIMEOUT_SECONDS = 20.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        sender_email = str(params.get("sender_email") or "").strip()
        recipient_email = str(params.get("recipient_email") or "").strip()
        mailbox = str(params.get("mailbox") or self.DEFAULT_MAILBOX).strip() or self.DEFAULT_MAILBOX
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )
        required_substrings = [
            str(item).strip()
            for item in (params.get("required_substrings") or [])
            if str(item).strip()
        ]
        forbidden_substrings = [
            str(item).strip()
            for item in (params.get("forbidden_substrings") or [])
            if str(item).strip()
        ]

        if not recipient_email or not required_substrings:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params recipient_email and required_substrings are required",
            )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_messages: list[dict[str, Any]] = []
        fetch_error_count = 0
        last_fetch_error = ""

        while True:
            attempts += 1
            try:
                last_messages = self._fetch_mailbox_messages(
                    api_base_url=api_base_url,
                    recipient_email=recipient_email,
                    mailbox=mailbox,
                )
            except Exception as exc:
                fetch_error_count += 1
                last_fetch_error = f"{type(exc).__name__}: {exc}"
                if time.time() >= deadline:
                    return EvalResult(
                        status=EvalStatus.ERROR,
                        message=f"Failed to query GreenMail: {last_fetch_error}",
                        metadata={
                            "api_base_url": api_base_url,
                            "recipient_email": recipient_email,
                            "attempts": attempts,
                            "fetch_error_count": fetch_error_count,
                        },
                    )
                if poll_interval_seconds > 0:
                    time.sleep(poll_interval_seconds)
                continue

            match = self._find_matching_message(
                messages=last_messages,
                sender_email=sender_email,
                recipient_email=recipient_email,
                required_substrings=required_substrings,
                forbidden_substrings=forbidden_substrings,
            )
            if match is not None:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Expected cross-app Delta Chat message was delivered to GreenMail",
                    metadata={
                        "recipient_email": recipient_email,
                        "uid": match.get("uid"),
                        "message_id": match.get("Message-ID"),
                        "attempts": attempts,
                        "fetch_error_count": fetch_error_count,
                    },
                )

            if time.time() >= deadline:
                break

            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Expected Delta Chat cafe message was not found in GreenMail",
            metadata={
                "recipient_email": recipient_email,
                "attempts": attempts,
                "mailbox_size": len(last_messages),
                "fetch_error_count": fetch_error_count,
                "last_fetch_error": last_fetch_error,
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
        sender_email: str,
        recipient_email: str,
        required_substrings: list[str],
        forbidden_substrings: list[str] | None = None,
    ) -> dict[str, Any] | None:
        recipient_email_lower = recipient_email.lower()
        sender_email_lower = sender_email.lower()
        required_lowers = [item.lower() for item in required_substrings]
        forbidden_lowers = [item.lower() for item in (forbidden_substrings or [])]

        for message in messages:
            mime_message = str(message.get("mimeMessage") or "")
            headers = Parser().parsestr(mime_message, headersonly=True)
            to_headers = headers.get_all("To", [])
            from_headers = headers.get_all("From", [])
            mime_lower = mime_message.lower()

            if not any(recipient_email_lower in header.lower() for header in to_headers):
                continue
            if sender_email and not any(sender_email_lower in header.lower() for header in from_headers):
                continue
            if any(forbidden in mime_lower for forbidden in forbidden_lowers):
                continue
            if not all(required in mime_lower for required in required_lowers):
                continue
            return message

        return None
