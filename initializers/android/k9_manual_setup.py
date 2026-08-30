"""Android initializer for the K-9 manual account-setup benchmark task."""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.mail_app_utils import launch_mail_or_chat_app


class K9ManualSetupInitializer(BaseInitializer):
    """Prepare a clean, unconfigured K-9 launch state and purge GreenMail."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_APP_PACKAGE = "com.fsck.k9"
    DEFAULT_APP_ACTIVITY = "net.thunderbird.app.common.MainActivity"
    DEFAULT_WAIT_MS = 1500
    DEFAULT_SMTP_HOST = "127.0.0.1"
    DEFAULT_SMTP_PORT = 3025

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for K-9 manual-setup initialization",
            )

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or self.DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        purge_greenmail = bool(params.get("purge_greenmail", True))
        clear_app_data = bool(params.get("clear_app_data", True))
        smtp_host = str(params.get("seed_smtp_host") or self.DEFAULT_SMTP_HOST).strip()
        smtp_port = int(params.get("seed_smtp_port") or self.DEFAULT_SMTP_PORT)
        default_recipient = str(params.get("default_recipient_email") or "benchsender@example.test").strip()
        seed_messages = params.get("seed_messages") or []

        if not isinstance(seed_messages, list):
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer.params seed_messages must be a list",
            )

        if not app_package or not app_activity:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package and app_activity",
            )

        try:
            if purge_greenmail:
                self._ensure_greenmail_ready(api_base_url)
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
                clear_app_data=clear_app_data,
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

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare K-9 launch state: {type(exc).__name__}: {exc}",
                metadata={
                    "api_base_url": api_base_url,
                    "app_package": app_package,
                    "app_activity": app_activity,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="GreenMail purged and K-9 opened in a clean unconfigured state",
            metadata={
                "api_base_url": api_base_url,
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "purge_greenmail": purge_greenmail,
                "clear_app_data": clear_app_data,
                "seed_message_count": len(seed_messages),
            },
        )

    @staticmethod
    def _ensure_greenmail_ready(api_base_url: str) -> None:
        payload = K9ManualSetupInitializer._request_json(
            f"{api_base_url}/api/service/readiness",
            method="GET",
        )
        if not isinstance(payload, dict) or payload.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")

    @staticmethod
    def _purge_greenmail(api_base_url: str) -> None:
        K9ManualSetupInitializer._request_json(
            f"{api_base_url}/api/mail/purge",
            method="POST",
            allow_empty=True,
        )

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
