"""Additional Android initializers for Oinkoin benchmark tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.android.oinkoin_support import (
    DEFAULT_APP_ACTIVITY,
    DEFAULT_APP_PACKAGE,
    DEFAULT_WAIT_MS,
    create_record_via_ui,
    prepare_fresh_state,
    seed_state_directly,
)


class _BaseOinkoinInitializer(BaseInitializer):
    def _prepare_common(self, context: Mapping[str, Any]) -> tuple[Any, dict[str, Any]] | InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Oinkoin initialization",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", True))

        if not app_package or not app_activity:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package and app_activity",
            )

        params.update(
            {
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "clear_app_data": clear_app_data,
            }
        )
        return controller, params

    @staticmethod
    def _prepare_fresh_state(controller: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        return prepare_fresh_state(
            controller,
            app_package=str(params["app_package"]),
            app_activity=str(params["app_activity"]),
            clear_app_data=bool(params.get("clear_app_data", True)),
            wait_ms=int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0),
        )


class OinkoinCreateIncomeInitializer(_BaseOinkoinInitializer):
    """Prepare Oinkoin from a fresh state for income creation."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        prepared = self._prepare_common(context)
        if isinstance(prepared, InitResult):
            return prepared

        controller, params = prepared
        try:
            metadata = self._prepare_fresh_state(controller, params)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Oinkoin income task: {type(exc).__name__}: {exc}",
                metadata={
                    "app_package": params["app_package"],
                    "app_activity": params["app_activity"],
                    "clear_app_data": params["clear_app_data"],
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Oinkoin opened from a fresh state for income creation",
            metadata=metadata,
        )


class OinkoinEditExpenseInitializer(_BaseOinkoinInitializer):
    """Prepare Oinkoin with a deterministic expense record ready for editing."""

    DEFAULT_SEED_CATEGORY_NAME = "Food"
    DEFAULT_SEED_AMOUNT = 12.34
    DEFAULT_SEED_TITLE = "Coffee"
    DEFAULT_SEED_NOTE = "old_note"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        prepared = self._prepare_common(context)
        if isinstance(prepared, InitResult):
            return prepared

        controller, params = prepared
        seed_category_name = str(
            params.get("seed_category_name") or self.DEFAULT_SEED_CATEGORY_NAME
        ).strip()
        seed_amount = float(params.get("seed_amount") or self.DEFAULT_SEED_AMOUNT)
        seed_title = str(params.get("seed_title") or self.DEFAULT_SEED_TITLE).strip()
        seed_note = str(params.get("seed_note") or self.DEFAULT_SEED_NOTE).strip()

        try:
            metadata = self._prepare_fresh_state(controller, params)
            create_record_via_ui(
                controller,
                app_package=str(params["app_package"]),
                category_name=seed_category_name,
                amount=seed_amount,
                title=seed_title,
                note=seed_note,
                category_kind="expense",
            )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to seed Oinkoin expense for edit task: {type(exc).__name__}: {exc}",
                metadata={
                    "app_package": params["app_package"],
                    "seed_title": seed_title,
                    "seed_note": seed_note,
                },
            )

        metadata.update(
            {
                "seed_category_name": seed_category_name,
                "seed_amount": seed_amount,
                "seed_title": seed_title,
                "seed_note": seed_note,
            }
        )
        return InitResult(
            status=InitStatus.PASS,
            message="Oinkoin opened with a seeded expense record ready for editing",
            metadata=metadata,
        )


class OinkoinDeleteExpenseInitializer(_BaseOinkoinInitializer):
    """Prepare Oinkoin with a deterministic expense record ready for deletion."""

    DEFAULT_SEED_CATEGORY_NAME = "Food"
    DEFAULT_SEED_AMOUNT = 9.99
    DEFAULT_SEED_TITLE = "Tea"
    DEFAULT_SEED_NOTE = "bench_delete_me"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        prepared = self._prepare_common(context)
        if isinstance(prepared, InitResult):
            return prepared

        controller, params = prepared
        seed_category_name = str(
            params.get("seed_category_name") or self.DEFAULT_SEED_CATEGORY_NAME
        ).strip()
        seed_amount = float(params.get("seed_amount") or self.DEFAULT_SEED_AMOUNT)
        seed_title = str(params.get("seed_title") or self.DEFAULT_SEED_TITLE).strip()
        seed_note = str(params.get("seed_note") or self.DEFAULT_SEED_NOTE).strip()

        try:
            metadata = self._prepare_fresh_state(controller, params)
            create_record_via_ui(
                controller,
                app_package=str(params["app_package"]),
                category_name=seed_category_name,
                amount=seed_amount,
                title=seed_title,
                note=seed_note,
                category_kind="expense",
            )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to seed Oinkoin expense for delete task: {type(exc).__name__}: {exc}",
                metadata={
                    "app_package": params["app_package"],
                    "seed_title": seed_title,
                    "seed_note": seed_note,
                },
            )

        metadata.update(
            {
                "seed_category_name": seed_category_name,
                "seed_amount": seed_amount,
                "seed_title": seed_title,
                "seed_note": seed_note,
            }
        )
        return InitResult(
            status=InitStatus.PASS,
            message="Oinkoin opened with a seeded expense record ready for deletion",
            metadata=metadata,
        )


class OinkoinCreateCustomCategoryAndUseItInitializer(_BaseOinkoinInitializer):
    """Prepare Oinkoin from a fresh state for custom-category creation."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        prepared = self._prepare_common(context)
        if isinstance(prepared, InitResult):
            return prepared

        controller, params = prepared
        seed_categories = [
            dict(item)
            for item in (params.get("seed_categories") or [])
            if isinstance(item, Mapping) and str(item.get("name") or "").strip()
        ]
        seed_records = [
            dict(item)
            for item in (params.get("seed_records") or [])
            if isinstance(item, Mapping) and str(item.get("title") or "").strip()
        ]
        try:
            metadata = self._prepare_fresh_state(controller, params)
            if seed_categories or seed_records:
                metadata.update(
                    seed_state_directly(
                        controller,
                        app_package=str(params["app_package"]),
                        categories=seed_categories,
                        records=seed_records,
                    )
                )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=(
                    "Failed to prepare Oinkoin custom-category task: "
                    f"{type(exc).__name__}: {exc}"
                ),
                metadata={
                    "app_package": params["app_package"],
                    "app_activity": params["app_activity"],
                    "clear_app_data": params["clear_app_data"],
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Oinkoin opened with seeded custom-category distractors",
            metadata=metadata,
        )
