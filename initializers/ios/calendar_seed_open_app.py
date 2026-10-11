"""Seed iOS Calendar events, then open Calendar in list mode."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.ios.calendar_store import IOSCalendarStore, coerce_event_specs, default_timezone_name


class CalendarSeedOpenAppInitializer(BaseInitializer):
    DEFAULT_BUNDLE_ID = "com.apple.mobilecal"
    DEFAULT_WAIT_MS = 1200

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS Calendar initialization",
            )

        bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip() or self.DEFAULT_BUNDLE_ID
        timezone_name = str(params.get("timezone") or default_timezone_name()).strip() or default_timezone_name()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        purge_all_events = bool(params.get("purge_all_events", False))
        disable_subscribed_calendars = bool(params.get("disable_subscribed_calendars", False))
        seed_events = coerce_event_specs(params.get("seed_events"))
        purge_summaries = self._coerce_text_list(params.get("purge_summaries"))
        terminate_warning = ""

        try:
            store = self._build_store(controller=controller, params=params, timezone_name=timezone_name)
            all_purge_summaries = sorted({*purge_summaries, *(event.summary for event in seed_events)})

            if hasattr(controller, "terminate_app"):
                terminate_warning = self._best_effort_terminate_app(controller, bundle_id)

            disabled_store_ids = (
                store.disable_subscribed_calendars()
                if disable_subscribed_calendars
                else []
            )
            if purge_all_events:
                deleted_count = store.purge_all_events()
            else:
                deleted_count = store.purge_events_by_summaries(all_purge_summaries)
            seeded_rowids = store.seed_events(seed_events)

            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.5)

            controller.activate_app(bundle_id)
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            # iOS may recreate and sync its built-in subscribed-calendar store
            # when Calendar first launches. Hide that store again after the
            # synchronization service has had its initialization window.
            disabled_store_ids_after_activation = (
                store.disable_subscribed_calendars()
                if disable_subscribed_calendars
                else []
            )

            self._dismiss_alerts(controller)
            self._ensure_month_list_mode(controller)
            self._tap_today_if_available(controller)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Calendar app: {type(exc).__name__}: {exc}",
                metadata={
                    "bundle_id": bundle_id,
                    "timezone": timezone_name,
                    "seed_event_count": len(seed_events),
                    "purge_summary_count": len(purge_summaries),
                    "purge_all_events": purge_all_events,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Calendar with seeded benchmark events",
            metadata={
                "bundle_id": bundle_id,
                "timezone": timezone_name,
                "deleted_count": deleted_count,
                "seeded_rowids": seeded_rowids,
                "seed_event_count": len(seed_events),
                "purge_all_events": purge_all_events,
                "disable_subscribed_calendars": disable_subscribed_calendars,
                "disabled_calendar_store_ids": disabled_store_ids,
                "disabled_calendar_store_ids_after_activation": disabled_store_ids_after_activation,
                "terminate_warning": terminate_warning,
            },
        )

    @staticmethod
    def _coerce_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        values: list[str] = []
        for item in raw:
            text = " ".join(str(item or "").strip().split())
            if text:
                values.append(text)
        return values

    @staticmethod
    def _build_store(controller: Any, params: Mapping[str, Any], timezone_name: str) -> IOSCalendarStore:
        db_path = str(params.get("db_path") or "").strip()
        if db_path:
            return IOSCalendarStore(db_path, timezone_name=timezone_name)

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("Calendar initializer needs params.db_path or a controller with runtime.udid")
        return IOSCalendarStore.from_simulator(udid, timezone_name=timezone_name)

    @staticmethod
    def _observe_ui_nodes(controller: Any) -> list[dict[str, Any]]:
        observation = controller.observe(include_ui_tree=True)
        return list(getattr(observation, "ui_nodes", []) or [])

    @staticmethod
    def _best_effort_terminate_app(controller: Any, bundle_id: str) -> str:
        try:
            controller.terminate_app(bundle_id)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        time.sleep(0.6)
        return ""

    @classmethod
    def _dismiss_alerts(cls, controller: Any, attempts: int = 2) -> None:
        for _ in range(max(attempts, 0)):
            if hasattr(controller, "alert_dismiss") and controller.alert_dismiss():
                time.sleep(0.6)
                continue
            break

    @classmethod
    def _ensure_month_list_mode(cls, controller: Any) -> None:
        ui_nodes = cls._observe_ui_nodes(controller)
        toggle_button = cls._find_first_button(ui_nodes, selector="toggle-month-view")
        if toggle_button is None:
            return

        if str(toggle_button.get("text") or "").strip() == "List":
            return

        controller.execute_action({"type": "tap", "target": toggle_button["id"]}, ui_nodes)
        time.sleep(0.8)

        menu_nodes = cls._observe_ui_nodes(controller)
        list_button = cls._find_first_button(menu_nodes, selector="list-button", text="List")
        if list_button is None:
            return

        controller.execute_action({"type": "tap", "target": list_button["id"]}, menu_nodes)
        time.sleep(0.8)

    @classmethod
    def _tap_today_if_available(cls, controller: Any) -> None:
        ui_nodes = cls._observe_ui_nodes(controller)
        today_button = cls._find_first_button(ui_nodes, text="Today")
        if today_button is None:
            return
        controller.execute_action({"type": "tap", "target": today_button["id"]}, ui_nodes)
        time.sleep(0.5)

    @staticmethod
    def _find_first_button(
        ui_nodes: list[dict[str, Any]],
        *,
        selector: str | None = None,
        text: str | None = None,
    ) -> dict[str, Any] | None:
        wanted_selector = str(selector or "").strip()
        wanted_text = str(text or "").strip()
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Button":
                continue
            if wanted_selector and str(node.get("selector") or "").strip() != wanted_selector:
                continue
            if wanted_text and str(node.get("text") or "").strip() != wanted_text:
                continue
            if str(node.get("id") or "").strip():
                return node
        return None
