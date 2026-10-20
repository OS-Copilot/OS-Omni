"""Initializer for single-screen Windows + Android tasks (phone mirrored with scrcpy).

Same order as the Linux version (initializers.linux.android_companion): restore the
companion phone's snapshot and run the Android-side initializer from the host, run the
Windows-side setup steps, then connect the guest to the phone and open its window on
the desktop. See platforms.windows.android_companion.

params:
  android: {initializer_id, params}  initializer run against the phone (host adb)
  windows: {steps: [...]}            DesktopSetupInitializer steps for the guest
  window:  {x, y, height}            scrcpy window geometry on the 1920x1080 desktop
"""

from __future__ import annotations

from typing import Any

from core.init import BaseInitializer
from initializers.linux.android_companion import LinuxAndroidCompanionInitializer
from initializers.windows.setup import DesktopSetupInitializer
from platforms.linux.android_companion import CompanionSettings
from platforms.windows.android_companion import scrcpy_powershell

# Right edge of the desktop, clear of the taskbar at the bottom.
DEFAULT_WINDOW = {"x": 1420, "y": 40, "height": 940}


class WindowsAndroidCompanionInitializer(LinuxAndroidCompanionInitializer):
    DESKTOP = "windows"
    DEFAULT_WINDOW = DEFAULT_WINDOW

    def desktop_setup(self) -> BaseInitializer:
        return DesktopSetupInitializer()

    def open_phone_window(self, controller: Any, settings: CompanionSettings, window: dict[str, int]) -> dict[str, Any]:
        return controller.run_powershell_script(scrcpy_powershell(settings, **window), timeout=200)
