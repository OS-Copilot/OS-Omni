"""Android initializer for the K-9 + GreenMail email benchmark task."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.mail_app_utils import (
    launch_mail_or_chat_app,
    reset_k9_account_if_requested,
)


class K9SendEmailInitializer(BaseInitializer):
    """Prepare the K-9 email task by purging GreenMail and opening K-9."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_APP_PACKAGE = "com.fsck.k9"
    DEFAULT_APP_ACTIVITY = "net.thunderbird.app.common.MainActivity"
    DEFAULT_WAIT_MS = 1500

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

        if not app_package or not app_activity:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package and app_activity",
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

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare K-9 email task: {type(exc).__name__}: {exc}",
                metadata={
                    "api_base_url": api_base_url,
                    "app_package": app_package,
                    "app_activity": app_activity,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="GreenMail purged and K-9 opened",
            metadata={
                "api_base_url": api_base_url,
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "purge_greenmail": purge_greenmail,
                "reset_app_data": bool(params.get("reset_app_data", False)),
            },
        )

    @staticmethod
    def _ensure_greenmail_ready(api_base_url: str) -> None:
        payload = K9SendEmailInitializer._request_json(
            f"{api_base_url}/api/service/readiness",
            method="GET",
        )
        if not isinstance(payload, dict) or payload.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")

    @staticmethod
    def _purge_greenmail(api_base_url: str) -> None:
        K9SendEmailInitializer._request_json(
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
