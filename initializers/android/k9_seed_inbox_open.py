"""Android initializer for K-9 forward tasks with seeded inbox messages."""

from __future__ import annotations

import json
import smtplib
import time
from email.message import EmailMessage
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.mail_app_utils import (
    launch_mail_or_chat_app,
    reset_k9_account_if_requested,
)


class K9SeedInboxOpenInitializer(BaseInitializer):
    """Seed inbox messages via GreenMail SMTP, then open K-9."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_APP_PACKAGE = "com.fsck.k9"
    DEFAULT_APP_ACTIVITY = "net.thunderbird.app.common.MainActivity"
    DEFAULT_WAIT_MS = 2000
    DEFAULT_SMTP_HOST = "127.0.0.1"
    DEFAULT_SMTP_PORT = 3025
    DEFAULT_AUTO_REFRESH_INBOX = True
    DEFAULT_REFRESH_ATTEMPTS = 2
    DEFAULT_REFRESH_PAUSE_MS = 1200

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for K-9 initialization",
            )

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or self.DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        purge_greenmail = bool(params.get("purge_greenmail", True))
        auto_refresh_inbox = bool(params.get("auto_refresh_inbox", self.DEFAULT_AUTO_REFRESH_INBOX))
        refresh_attempts = int(params.get("refresh_attempts", self.DEFAULT_REFRESH_ATTEMPTS) or 0)
        refresh_pause_ms = int(params.get("refresh_pause_ms", self.DEFAULT_REFRESH_PAUSE_MS) or 0)

        smtp_host = str(params.get("seed_smtp_host") or self.DEFAULT_SMTP_HOST).strip()
        smtp_port = int(params.get("seed_smtp_port") or self.DEFAULT_SMTP_PORT)
        default_recipient = str(params.get("default_recipient_email") or "benchsender@example.test").strip()

        seed_messages = params.get("seed_messages") or []
        if not isinstance(seed_messages, list):
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer.params seed_messages must be a list",
            )

        try:
            self._ensure_greenmail_ready(api_base_url)
            reset_k9_account_if_requested(
                controller,
                params,
                api_base_url=api_base_url,
            )
            if purge_greenmail:
                self._purge_greenmail(api_base_url)

            for item in seed_messages:
                if not isinstance(item, Mapping):
                    continue
                sender_email = str(item.get("sender_email") or "").strip()
                sender_password = str(item.get("sender_password") or "").strip()
                recipient_email = str(item.get("recipient_email") or default_recipient).strip()
                subject = str(item.get("subject") or "").strip()
                body = str(item.get("body") or "")
                if not sender_email or not recipient_email or not subject or not body:
                    continue
                self._send_seed_email(
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    sender_email=sender_email,
                    sender_password=sender_password,
                    recipient_email=recipient_email,
                    subject=subject,
                    body=body,
                )

            ok, focus_output = launch_mail_or_chat_app(
                controller,
                app_package=app_package,
                app_activity=app_activity,
                label="K-9 Mail",
                wait_ms=wait_ms,
            )
            if not ok:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=f"K-9 did not become the foreground app: {focus_output or 'no focus output'}",
                    metadata={
                        "app_package": app_package,
                        "app_activity": app_activity,
                        "focus_output": focus_output,
                    },
                )

            if auto_refresh_inbox and refresh_attempts > 0:
                self._refresh_k9_inbox(
                    controller=controller,
                    attempts=refresh_attempts,
                    pause_ms=refresh_pause_ms,
                )

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare K-9 forward task: {type(exc).__name__}: {exc}",
                metadata={
                    "api_base_url": api_base_url,
                    "app_package": app_package,
                    "app_activity": app_activity,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="GreenMail seeded and K-9 opened",
            metadata={
                "api_base_url": api_base_url,
                "app_package": app_package,
                "seed_message_count": len(seed_messages),
                "purge_greenmail": purge_greenmail,
                "auto_refresh_inbox": auto_refresh_inbox,
                "refresh_attempts": refresh_attempts,
                "reset_app_data": bool(params.get("reset_app_data", False)),
            },
        )

    @staticmethod
    def _refresh_k9_inbox(*, controller: Any, attempts: int, pause_ms: int) -> None:
        width = int(getattr(controller, "width", 1080) or 1080)
        height = int(getattr(controller, "height", 1920) or 1920)
        start_x = width // 2
        start_y = max(int(height * 0.28), 320)
        end_y = min(int(height * 0.72), height - 160)

        for _ in range(max(attempts, 0)):
            controller.execute_adb(
                [
                    "shell",
                    "input",
                    "swipe",
                    str(start_x),
                    str(start_y),
                    str(start_x),
                    str(end_y),
                    "320",
                ]
            )
            if pause_ms > 0:
                time.sleep(pause_ms / 1000.0)

    @staticmethod
    def _send_seed_email(
        *,
        smtp_host: str,
        smtp_port: int,
        sender_email: str,
        sender_password: str,
        recipient_email: str,
        subject: str,
        body: str,
    ) -> None:
        message = EmailMessage()
        message["From"] = sender_email
        message["To"] = recipient_email
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=10.0) as client:
            try:
                client.login(sender_email, sender_password)
            except smtplib.SMTPException:
                pass
            client.send_message(message)

    @staticmethod
    def _ensure_greenmail_ready(api_base_url: str) -> None:
        payload = K9SeedInboxOpenInitializer._request_json(
            f"{api_base_url}/api/service/readiness",
            method="GET",
        )
        if not isinstance(payload, dict) or payload.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")

    @staticmethod
    def _purge_greenmail(api_base_url: str) -> None:
        K9SeedInboxOpenInitializer._request_json(
            f"{api_base_url}/api/mail/purge",
            method="POST",
            allow_empty=True,
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
