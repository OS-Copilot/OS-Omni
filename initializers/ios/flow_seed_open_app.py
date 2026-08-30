"""Seed Flow's ObjectBox state, then launch the app."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.ios.flow_store import (
    DEFAULT_BUNDLE_ID,
    DEFAULT_SUBDIRECTORY,
    IOSFlowStore,
    resolve_flow_repo_path,
)


class FlowSeedOpenAppInitializer(BaseInitializer):
    DEFAULT_WAIT_MS = 1200

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS Flow initialization",
            )

        bundle_id = str(
            params.get("bundle_id")
            or params.get("app_id")
            or params.get("launch_app_bundle_id")
            or DEFAULT_BUNDLE_ID
        ).strip() or DEFAULT_BUNDLE_ID
        flow_repo_path = str(resolve_flow_repo_path(params.get("flow_repo_path")))
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        seed_spec = dict(params.get("seed_spec") or {})
        if not seed_spec:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires non-empty params.seed_spec",
                metadata={"bundle_id": bundle_id},
            )

        try:
            if hasattr(controller, "terminate_app"):
                controller.terminate_app(bundle_id)
                time.sleep(0.8)

            store = self._build_store(
                controller=controller,
                params=params,
                bundle_id=bundle_id,
                flow_repo_path=flow_repo_path,
            )
            seed_result = store.seed(seed_spec)
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
                message=f"Failed to prepare Flow: {type(exc).__name__}: {exc}",
                metadata={"bundle_id": bundle_id, "flow_repo_path": flow_repo_path},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Flow with seeded ObjectBox state",
            metadata={
                "bundle_id": bundle_id,
                "flow_repo_path": flow_repo_path,
                "seed_accounts": len(seed_result.get("accounts", []) or []),
                "seed_transactions": len(seed_result.get("transactions", []) or []),
            },
        )

    @staticmethod
    def _build_store(
        *,
        controller: Any,
        params: Mapping[str, Any],
        bundle_id: str,
        flow_repo_path: str,
    ) -> IOSFlowStore:
        app_support_directory = str(params.get("app_support_directory") or "").strip()
        data_container_path = str(params.get("data_container_path") or "").strip()
        subdirectory = str(params.get("subdirectory") or "").strip()
        if app_support_directory:
            return IOSFlowStore(
                flow_repo_path=flow_repo_path,
                bundle_id=bundle_id,
                app_support_directory=app_support_directory,
                data_container_path=data_container_path or None,
                subdirectory=subdirectory or DEFAULT_SUBDIRECTORY,
            )

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("Flow initializer needs app_support_directory or a controller with runtime.udid")
        return IOSFlowStore.from_simulator(
            udid,
            bundle_id=bundle_id,
            flow_repo_path=flow_repo_path,
            subdirectory=subdirectory or DEFAULT_SUBDIRECTORY,
        )
