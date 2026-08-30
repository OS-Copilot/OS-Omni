"""Reset selected Safari simulator state, then open Safari."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.ios.safari_store import DEFAULT_BUNDLE_ID, IOSSafariStore, normalize_text, normalize_url


class SafariPrepareOpenAppInitializer(BaseInitializer):
    DEFAULT_WAIT_MS = 1000

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for Safari initialization",
            )

        bundle_id = str(params.get("bundle_id") or DEFAULT_BUNDLE_ID).strip() or DEFAULT_BUNDLE_ID
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        purge_all_history = bool(params.get("purge_all_history", False))
        purge_all_tabs = bool(params.get("purge_all_tabs", False))
        purge_history_urls = self._coerce_url_list(params.get("purge_history_urls"))
        purge_bookmark_urls = self._coerce_url_list(params.get("purge_bookmark_urls"))
        purge_bookmark_titles = self._coerce_text_list(params.get("purge_bookmark_titles"))
        purge_folder_titles = self._coerce_text_list(params.get("purge_folder_titles"))
        purge_tab_urls = self._coerce_url_list(params.get("purge_tab_urls"))
        launch_after_setup = self._coerce_bool(params.get("launch_after_setup"), default=True)
        terminate_after_setup = self._coerce_bool(params.get("terminate_after_setup"), default=False)

        try:
            store = self._build_store(controller=controller, params=params, bundle_id=bundle_id)

            if hasattr(controller, "terminate_app"):
                controller.terminate_app(bundle_id)
                time.sleep(0.8)

            deleted_history_count = store.purge_history(
                urls=purge_history_urls,
                purge_all=purge_all_history,
            )
            deleted_bookmark_count = store.purge_bookmarks(
                titles=purge_bookmark_titles,
                urls=purge_bookmark_urls,
                folder_titles=purge_folder_titles,
            )
            deleted_tab_count = store.purge_tabs(
                urls=purge_tab_urls,
                purge_all=purge_all_tabs,
            )

            if launch_after_setup:
                if hasattr(controller, "press_home"):
                    controller.press_home()
                    time.sleep(0.4)
                controller.activate_app(bundle_id)
                if wait_ms > 0:
                    time.sleep(wait_ms / 1000.0)

                self._dismiss_alerts(controller)

            if terminate_after_setup:
                if hasattr(controller, "terminate_app"):
                    controller.terminate_app(bundle_id)
                    time.sleep(0.5)
                elif hasattr(controller, "press_home"):
                    controller.press_home()
                    time.sleep(0.5)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Safari: {type(exc).__name__}: {exc}",
                metadata={
                    "bundle_id": bundle_id,
                    "purge_all_history": purge_all_history,
                    "purge_all_tabs": purge_all_tabs,
                    "launch_after_setup": launch_after_setup,
                    "terminate_after_setup": terminate_after_setup,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Safari benchmark state",
            metadata={
                "bundle_id": bundle_id,
                "deleted_history_count": deleted_history_count,
                "deleted_bookmark_count": deleted_bookmark_count,
                "deleted_tab_count": deleted_tab_count,
                "purge_all_history": purge_all_history,
                "purge_all_tabs": purge_all_tabs,
                "launch_after_setup": launch_after_setup,
                "terminate_after_setup": terminate_after_setup,
            },
        )

    @staticmethod
    def _build_store(controller: Any, params: Mapping[str, Any], bundle_id: str) -> IOSSafariStore:
        safari_root = str(params.get("safari_root") or "").strip()
        if safari_root:
            return IOSSafariStore(safari_root, bundle_id=bundle_id)

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("Safari initializer needs params.safari_root or a controller with runtime.udid")
        return IOSSafariStore.from_simulator(udid, bundle_id=bundle_id)

    @staticmethod
    def _coerce_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [value for item in raw if (value := normalize_text(item))]

    @staticmethod
    def _coerce_url_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [value for item in raw if (value := normalize_url(item))]

    @staticmethod
    def _coerce_bool(raw: Any, *, default: bool) -> bool:
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().casefold()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return default

    @staticmethod
    def _dismiss_alerts(controller: Any, attempts: int = 2) -> None:
        for _ in range(max(attempts, 0)):
            if hasattr(controller, "alert_dismiss") and controller.alert_dismiss():
                time.sleep(0.6)
                continue
            break
