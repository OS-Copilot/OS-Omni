"""Android initializer for the Delta Chat search-and-quote-reply task.

Seeds multiple conversations via GreenMail SMTP so that Delta Chat
has several chats to search through. One of them contains the target
message that the agent must find and quote-reply to.
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
from initializers.android.deltachat import DeltaChatSendMessageInitializer


class DeltaChatSearchReplyInitializer(BaseInitializer):
    """Seed multiple conversations and launch Delta Chat for search-and-reply."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_APP_PACKAGE = "chat.delta"
    DEFAULT_APP_ACTIVITY = "org.thoughtcrime.securesms.RoutingActivity"
    DEFAULT_WAIT_MS = 2500
    DEFAULT_SEED_VISIBLE_TIMEOUT_SECONDS = 35.0
    DEFAULT_SEED_VISIBLE_POLL_INTERVAL_SECONDS = 1.5

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
        require_seed_visible = bool(params.get("require_seed_visible", True))
        seed_visible_timeout_seconds = float(
            params.get("seed_visible_timeout_seconds", self.DEFAULT_SEED_VISIBLE_TIMEOUT_SECONDS) or 0.0
        )
        seed_visible_poll_interval_seconds = float(
            params.get(
                "seed_visible_poll_interval_seconds",
                self.DEFAULT_SEED_VISIBLE_POLL_INTERVAL_SECONDS,
            )
            or 0.0
        )

        smtp_host = str(params.get("seed_smtp_host") or "127.0.0.1").strip()
        smtp_port = int(params.get("seed_smtp_port") or 3025)

        # Collect seed emails: decoys + target
        seed_emails = []

        # Decoy 1
        if params.get("decoy1_sender_email"):
            seed_emails.append({
                "sender_email": str(params["decoy1_sender_email"]),
                "sender_password": str(params.get("decoy1_sender_password", "")),
                "recipient_email": str(params.get("decoy1_recipient_email", "")),
                "subject": str(params.get("decoy1_subject", "")),
                "body": str(params.get("decoy1_body", "")),
            })

        # Decoy 2
        if params.get("decoy2_sender_email"):
            seed_emails.append({
                "sender_email": str(params["decoy2_sender_email"]),
                "sender_password": str(params.get("decoy2_sender_password", "")),
                "recipient_email": str(params.get("decoy2_recipient_email", "")),
                "subject": str(params.get("decoy2_subject", "")),
                "body": str(params.get("decoy2_body", "")),
            })

        # Target (sent last so it appears in Delta Chat)
        if params.get("target_sender_email"):
            seed_emails.append({
                "sender_email": str(params["target_sender_email"]),
                "sender_password": str(params.get("target_sender_password", "")),
                "recipient_email": str(params.get("target_recipient_email", "")),
                "subject": str(params.get("target_subject", "")),
                "body": str(params.get("target_body", "")),
                "is_target": True,
            })
        seed_visibility = None

        try:
            self._ensure_greenmail_ready(api_base_url)
            reset_delta_chat_account_if_requested(
                controller,
                params,
                api_base_url=api_base_url,
            )
            if purge_greenmail:
                self._purge_greenmail(api_base_url)

            # Send all seed emails
            for seed in seed_emails:
                if all(seed.get(k) for k in ("sender_email", "recipient_email", "body")):
                    self._send_seed_email(
                        smtp_host=smtp_host, smtp_port=smtp_port,
                        sender_email=seed["sender_email"],
                        sender_password=seed["sender_password"],
                        recipient_email=seed["recipient_email"],
                        subject=seed["subject"], body=seed["body"],
                    )

            valid_seed_emails = [
                seed
                for seed in seed_emails
                if all(seed.get(k) for k in ("sender_email", "recipient_email", "subject", "body"))
            ]
            target_seed = next((seed for seed in valid_seed_emails if seed.get("is_target")), None)
            if valid_seed_emails:
                sync_reset = DeltaChatSendMessageInitializer._reset_imap_sync_checkpoint(
                    controller=controller,
                    app_package=app_package,
                )
                db_paths = sync_reset.get("db_paths", [])
                for seed in valid_seed_emails:
                    DeltaChatSendMessageInitializer._patch_seed_conversation_databases(
                        controller=controller,
                        app_package=app_package,
                        seed_sender_email=str(seed["sender_email"]),
                        seed_subject=str(seed["subject"]),
                        seed_body=str(seed["body"]),
                        db_paths=db_paths,
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

            if target_seed is not None:
                seed_visibility = DeltaChatSendMessageInitializer._wait_for_seed_conversation_visible(
                    controller=controller,
                    app_package=app_package,
                    app_activity=app_activity,
                    seed_sender_email=str(target_seed["sender_email"]),
                    seed_body=str(target_seed["body"]),
                    timeout_seconds=seed_visible_timeout_seconds,
                    poll_interval_seconds=seed_visible_poll_interval_seconds,
                )
                if require_seed_visible and not seed_visibility["visible"]:
                    return InitResult(
                        status=InitStatus.FAIL,
                        message=(
                            "Delta Chat target seed conversation did not become visible "
                            "after GreenMail injection"
                        ),
                        metadata={
                            "api_base_url": api_base_url,
                            "app_package": app_package,
                            "target_sender_email": target_seed["sender_email"],
                            "seed_visibility": seed_visibility,
                        },
                    )

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare search-reply task: {type(exc).__name__}: {exc}",
                metadata={"api_base_url": api_base_url, "app_package": app_package},
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Seeded {len(seed_emails)} conversations and Delta Chat opened",
            metadata={
                "api_base_url": api_base_url,
                "app_package": app_package,
                "seed_count": len(seed_emails),
                "reset_app_data": bool(params.get("reset_app_data", False)),
                "seed_visibility": seed_visibility,
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
        payload = DeltaChatSearchReplyInitializer._request_json(
            f"{api_base_url}/api/service/readiness", method="GET",
        )
        if not isinstance(payload, dict) or payload.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")

    @staticmethod
    def _purge_greenmail(api_base_url: str) -> None:
        DeltaChatSearchReplyInitializer._request_json(
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
