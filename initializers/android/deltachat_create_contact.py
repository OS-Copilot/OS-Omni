"""Android initializer for the Delta Chat create-contact-and-send-message task."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.mail_app_utils import (
    launch_mail_or_chat_app,
    reset_delta_chat_account_if_requested,
)


class DeltaChatCreateContactInitializer(BaseInitializer):
    """Prepare GreenMail and launch Delta Chat for the create-contact task.

    This initializer purges GreenMail (so evaluation starts clean) and
    launches Delta Chat.  It does NOT pre-seed a conversation with the
    target contact — the agent is expected to create the contact itself.
    """

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_APP_PACKAGE = "chat.delta"
    DEFAULT_APP_ACTIVITY = "org.thoughtcrime.securesms.RoutingActivity"
    DEFAULT_WAIT_MS = 2000

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

        try:
            self._ensure_greenmail_ready(api_base_url)
            reset_delta_chat_account_if_requested(
                controller,
                params,
                api_base_url=api_base_url,
            )
            if purge_greenmail:
                self._purge_greenmail(api_base_url)

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
                message=f"Failed to prepare Delta Chat task: {type(exc).__name__}: {exc}",
                metadata={"api_base_url": api_base_url, "app_package": app_package},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="GreenMail purged and Delta Chat opened for create-contact task",
            metadata={
                "api_base_url": api_base_url,
                "app_package": app_package,
                "app_activity": app_activity,
                "reset_app_data": bool(params.get("reset_app_data", False)),
            },
        )

    @staticmethod
    def _ensure_greenmail_ready(api_base_url: str) -> None:
        payload = DeltaChatCreateContactInitializer._request_json(
            f"{api_base_url}/api/service/readiness", method="GET",
        )
        if not isinstance(payload, dict) or payload.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")

    @staticmethod
    def _purge_greenmail(api_base_url: str) -> None:
        DeltaChatCreateContactInitializer._request_json(
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
