"""Seed OpenShop local state, then launch the app."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.ios.openshop_store import DEFAULT_BUNDLE_ID, OpenShopStore, coerce_cart_item_specs


class OpenShopSeedOpenAppInitializer(BaseInitializer):
    DEFAULT_WAIT_MS = 1200
    DEFAULT_BOOTSTRAP_WAIT_MS = 1200

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS OpenShop initialization",
            )

        bundle_id = str(
            params.get("bundle_id")
            or params.get("app_id")
            or params.get("launch_app_bundle_id")
            or DEFAULT_BUNDLE_ID
        ).strip() or DEFAULT_BUNDLE_ID
        login_session = bool(params.get("login_session", False))
        cart_items = coerce_cart_item_specs(params.get("cart_items"))
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        bootstrap_webview = bool(params.get("bootstrap_webview", True))
        bootstrap_wait_ms = int(params.get("bootstrap_wait_ms", self.DEFAULT_BOOTSTRAP_WAIT_MS) or 0)
        clear_saved_state = bool(params.get("clear_saved_state", True))

        try:
            if hasattr(controller, "terminate_app"):
                controller.terminate_app(bundle_id)
                time.sleep(0.6)

            if bootstrap_webview:
                OpenShopStore.bootstrap_webview_storage(
                    controller=controller,
                    bundle_id=bundle_id,
                    wait_seconds=max(bootstrap_wait_ms, 0) / 1000.0,
                )

            store = self._build_store(controller=controller, params=params, bundle_id=bundle_id)
            store.reset_state(login_session=login_session, cart_items=cart_items)
            if clear_saved_state:
                store.clear_saved_state()

            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.5)
            controller.activate_app(bundle_id)
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare OpenShop: {type(exc).__name__}: {exc}",
                metadata={
                    "bundle_id": bundle_id,
                    "login_session": login_session,
                    "cart_item_count": len(cart_items),
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared OpenShop with the requested local state",
            metadata={
                "bundle_id": bundle_id,
                "login_session": login_session,
                "cart_item_count": len(cart_items),
                "wait_ms": wait_ms,
            },
        )

    @staticmethod
    def _build_store(controller: Any, params: Mapping[str, Any], bundle_id: str) -> OpenShopStore:
        db_path = str(params.get("db_path") or "").strip()
        seed_data_path = str(params.get("seed_data_path") or "").strip()
        data_container_path = str(params.get("data_container_path") or "").strip()
        if db_path:
            return OpenShopStore(
                db_path,
                bundle_id=bundle_id,
                seed_data_path=seed_data_path or None,
                data_container_path=data_container_path or None,
            )

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("OpenShop initializer needs params.db_path or a controller with runtime.udid")
        return OpenShopStore.from_simulator(udid, bundle_id=bundle_id)
