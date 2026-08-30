"""Seed GreenMail and open the target iOS app."""

from __future__ import annotations

import smtplib
import time
from email.message import EmailMessage
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.ios.greenmail_local_state import purge_local_state_for_bundle
from initializers.ios.greenmail_open_app import GreenMailOpenAppInitializer


class GreenMailSeedOpenAppInitializer(BaseInitializer):
    """Purge GreenMail, seed mailbox messages, then foreground the target app."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_WAIT_MS = 800
    DEFAULT_LAUNCH_BEFORE_SEED_WAIT_MS = 0
    DEFAULT_SMTP_HOST = "127.0.0.1"
    DEFAULT_SMTP_PORT = 3025

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS initialization",
            )

        bundle_id = str(
            params.get("bundle_id")
            or params.get("app_id")
            or params.get("launch_app_bundle_id")
            or ""
        ).strip()
        if not bundle_id:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires params.bundle_id or params.app_id",
            )

        api_base_url = str(params.get("api_base_url") or self.DEFAULT_API_BASE_URL).rstrip("/")
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        seed_after_launch = bool(params.get("seed_after_launch", False))
        launch_before_seed_wait_ms = int(
            params.get("launch_before_seed_wait_ms", self.DEFAULT_LAUNCH_BEFORE_SEED_WAIT_MS) or 0
        )
        purge_greenmail = bool(params.get("purge_greenmail", True))
        seed_messages = self._coerce_seed_messages(params.get("seed_messages"))
        app_data_container_path = str(params.get("app_data_container_path") or "").strip() or None
        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip() or None
        local_purge_result: dict[str, object] = {"applied": False, "reason": "not_started"}
        if not seed_messages:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires non-empty params.seed_messages",
                metadata={"bundle_id": bundle_id, "api_base_url": api_base_url},
            )

        try:
            if hasattr(controller, "terminate_app"):
                controller.terminate_app(bundle_id)
                time.sleep(0.8)

            GreenMailOpenAppInitializer._ensure_greenmail_ready(api_base_url)
            if purge_greenmail:
                GreenMailOpenAppInitializer._purge_greenmail(api_base_url)
            local_purge_result = purge_local_state_for_bundle(
                bundle_id=bundle_id,
                udid=udid,
                app_data_container_path=app_data_container_path,
            )

            if seed_after_launch:
                self._bring_app_to_foreground(controller, bundle_id)
                if launch_before_seed_wait_ms > 0:
                    time.sleep(launch_before_seed_wait_ms / 1000.0)
                for message in seed_messages:
                    self._seed_message(message)
            else:
                for message in seed_messages:
                    self._seed_message(message)
                self._bring_app_to_foreground(controller, bundle_id)

            # New incoming messages can leave the simulator on a notification overlay.
            # Bring the target app back to the foreground so the task starts from the app.
            self._bring_app_to_foreground(controller, bundle_id)

            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare '{bundle_id}' with seeded GreenMail: {type(exc).__name__}: {exc}",
                metadata={
                    "bundle_id": bundle_id,
                    "api_base_url": api_base_url,
                    "purge_greenmail": purge_greenmail,
                    "local_purge_result": local_purge_result,
                    "seeded_message_count": len(seed_messages),
                    "seed_after_launch": seed_after_launch,
                    "launch_before_seed_wait_ms": launch_before_seed_wait_ms,
                    "wait_ms": wait_ms,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Prepared '{bundle_id}' after GreenMail seeding",
            metadata={
                "bundle_id": bundle_id,
                "api_base_url": api_base_url,
                "purge_greenmail": purge_greenmail,
                "local_purge_result": local_purge_result,
                "seeded_message_count": len(seed_messages),
                "seed_after_launch": seed_after_launch,
                "launch_before_seed_wait_ms": launch_before_seed_wait_ms,
                "wait_ms": wait_ms,
            },
        )

    @staticmethod
    def _bring_app_to_foreground(controller: Any, bundle_id: str) -> None:
        if hasattr(controller, "press_home"):
            controller.press_home()
            time.sleep(0.5)
        controller.activate_app(bundle_id)
        time.sleep(0.5)

    @classmethod
    def _coerce_seed_messages(cls, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []

        messages: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            sender_email = str(item.get("sender_email") or "").strip()
            sender_password = str(item.get("sender_password") or "").strip()
            recipient_email = str(item.get("recipient_email") or "").strip()
            subject = str(item.get("subject") or "").strip()
            body = str(item.get("body") or "").strip()
            if not sender_email or not sender_password or not recipient_email or not subject or not body:
                continue
            message: dict[str, Any] = {
                "sender_email": sender_email,
                "sender_password": sender_password,
                "recipient_email": recipient_email,
                "subject": subject,
                "body": body,
                "smtp_host": str(item.get("smtp_host") or cls.DEFAULT_SMTP_HOST).strip(),
                "smtp_port": int(item.get("smtp_port") or cls.DEFAULT_SMTP_PORT),
            }
            chat_version = str(item.get("chat_version") or "").strip()
            if chat_version:
                message["chat_version"] = chat_version
            messages.append(message)
        return messages

    @staticmethod
    def _seed_message(message: Mapping[str, Any]) -> None:
        smtp_host = str(message.get("smtp_host") or GreenMailSeedOpenAppInitializer.DEFAULT_SMTP_HOST).strip()
        smtp_port = int(message.get("smtp_port") or GreenMailSeedOpenAppInitializer.DEFAULT_SMTP_PORT)
        sender_email = str(message.get("sender_email") or "").strip()
        sender_password = str(message.get("sender_password") or "").strip()
        recipient_email = str(message.get("recipient_email") or "").strip()
        subject = str(message.get("subject") or "").strip()
        body = str(message.get("body") or "")

        mime_message = EmailMessage()
        mime_message["From"] = sender_email
        mime_message["To"] = recipient_email
        mime_message["Subject"] = subject
        chat_version = str(message.get("chat_version") or "").strip()
        if chat_version:
            mime_message["Chat-Version"] = chat_version
        mime_message.set_content(body)

        with smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=10.0) as client:
            client.login(sender_email, sender_password)
            client.send_message(mime_message)
