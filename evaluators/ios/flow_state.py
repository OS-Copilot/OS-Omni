"""Evaluator for Flow bookkeeping tasks backed by Flow's ObjectBox state."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.ios.flow_store import (
    DEFAULT_BUNDLE_ID,
    DEFAULT_SUBDIRECTORY,
    IOSFlowStore,
    resolve_flow_repo_path,
)


class FlowStateEvaluator(BaseEvaluator):
    DEFAULT_TIMEOUT_SECONDS = 8.0
    DEFAULT_POLL_INTERVAL_SECONDS = 0.5
    APP_RESTART_WAIT_SECONDS = 0.8

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        assert_spec = dict(params.get("assert_spec") or {})
        if not assert_spec:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires non-empty params.assert_spec",
            )

        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )
        bundle_id = str(params.get("bundle_id") or DEFAULT_BUNDLE_ID).strip() or DEFAULT_BUNDLE_ID
        flow_repo_path = str(resolve_flow_repo_path(params.get("flow_repo_path")))

        try:
            store = self._build_store(
                controller=controller,
                params=params,
                bundle_id=bundle_id,
                flow_repo_path=flow_repo_path,
            )
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to resolve Flow state store: {type(exc).__name__}: {exc}",
            )

        was_foreground = self._foreground_matches(controller, bundle_id)
        if controller is not None and hasattr(controller, "terminate_app"):
            try:
                controller.terminate_app(bundle_id)
                time.sleep(self.APP_RESTART_WAIT_SECONDS)
            except Exception:
                pass

        try:
            deadline = time.time() + max(timeout_seconds, 0.0)
            attempts = 0
            last_result: dict[str, Any] = {}

            while True:
                attempts += 1
                try:
                    last_result = store.assert_state(assert_spec)
                except Exception as exc:
                    return EvalResult(
                        status=EvalStatus.ERROR,
                        message=f"Failed to query Flow state: {type(exc).__name__}: {exc}",
                    )

                status = str(last_result.get("status") or "").lower()
                if status == "pass":
                    return EvalResult(
                        status=EvalStatus.PASS,
                        message="Flow ObjectBox state matches the expected task outcome",
                        metadata={"attempts": attempts, "summary": last_result.get("summary") or {}},
                    )

                if time.time() >= deadline:
                    break
                if poll_interval_seconds > 0:
                    time.sleep(poll_interval_seconds)

            return EvalResult(
                status=EvalStatus.FAIL,
                message="Flow ObjectBox state does not match the expected task outcome",
                metadata={
                    "attempts": attempts,
                    "failures": last_result.get("failures") or [],
                    "summary": last_result.get("summary") or {},
                },
            )
        finally:
            if was_foreground and controller is not None and hasattr(controller, "activate_app"):
                try:
                    controller.activate_app(bundle_id)
                    time.sleep(self.APP_RESTART_WAIT_SECONDS)
                except Exception:
                    pass

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
            raise ValueError("Flow evaluator needs app_support_directory or a controller with runtime.udid")
        return IOSFlowStore.from_simulator(
            udid,
            bundle_id=bundle_id,
            flow_repo_path=flow_repo_path,
            subdirectory=subdirectory or DEFAULT_SUBDIRECTORY,
        )

    @staticmethod
    def _foreground_matches(controller: Any, bundle_id: str) -> bool:
        if controller is None or not hasattr(controller, "observe"):
            return False
        try:
            observation = controller.observe(include_ui_tree=False)
        except Exception:
            return False
        foreground_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
        return foreground_bundle_id == bundle_id
