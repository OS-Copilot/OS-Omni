"""Evaluator for deleting one specific email in Maily while keeping decoys."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class MailyDeleteSpecificEmailEvaluator(BaseEvaluator):
    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_MAILBOX = "INBOX"
    DEFAULT_TIMEOUT_SECONDS = 12.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        recipient_email = str(params.get("recipient_email") or "").strip()
        mailbox = str(params.get("mailbox") or self.DEFAULT_MAILBOX).strip() or self.DEFAULT_MAILBOX
        target_subject = str(params.get("target_subject") or "").strip()
        decoy_subjects = self._coerce_text_list(params.get("decoy_subjects"))
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        if not recipient_email or not target_subject:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params recipient_email and target_subject are required",
            )
        if not decoy_subjects:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params decoy_subjects must be a non-empty list",
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

            subjects = [str(message.get("subject") or "").strip() for message in last_messages]
            target_still_present = target_subject in subjects
            missing_decoys = [subject for subject in decoy_subjects if subject not in subjects]

            if not target_still_present and not missing_decoys:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Target email was deleted while decoy emails remained in INBOX",
                    metadata={
                        "recipient_email": recipient_email,
                        "target_subject": target_subject,
                        "decoy_subjects": decoy_subjects,
                        "attempts": attempts,
                        "remaining_subjects": subjects,
                    },
                )

            if time.time() >= deadline:
                break

            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        subjects = [str(message.get("subject") or "").strip() for message in last_messages]
        missing_decoys = [subject for subject in decoy_subjects if subject not in subjects]
        target_still_present = target_subject in subjects
        if target_still_present:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Target email '{target_subject}' is still present in the mailbox",
                metadata={
                    "recipient_email": recipient_email,
                    "target_subject": target_subject,
                    "decoy_subjects": decoy_subjects,
                    "remaining_subjects": subjects,
                    "attempts": attempts,
                },
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message="One or more decoy emails are missing after deletion",
            metadata={
                "recipient_email": recipient_email,
                "target_subject": target_subject,
                "decoy_subjects": decoy_subjects,
                "missing_decoys": missing_decoys,
                "remaining_subjects": subjects,
                "attempts": attempts,
            },
        )

    @staticmethod
    def _coerce_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        values: list[str] = []
        for item in raw:
            text = str(item or "").strip()
            if text:
                values.append(text)
        return values

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
