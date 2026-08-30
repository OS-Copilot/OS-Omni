"""Initializers for Android Fossify Calendar + OpenShop cross-app tasks."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.fossify_calendar import FossifyCalendarInitializer
from platforms.android.openshop_support import DEFAULT_APP_ACTIVITY, DEFAULT_APP_PACKAGE, prepare_fresh_openshop


DEFAULT_CALENDAR_PACKAGE = "org.fossify.calendar"


class CalendarShoppingCrossAppInitializer(BaseInitializer):
    """Seed Fossify Calendar, reset OpenShop, then open Calendar for the task start."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Calendar+Shopping initialization",
            )

        openshop_package = str(params.get("openshop_package") or DEFAULT_APP_PACKAGE).strip()
        openshop_activity = str(params.get("openshop_activity") or DEFAULT_APP_ACTIVITY).strip()
        calendar_package = str(params.get("app_package") or DEFAULT_CALENDAR_PACKAGE).strip()
        wait_ms = int(params.get("wait_ms", 1500) or 0)

        calendar_params = {
            "app_package": calendar_package,
            "database_path": params.get("database_path"),
            "timezone": params.get("timezone"),
            "clear_app_data": params.get("clear_calendar_data", True),
            "seed_events": params.get("seed_events") or [],
            "wait_ms": wait_ms,
        }

        try:
            calendar_result = FossifyCalendarInitializer().initialize(
                {
                    **dict(context),
                    "params": calendar_params,
                }
            )
            if calendar_result.status != InitStatus.PASS:
                return calendar_result

            openshop_metadata = prepare_fresh_openshop(
                controller,
                app_package=openshop_package,
                app_activity=openshop_activity,
                clear_app_data=bool(params.get("clear_openshop_data", True)),
                wait_ms=int(params.get("openshop_wait_ms", 1800) or 0),
            )

            controller.execute_adb(["shell", "am", "force-stop", calendar_package])
            controller.execute_adb(
                ["shell", "monkey", "-p", calendar_package, "-c", "android.intent.category.LAUNCHER", "1"]
            )
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Calendar+Shopping task: {type(exc).__name__}: {exc}",
                metadata={
                    "calendar_package": calendar_package,
                    "openshop_package": openshop_package,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Fossify Calendar seeded and OpenShop reset",
            metadata={
                "calendar_package": calendar_package,
                "openshop": openshop_metadata,
                "seed_event_count": len(calendar_params["seed_events"]),
            },
        )
