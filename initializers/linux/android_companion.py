"""Initializer for single-screen Linux + Android tasks (phone mirrored with scrcpy).

Order: restore the companion phone's snapshot and run the Android-side initializer
from the host, run the Linux-side setup steps, then connect the guest to the phone
and open its window on the desktop. See platforms.linux.android_companion.

params:
  android: {initializer_id, params}  initializer run against the phone (host adb)
  linux:   {steps: [...]}            DesktopSetupInitializer steps for the guest
  window:  {x, y, height}            scrcpy window geometry on the 1920x1080 desktop
"""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from core.init.loader import load_initializer
from initializers.linux.setup import DesktopSetupInitializer
from platforms.android.controller import AdbController
from platforms.linux.android_companion import CompanionSettings, ensure_forward, reset_phone, scrcpy_script

DEFAULT_WINDOW = {"x": 1240, "y": 60, "height": 990}


def phone_controller(settings: CompanionSettings) -> AdbController:
    if settings.adb_port:
        import os

        os.environ["ANDROID_ADB_SERVER_PORT"] = str(settings.adb_port)
    return AdbController(adb_device=settings.serial, adb_path=settings.adb_path)


class LinuxAndroidCompanionInitializer(BaseInitializer):
    # The desktop half: params key, setup initializer, and how the phone window is opened.
    DESKTOP = "linux"
    DEFAULT_WINDOW = DEFAULT_WINDOW

    def desktop_setup(self) -> BaseInitializer:
        return DesktopSetupInitializer()

    def open_phone_window(self, controller: Any, settings: CompanionSettings, window: dict[str, int]) -> dict[str, Any]:
        return controller.run_bash_script(scrcpy_script(settings, **window), timeout=200)

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        metadata: dict[str, Any] = {}
        try:
            settings = CompanionSettings.from_env()
            metadata["phone"] = {"serial": settings.serial, "snapshot": settings.snapshot,
                                 "guest_adb": f"{settings.forward_host}:{settings.forward_port}"}
            ensure_forward(settings)
            reset_phone(settings)
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Companion phone is not ready: {exc}", metadata)

        android = dict(params.get("android") or {})
        if android.get("initializer_id"):
            result = load_initializer(str(android["initializer_id"])).initialize(
                {**context, "controller": phone_controller(settings), "params": dict(android.get("params") or {})})
            metadata["android"] = {"status": result.status.value, "message": result.message}
            if result.status != InitStatus.PASS:
                return InitResult(result.status, f"Android setup failed: {result.message}", metadata)

        desktop = dict(params.get(self.DESKTOP) or {})
        if desktop.get("steps"):
            result = self.desktop_setup().initialize({**context, "params": desktop})
            metadata[self.DESKTOP] = {"status": result.status.value, "message": result.message}
            if result.status != InitStatus.PASS:
                return InitResult(result.status, f"{self.DESKTOP.capitalize()} setup failed: {result.message}", metadata)

        window = {**self.DEFAULT_WINDOW, **dict(params.get("window") or {})}
        reply = self.open_phone_window(controller, settings, window)
        output = str(reply.get("output") or "")
        if "SCRCPY_READY" not in output:
            metadata["scrcpy"] = output[-2000:] + str(reply.get("error") or "")[-2000:]
            return InitResult(InitStatus.ERROR, "The phone window did not open on the desktop", metadata)
        metadata["scrcpy"] = {"window": window}
        return InitResult(InitStatus.PASS, "Companion phone mirrored on the desktop", metadata)
