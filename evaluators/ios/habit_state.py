"""Evaluator for Habit tasks backed by the app's Core Data SQLite state."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.ios.habit_store import DEFAULT_BUNDLE_ID, IOSHabitStore


class HabitStateEvaluator(BaseEvaluator):
    DEFAULT_TIMEOUT_SECONDS = 8.0
    DEFAULT_POLL_INTERVAL_SECONDS = 0.5

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

        try:
            store = self._build_store(controller=controller, params=params, bundle_id=bundle_id)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Failed to resolve Habit state store: {type(exc).__name__}: {exc}",
            )

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
                    message=f"Failed to query Habit state: {type(exc).__name__}: {exc}",
                )

            status = str(last_result.get("status") or "").lower()
            if status == "pass":
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Habit local state matches the expected task outcome",
                    metadata={"attempts": attempts, "summary": last_result.get("summary") or {}},
                )

            if time.time() >= deadline:
                break
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Habit local state does not match the expected task outcome",
            metadata={
                "attempts": attempts,
                "failures": last_result.get("failures") or [],
                "summary": last_result.get("summary") or {},
            },
        )

    @staticmethod
    def _build_store(
        *,
        controller: Any,
        params: Mapping[str, Any],
        bundle_id: str,
    ) -> IOSHabitStore:
        db_path = str(params.get("db_path") or "").strip()
        data_container_path = str(params.get("data_container_path") or "").strip()
        if db_path:
            return IOSHabitStore(
                db_path,
                bundle_id=bundle_id,
                data_container_path=data_container_path or None,
            )

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("Habit evaluator needs db_path or a controller with runtime.udid")
        return IOSHabitStore.from_simulator(udid, bundle_id=bundle_id)
