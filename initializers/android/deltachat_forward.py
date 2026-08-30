"""Android initializer for the Delta Chat forward-message task.

Seeds two conversations via GreenMail SMTP:
1. Source conversation (contains the message to forward)
2. Target conversation (the recipient to forward to)
Then launches Delta Chat.
"""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.mail_app_utils import (
    launch_mail_or_chat_app,
    reset_delta_chat_account_if_requested,
)


class DeltaChatForwardMessageInitializer(BaseInitializer):
    """Prepare two seeded conversations and launch Delta Chat for forwarding."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_APP_PACKAGE = "chat.delta"
    DEFAULT_APP_ACTIVITY = "org.thoughtcrime.securesms.RoutingActivity"
    DEFAULT_WAIT_MS = 2500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Delta Chat initialization",
            )

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or self.DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        purge_greenmail = bool(params.get("purge_greenmail", True))

        # Source conversation seed params
        source_sender_email = str(params.get("source_sender_email") or "").strip()
        source_sender_password = str(params.get("source_sender_password") or "").strip()
        source_recipient_email = str(params.get("source_recipient_email") or "").strip()
        source_subject = str(params.get("source_subject") or "").strip()
        source_body = str(params.get("source_body") or "").strip()

        # Target conversation seed params
        target_sender_email = str(params.get("target_sender_email") or "").strip()
        target_sender_password = str(params.get("target_sender_password") or "").strip()
        target_recipient_email = str(params.get("target_recipient_email") or "").strip()
        target_subject = str(params.get("target_subject") or "").strip()
        target_body = str(params.get("target_body") or "").strip()

        smtp_host = str(params.get("seed_smtp_host") or "127.0.0.1").strip()
        smtp_port = int(params.get("seed_smtp_port") or 3025)

        try:
            self._ensure_greenmail_ready(api_base_url)
            reset_delta_chat_account_if_requested(
                controller,
                params,
                api_base_url=api_base_url,
            )
            if purge_greenmail:
                self._purge_greenmail(api_base_url)

            # Seed the source conversation (the message to be forwarded)
            if all((source_sender_email, source_sender_password,
                     source_recipient_email, source_subject, source_body)):
                self._send_seed_email(
                    smtp_host=smtp_host, smtp_port=smtp_port,
                    sender_email=source_sender_email,
                    sender_password=source_sender_password,
                    recipient_email=source_recipient_email,
                    subject=source_subject, body=source_body,
                )

            # Seed the target conversation (so it exists for forwarding to)
            if all((target_sender_email, target_sender_password,
                     target_recipient_email, target_subject, target_body)):
                self._send_seed_email(
                    smtp_host=smtp_host, smtp_port=smtp_port,
                    sender_email=target_sender_email,
                    sender_password=target_sender_password,
                    recipient_email=target_recipient_email,
                    subject=target_subject, body=target_body,
                )

            ok, focus_output = launch_mail_or_chat_app(
                controller,
                app_package=app_package,
                app_activity=app_activity,
                label="Delta Chat",
                wait_ms=wait_ms,
            )
            if not ok:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=f"Delta Chat did not become the foreground app: {focus_output or 'no focus output'}",
                    metadata={"app_package": app_package, "focus_output": focus_output},
                )

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare forward-message task: {type(exc).__name__}: {exc}",
                metadata={"api_base_url": api_base_url, "app_package": app_package},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Two conversations seeded and Delta Chat opened for forwarding",
            metadata={
                "api_base_url": api_base_url,
                "app_package": app_package,
                "source_sender_email": source_sender_email,
                "target_sender_email": target_sender_email,
                "reset_app_data": bool(params.get("reset_app_data", False)),
            },
        )

    @staticmethod
    def _send_seed_email(
        *, smtp_host: str, smtp_port: int,
        sender_email: str, sender_password: str,
        recipient_email: str, subject: str, body: str,
    ) -> None:
        message = EmailMessage()
        message["From"] = sender_email
        message["To"] = recipient_email
        message["Subject"] = subject
        message["Chat-Version"] = "1.0"
        message.set_content(body)

        with smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=10.0) as client:
            try:
                client.login(sender_email, sender_password)
            except smtplib.SMTPException:
                pass  # GreenMail test SMTP may not require auth
            client.send_message(message)

    @staticmethod
    def _ensure_greenmail_ready(api_base_url: str) -> None:
        payload = DeltaChatForwardMessageInitializer._request_json(
            f"{api_base_url}/api/service/readiness", method="GET",
        )
        if not isinstance(payload, dict) or payload.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")

    @staticmethod
    def _purge_greenmail(api_base_url: str) -> None:
        DeltaChatForwardMessageInitializer._request_json(
            f"{api_base_url}/api/mail/purge", method="POST", allow_empty=True,
        )

    @staticmethod
    def _request_json(url: str, *, method: str, allow_empty: bool = False) -> Any:
        request = Request(url, method=method)
        try:
            with urlopen(request, timeout=5.0) as response:
                raw = response.read()
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"{method} {url} failed: {exc}") from exc

        if not raw:
            if allow_empty:
                return None
            raise RuntimeError(f"{method} {url} returned an empty response")

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{method} {url} returned invalid JSON") from exc
