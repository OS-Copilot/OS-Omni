"""Seed Habit local state, then launch the app."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.ios.habit_store import DEFAULT_BUNDLE_ID, IOSHabitStore, coerce_habit_specs


class HabitSeedOpenAppInitializer(BaseInitializer):
    DEFAULT_WAIT_MS = 1200

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS Habit initialization",
            )

        bundle_id = str(
            params.get("bundle_id")
            or params.get("app_id")
            or params.get("launch_app_bundle_id")
            or DEFAULT_BUNDLE_ID
        ).strip() or DEFAULT_BUNDLE_ID
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        seed_spec = dict(params.get("seed_spec") or {})
        habits = coerce_habit_specs(seed_spec.get("habits"))

        try:
            if hasattr(controller, "terminate_app"):
                controller.terminate_app(bundle_id)
                time.sleep(0.8)

            store = self._build_store(controller=controller, params=params, bundle_id=bundle_id)
            seeded_records = store.reset_habits(habits)
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
                message=f"Failed to prepare Habit: {type(exc).__name__}: {exc}",
                metadata={"bundle_id": bundle_id},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Habit with seeded local state",
            metadata={
                "bundle_id": bundle_id,
                "seeded_habits": len(seeded_records),
                "seeded_titles": [record.title for record in seeded_records],
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
            raise ValueError("Habit initializer needs db_path or a controller with runtime.udid")
        return IOSHabitStore.from_simulator(udid, bundle_id=bundle_id)
