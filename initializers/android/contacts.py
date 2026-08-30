"""Android initializer for clean Contacts tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.app_utils import ensure_package_installed, launch_app_cleanly, wait_for_foreground


class ContactsCleanOpenInitializer(BaseInitializer):
    """Clear Contacts app/provider state and open the contacts list."""

    DEFAULT_APP_PACKAGE = "com.android.contacts"
    DEFAULT_APP_ACTIVITY = "com.android.contacts.activities.PeopleActivity"
    DEFAULT_WAIT_MS = 1000
    DEFAULT_PACKAGE_ACTIVITY_CANDIDATES = (
        ("com.google.android.contacts", "com.google.android.contacts.activities.PeopleActivity"),
        ("com.android.contacts", "com.android.contacts.activities.PeopleActivity"),
    )
    DEFAULT_PROVIDER_PACKAGES = (
        "com.google.android.contacts",
        "com.android.contacts",
        "com.android.providers.contacts",
    )
    DEFAULT_RUNTIME_PERMISSIONS = (
        "android.permission.READ_CONTACTS",
        "android.permission.WRITE_CONTACTS",
        "android.permission.GET_ACCOUNTS",
    )
    DEFAULT_PERMISSION_ALLOW_IDS = (
        "com.android.permissioncontroller:id/permission_allow_button",
        "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
    )
    DEFAULT_PERMISSION_ALLOW_TEXT = ("Allow", "ALLOW", "允许")

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Contacts initialization",
            )

        requested_package = str(params.get("app_package") or "").strip()
        requested_activity = str(params.get("app_activity") or "").strip()
        app_package = requested_package or self.DEFAULT_APP_PACKAGE
        app_activity = requested_activity or self.DEFAULT_APP_ACTIVITY
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        clear_contacts = bool(params.get("clear_contacts", True))
        provider_packages = params.get("provider_packages") or self.DEFAULT_PROVIDER_PACKAGES
        runtime_permissions = params.get("runtime_permissions") or self.DEFAULT_RUNTIME_PERMISSIONS

        try:
            package_candidates: list[tuple[str, str]] = []
            if requested_package:
                package_candidates.append((requested_package, requested_activity))
            for candidate_package, candidate_activity in self.DEFAULT_PACKAGE_ACTIVITY_CANDIDATES:
                if candidate_package != requested_package:
                    package_candidates.append((candidate_package, candidate_activity))

            resolved_package = ""
            resolved_activity = ""
            for candidate_package, candidate_activity in package_candidates:
                package_path = str(controller.execute_adb(["shell", "pm", "path", candidate_package]) or "").strip()
                if "package:" in package_path:
                    resolved_package = candidate_package
                    resolved_activity = requested_activity if candidate_package == requested_package and requested_activity else candidate_activity
                    break

            if not resolved_package:
                ensure_package_installed(controller, app_package, label="Contacts")
                resolved_package = app_package
                resolved_activity = app_activity

            app_package = resolved_package
            app_activity = resolved_activity or app_activity

            for permission in runtime_permissions:
                permission = str(permission or "").strip()
                if not permission:
                    continue
                controller.execute_adb(
                    ["shell", f"pm grant {app_package} {permission} 2>/dev/null || true"]
                )

            cleared_packages: list[str] = []
            if clear_contacts:
                for package in provider_packages:
                    package = str(package or "").strip()
                    if not package:
                        continue
                    controller.execute_adb(["shell", "am", "force-stop", package])
                    controller.execute_adb(["shell", "pm", "clear", package])
                    cleared_packages.append(package)

            ok, focus_output = launch_app_cleanly(
                controller,
                app_package=app_package,
                app_activity=app_activity,
                clear_app_data=False,
                wait_ms=wait_ms,
            )
            if (not ok) and self._looks_like_permission_prompt(focus_output):
                if self._tap_permission_allow(controller):
                    ok, focus_output = wait_for_foreground(
                        controller,
                        app_package,
                        timeout_seconds=10.0,
                    )
                if not ok:
                    ok, focus_output = launch_app_cleanly(
                        controller,
                        app_package=app_package,
                        app_activity=app_activity,
                        clear_app_data=False,
                        wait_ms=wait_ms,
                    )
            if not ok:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=f"Contacts did not become the foreground app: {focus_output or 'no focus output'}",
                    metadata={
                        "app_package": app_package,
                        "app_activity": app_activity,
                        "cleared_packages": cleared_packages,
                    },
                )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Contacts task: {type(exc).__name__}: {exc}",
                metadata={"app_package": app_package, "app_activity": app_activity},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Contacts opened from a clean contacts provider state",
            metadata={
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "clear_contacts": clear_contacts,
            },
        )

    @classmethod
    def _looks_like_permission_prompt(cls, focus_output: str) -> bool:
        text = str(focus_output or "").lower()
        return any(marker in text for marker in ("permissioncontroller", "grantpermissionsactivity"))

    @classmethod
    def _tap_permission_allow(cls, controller: Any) -> bool:
        if not hasattr(controller, "observe"):
            return False
        try:
            observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
        except Exception:
            return False
        ui_nodes = list(getattr(observation, "ui_nodes", None) or [])
        for node in ui_nodes:
            resource_id = str(node.get("resource_id") or node.get("resource-id") or "").strip()
            text = str(node.get("text") or node.get("content_description") or node.get("content-desc") or "").strip()
            if resource_id not in cls.DEFAULT_PERMISSION_ALLOW_IDS and text not in cls.DEFAULT_PERMISSION_ALLOW_TEXT:
                continue
            tap = node.get("tap") or {}
            try:
                x = int(tap.get("x"))
                y = int(tap.get("y"))
            except (TypeError, ValueError):
                continue
            controller.execute_adb(["shell", "input", "tap", str(x), str(y)])
            return True
        return False
