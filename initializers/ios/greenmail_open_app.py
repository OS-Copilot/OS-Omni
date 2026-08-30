"""Open an iOS communication app after resetting GreenMail state."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.ios.greenmail_local_state import purge_local_state_for_bundle


class GreenMailOpenAppInitializer(BaseInitializer):
    """Purge GreenMail, then bring the target iOS app to foreground."""

    DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
    DEFAULT_WAIT_MS = 800

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
        purge_greenmail = bool(params.get("purge_greenmail", True))
        app_data_container_path = str(params.get("app_data_container_path") or "").strip() or None
        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip() or None
        local_purge_result: dict[str, object] = {"applied": False, "reason": "not_started"}

        try:
            if hasattr(controller, "terminate_app"):
                controller.terminate_app(bundle_id)
                time.sleep(0.8)

            if purge_greenmail:
                self._ensure_greenmail_ready(api_base_url)
                self._purge_greenmail(api_base_url)

            local_purge_result = purge_local_state_for_bundle(
                bundle_id=bundle_id,
                udid=udid,
                app_data_container_path=app_data_container_path,
            )

            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.5)
            controller.activate_app(bundle_id)
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare '{bundle_id}': {type(exc).__name__}: {exc}",
                metadata={
                    "bundle_id": bundle_id,
                    "api_base_url": api_base_url,
                    "purge_greenmail": purge_greenmail,
                    "local_purge_result": local_purge_result,
                    "wait_ms": wait_ms,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Prepared '{bundle_id}' after GreenMail setup",
            metadata={
                "bundle_id": bundle_id,
                "api_base_url": api_base_url,
                "purge_greenmail": purge_greenmail,
                "local_purge_result": local_purge_result,
                "wait_ms": wait_ms,
            },
        )

    @staticmethod
    def _ensure_greenmail_ready(api_base_url: str) -> None:
        payload = GreenMailOpenAppInitializer._request_json(
            f"{api_base_url}/api/service/readiness",
            method="GET",
        )
        if not isinstance(payload, dict) or payload.get("message") != "Service running":
            raise RuntimeError(f"GreenMail readiness check failed: {payload!r}")

    @staticmethod
    def _purge_greenmail(api_base_url: str) -> None:
        GreenMailOpenAppInitializer._request_json(
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
