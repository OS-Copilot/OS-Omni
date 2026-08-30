"""Seed iOS Contacts data, then open the Contacts app."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.ios.contacts_store import IOSContactsStore, coerce_contact_specs


class ContactsSeedOpenAppInitializer(BaseInitializer):
    DEFAULT_BUNDLE_ID = "com.apple.MobileAddressBook"
    DEFAULT_WAIT_MS = 1200

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS Contacts initialization",
            )

        bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip() or self.DEFAULT_BUNDLE_ID
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        purge_all_contacts = bool(params.get("purge_all_contacts", False))
        purge_contacts = coerce_contact_specs(params.get("purge_contacts"))
        seed_contacts = coerce_contact_specs(params.get("seed_contacts"))
        terminate_warning = ""

        try:
            store = self._build_store(controller=controller, params=params)

            if hasattr(controller, "terminate_app"):
                terminate_warning = self._best_effort_terminate_app(controller, bundle_id)

            if purge_all_contacts:
                deleted_count = store.purge_all_contacts()
            else:
                deleted_count = store.purge_matching_contacts([*purge_contacts, *seed_contacts])

            seeded_rowids = store.seed_contacts(seed_contacts)

            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.5)

            controller.activate_app(bundle_id)
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Contacts app: {type(exc).__name__}: {exc}",
                metadata={
                    "bundle_id": bundle_id,
                    "purge_all_contacts": purge_all_contacts,
                    "seed_contact_count": len(seed_contacts),
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Contacts with seeded benchmark data",
            metadata={
                "bundle_id": bundle_id,
                "deleted_count": deleted_count,
                "seeded_rowids": seeded_rowids,
                "seed_contact_count": len(seed_contacts),
                "purge_all_contacts": purge_all_contacts,
                "terminate_warning": terminate_warning,
            },
        )

    @staticmethod
    def _build_store(controller: Any, params: Mapping[str, Any]) -> IOSContactsStore:
        db_path = str(params.get("db_path") or "").strip()
        if db_path:
            return IOSContactsStore(db_path)

        udid = str(
            params.get("udid")
            or getattr(getattr(controller, "runtime", None), "udid", "")
            or ""
        ).strip()
        if not udid:
            raise ValueError("Contacts initializer needs params.db_path or a controller with runtime.udid")
        return IOSContactsStore.from_simulator(udid)

    @staticmethod
    def _best_effort_terminate_app(controller: Any, bundle_id: str) -> str:
        try:
            controller.terminate_app(bundle_id)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        time.sleep(0.8)
        return ""
