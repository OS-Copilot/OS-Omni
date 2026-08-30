"""Evaluator for the Delta Chat search-and-quote-reply task.

Verifies that the agent found the correct message via search and
sent a quote-reply to the correct recipient via GreenMail.
"""

from __future__ import annotations

import json
import time
from email.parser import Parser
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class DeltaChatSearchReplyEvaluator(BaseEvaluator):
    """Validate that the quote-reply was delivered to the correct recipient."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_MAILBOX = "INBOX"
    DEFAULT_TIMEOUT_SECONDS = 25.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        target_recipient_email = str(params.get("target_recipient_email") or "").strip()
        sender_email = str(params.get("sender_email") or "").strip()
        reply_body = str(params.get("reply_body") or "").strip()
        original_body = str(params.get("original_body") or "").strip()
        mailbox = str(params.get("mailbox") or self.DEFAULT_MAILBOX).strip() or self.DEFAULT_MAILBOX
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        if not target_recipient_email or not reply_body:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params target_recipient_email and reply_body are required",
            )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_messages: list[dict[str, Any]] = []

        while True:
            attempts += 1
            try:
                last_messages = self._fetch_mailbox_messages(
                    api_base_url=api_base_url,
                    recipient_email=target_recipient_email,
                    mailbox=mailbox,
                )
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to query GreenMail: {type(exc).__name__}: {exc}",
                    metadata={"api_base_url": api_base_url, "target_recipient_email": target_recipient_email},
                )

            match = self._find_reply_message(
                messages=last_messages,
                target_recipient_email=target_recipient_email,
                sender_email=sender_email,
                reply_body=reply_body,
                original_body=original_body,
            )
            if match is not None:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Quote-reply was successfully delivered to target recipient",
                    metadata={
                        "target_recipient_email": target_recipient_email,
                        "uid": match.get("uid"),
                        "attempts": attempts,
                    },
                )

            if time.time() >= deadline:
                break

            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Quote-reply was not found in target recipient's mailbox",
            metadata={
                "target_recipient_email": target_recipient_email,
                "attempts": attempts,
                "mailbox_size": len(last_messages),
            },
        )

    @staticmethod
    def _fetch_mailbox_messages(
        *, api_base_url: str, recipient_email: str, mailbox: str,
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

    @staticmethod
    def _find_reply_message(
        *,
        messages: list[dict[str, Any]],
        target_recipient_email: str,
        sender_email: str,
        reply_body: str,
        original_body: str,
    ) -> dict[str, Any] | None:
        for message in messages:
            mime_message = str(message.get("mimeMessage") or "")
            headers = Parser().parsestr(mime_message, headersonly=True)
            to_headers = headers.get_all("To", [])
            from_headers = headers.get_all("From", [])

            # Check recipient
            if not any(target_recipient_email.lower() in h.lower() for h in to_headers):
                continue
            # Check sender
            if sender_email and not any(
                sender_email.lower() in h.lower() for h in from_headers
            ):
                continue
            # The reply text must be present
            if reply_body not in mime_message:
                continue
            # The original quoted text should also appear (quote-reply)
            # Note: Delta Chat may include the original in various formats,
            # so we check if the original text appears anywhere in the MIME
            if original_body and original_body not in mime_message:
                continue
            return message
        return None
