"""Android initializer for Spotube search-and-play-attempt tasks."""

from __future__ import annotations

import re
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.app_utils import ensure_package_installed
from platforms.android.spotube_support import clear_player_state
from platforms.android.spotube_state import reset_profile_settings_to_baseline


class SpotubeOpenCleanSessionInitializer(BaseInitializer):
    """Launch Spotube after clearing stale runtime signals."""

    DEFAULT_APP_PACKAGE = "oss.krtirtho.spotube"
    DEFAULT_APP_ACTIVITY = "com.ryanheise.audioservice.AudioServiceActivity"
    DEFAULT_WAIT_MS = 2200
    DEFAULT_FOREGROUND_TIMEOUT_SECONDS = 12.0
    DEFAULT_FOREGROUND_POLL_INTERVAL_SECONDS = 0.6
    DEFAULT_CLEAR_EXTERNAL_LOG = True
    DEFAULT_EXTERNAL_LOG_PATH = "/sdcard/Android/data/oss.krtirtho.spotube/files/.spotube_logs"
    DEFAULT_HOME_STABILIZATION_ATTEMPTS = 5
    DEFAULT_HOME_TOP_SCROLLS = 4

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Spotube initialization",
            )

        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or self.DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        foreground_timeout_seconds = float(
            params.get("foreground_timeout_seconds", self.DEFAULT_FOREGROUND_TIMEOUT_SECONDS) or 0.0
        )
        foreground_poll_interval_seconds = float(
            params.get(
                "foreground_poll_interval_seconds",
                self.DEFAULT_FOREGROUND_POLL_INTERVAL_SECONDS,
            )
            or 0.0
        )
        clear_external_log = bool(
            params.get("clear_external_log", self.DEFAULT_CLEAR_EXTERNAL_LOG)
        )
        external_log_path = str(
            params.get("external_log_path") or self.DEFAULT_EXTERNAL_LOG_PATH
        ).strip()
        home_stabilization_attempts = int(
            params.get(
                "home_stabilization_attempts",
                self.DEFAULT_HOME_STABILIZATION_ATTEMPTS,
            )
            or 0
        )
        require_home_stabilization = bool(params.get("require_home_stabilization", False))
        scroll_home_to_top = bool(params.get("scroll_home_to_top", True))
        home_top_scrolls = int(params.get("home_top_scrolls", self.DEFAULT_HOME_TOP_SCROLLS) or 0)
        open_settings_after_launch = bool(params.get("open_settings_after_launch", False))
        require_settings_open = bool(
            params.get("require_settings_open", open_settings_after_launch)
        )
        reset_profile_settings = bool(params.get("reset_profile_settings", False))
        require_profile_reset = bool(
            params.get("require_profile_reset", reset_profile_settings)
        )
        clear_player_state_enabled = bool(params.get("clear_player_state", True))

        if not app_package or not app_activity:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package and app_activity",
            )

        try:
            package_path = ensure_package_installed(controller, app_package, label="Spotube")

            profile_reset_metadata = None
            if reset_profile_settings:
                profile_reset_metadata = reset_profile_settings_to_baseline(
                    controller,
                    app_package=app_package,
                    app_activity=app_activity,
                    wait_ms=wait_ms,
                )
                baseline_status = (
                    profile_reset_metadata.get("baseline_checks", {}).get("status")
                    if isinstance(profile_reset_metadata, dict)
                    else None
                )
                if require_profile_reset and baseline_status != "PASS":
                    return InitResult(
                        status=InitStatus.FAIL,
                        message="Spotube profile baseline reset did not reach the expected non-target state",
                        metadata={
                            "app_package": app_package,
                            "app_activity": app_activity,
                            "profile_reset": profile_reset_metadata,
                        },
                    )

            player_state_metadata = None
            if clear_player_state_enabled:
                player_state_metadata = clear_player_state(
                    controller,
                    app_package=app_package,
                    app_activity=app_activity,
                )

            controller.execute_adb(["shell", "am", "force-stop", app_package])
            if clear_external_log and external_log_path:
                controller.execute_adb(["shell", "rm", "-f", external_log_path])

            start_output = str(
                controller.execute_adb(
                    ["shell", "am", "start", "-n", f"{app_package}/{app_activity}"]
                )
                or ""
            )
            # Some builds reject explicit component launches. Fallback to launcher intent.
            if "Error type" in start_output or "does not exist" in start_output:
                controller.execute_adb(
                    [
                        "shell",
                        "monkey",
                        "-p",
                        app_package,
                        "-c",
                        "android.intent.category.LAUNCHER",
                        "1",
                    ]
                )
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            is_foreground, focus_output = self._wait_for_foreground(
                controller=controller,
                app_package=app_package,
                timeout_seconds=foreground_timeout_seconds,
                poll_interval_seconds=foreground_poll_interval_seconds,
            )
            if not is_foreground:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=(
                        f"Spotube did not become the foreground app: "
                        f"{focus_output or 'no focus/activity output'}"
                    ),
                    metadata={
                        "app_package": app_package,
                        "app_activity": app_activity,
                        "focus_output": focus_output,
                    },
                )
            home_ready = self._stabilize_to_home(
                controller=controller,
                attempts=max(home_stabilization_attempts, 0),
            )
            if require_home_stabilization and not home_ready:
                return InitResult(
                    status=InitStatus.FAIL,
                    message="Spotube foreground is ready, but failed to stabilize on Home tab",
                    metadata={
                        "app_package": app_package,
                        "app_activity": app_activity,
                        "home_stabilization_attempts": home_stabilization_attempts,
                        "require_home_stabilization": require_home_stabilization,
                    },
                )
            if scroll_home_to_top:
                self._prepare_home_top(
                    controller=controller,
                    scrolls=max(home_top_scrolls, 0),
                )
            settings_ready = False
            if open_settings_after_launch:
                settings_ready = self._open_settings_page(controller=controller)
                if require_settings_open and not settings_ready:
                    return InitResult(
                        status=InitStatus.FAIL,
                        message="Spotube foreground is ready, but failed to open Settings page",
                        metadata={
                            "app_package": app_package,
                            "app_activity": app_activity,
                            "open_settings_after_launch": open_settings_after_launch,
                            "require_settings_open": require_settings_open,
                        },
                    )
            else:
                settings_ready = False
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Spotube task: {type(exc).__name__}: {exc}",
                metadata={
                    "app_package": app_package,
                    "app_activity": app_activity,
                    "clear_external_log": clear_external_log,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Spotube opened with a clean media session baseline",
            metadata={
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "foreground_timeout_seconds": foreground_timeout_seconds,
                "foreground_poll_interval_seconds": foreground_poll_interval_seconds,
                "clear_external_log": clear_external_log,
                "external_log_path": external_log_path,
                "home_stabilization_attempts": home_stabilization_attempts,
                "require_home_stabilization": require_home_stabilization,
                "home_stabilized": home_ready,
                "scroll_home_to_top": scroll_home_to_top,
                "home_top_scrolls": home_top_scrolls,
                "open_settings_after_launch": open_settings_after_launch,
                "require_settings_open": require_settings_open,
                "settings_opened": settings_ready,
                "reset_profile_settings": reset_profile_settings,
                "require_profile_reset": require_profile_reset,
                "profile_reset": profile_reset_metadata,
                "clear_player_state": clear_player_state_enabled,
                "player_state_reset": player_state_metadata,
                "package_path": package_path,
            },
        )

    @classmethod
    def _wait_for_foreground(
        cls,
        *,
        controller: Any,
        app_package: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> tuple[bool, str]:
        deadline = time.time() + max(timeout_seconds, 0.0)
        interval = max(poll_interval_seconds, 0.1)
        last_focus_summary = ""

        while True:
            is_foreground, focus_summary = cls._is_foreground(controller=controller, app_package=app_package)
            if is_foreground:
                return True, focus_summary

            last_focus_summary = focus_summary
            if time.time() >= deadline:
                break
            time.sleep(interval)

        return False, last_focus_summary

    @staticmethod
    def _is_foreground(*, controller: Any, app_package: str) -> tuple[bool, str]:
        window_dump = str(controller.execute_adb(["shell", "dumpsys", "window"]) or "")
        activity_dump = str(controller.execute_adb(["shell", "dumpsys", "activity", "activities"]) or "")

        focus_lines: list[str] = []
        for line in window_dump.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                focus_lines.append(line.strip())
        for line in activity_dump.splitlines():
            if "mResumedActivity" in line or "topResumedActivity" in line:
                focus_lines.append(line.strip())

        focus_summary = " | ".join(focus_lines)
        combined = f"{window_dump}\n{activity_dump}"
        return (app_package in combined), focus_summary

    @classmethod
    def _stabilize_to_home(cls, *, controller: Any, attempts: int) -> bool:
        if attempts <= 0:
            return True
        for _ in range(attempts):
            ui_xml = cls._dump_ui_xml(controller=controller)
            if not ui_xml:
                time.sleep(0.25)
                continue
            if cls._has_selected_home(ui_xml):
                return True
            tapped = cls._tap_home_tab(controller=controller, ui_xml=ui_xml)
            if not tapped:
                # Avoid Back fallback here. Back can exit Spotube to launcher.
                # Only do app-internal home-tab taps during stabilization.
                pass
            time.sleep(0.45)
        ui_xml = cls._dump_ui_xml(controller=controller)
        return bool(ui_xml and cls._has_selected_home(ui_xml))

    @staticmethod
    def _dump_ui_xml(*, controller: Any) -> str | None:
        remote_path = "/sdcard/spotube_init_ui.xml"
        with tempfile.TemporaryDirectory(prefix="spotube-init-ui-") as tmpdir:
            local_path = Path(tmpdir) / "spotube_init_ui.xml"
            controller.execute_adb(["shell", "uiautomator", "dump", remote_path])
            controller.execute_adb(["pull", remote_path, str(local_path)])
            if not local_path.exists() or local_path.stat().st_size <= 0:
                return None
            return local_path.read_text(encoding="utf-8", errors="ignore")

    @staticmethod
    def _has_selected_home(ui_xml: str) -> bool:
        try:
            root = ET.fromstring(ui_xml)
        except ET.ParseError:
            return False
        for node in root.iter("node"):
            token = (
                f"{node.attrib.get('text', '')} {node.attrib.get('content-desc', '')}"
            ).strip().lower()
            if "home" in token and str(node.attrib.get("selected", "")).lower() == "true":
                return True
        return False

    @staticmethod
    def _tap_home_tab(*, controller: Any, ui_xml: str) -> bool:
        try:
            root = ET.fromstring(ui_xml)
        except ET.ParseError:
            return False
        candidates: list[tuple[int, int, int]] = []
        display_bottom = 0
        all_bounds: list[tuple[int, int, int, int]] = []
        for node in root.iter("node"):
            bounds = str(node.attrib.get("bounds") or "")
            matched = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not matched:
                continue
            x1, y1, x2, y2 = (int(matched.group(i)) for i in range(1, 5))
            all_bounds.append((x1, y1, x2, y2))
            if y2 > display_bottom:
                display_bottom = y2

        for node in root.iter("node"):
            token = (
                f"{node.attrib.get('text', '')} {node.attrib.get('content-desc', '')}"
            ).strip().lower()
            if "home" not in token:
                continue
            bounds = str(node.attrib.get("bounds") or "")
            matched = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not matched:
                continue
            x1, y1, x2, y2 = (int(matched.group(i)) for i in range(1, 5))
            # Restrict to bottom navigation region to avoid system/launcher "Home".
            if display_bottom > 0 and y1 < int(display_bottom * 0.72):
                continue
            x = (x1 + x2) // 2
            y = (y1 + y2) // 2
            area = max(1, (x2 - x1) * (y2 - y1))
            candidates.append((area, x, y))
        if not candidates:
            return False
        # Prefer the smallest clickable "home" target in bottom nav.
        candidates.sort(key=lambda item: item[0])
        _, x, y = candidates[0]
        controller.execute_adb(["shell", "input", "tap", str(x), str(y)])
        return True

    @classmethod
    def _prepare_home_top(cls, *, controller: Any, scrolls: int) -> None:
        ui_xml = cls._dump_ui_xml(controller=controller)
        if ui_xml and cls._settings_page_visible(ui_xml):
            controller.execute_adb(["shell", "input", "keyevent", "KEYCODE_BACK"])
            time.sleep(0.6)

        ui_xml = cls._dump_ui_xml(controller=controller)
        if ui_xml and not cls._home_top_bar_visible(ui_xml):
            cls._tap_bottom_home(controller=controller)
            time.sleep(0.6)

        width = int(getattr(controller, "width", 1080) or 1080)
        height = int(getattr(controller, "height", 2400) or 2400)
        x = str(width // 2)
        start_y = str(int(height * 0.34))
        end_y = str(int(height * 0.82))
        for _ in range(scrolls):
            controller.execute_adb(["shell", "input", "swipe", x, start_y, x, end_y, "250"])
            time.sleep(0.18)

    @staticmethod
    def _home_top_bar_visible(ui_xml: str) -> bool:
        try:
            root = ET.fromstring(ui_xml)
        except ET.ParseError:
            return False
        tokens = [
            f"{node.attrib.get('text', '')} {node.attrib.get('content-desc', '')}".strip().lower()
            for node in root.iter("node")
        ]
        combined = "\n".join(tokens)
        return "spotube" in combined and "devices" in combined

    @staticmethod
    def _tap_bottom_home(*, controller: Any) -> None:
        width = int(getattr(controller, "width", 1080) or 1080)
        height = int(getattr(controller, "height", 2400) or 2400)
        controller.execute_adb(
            [
                "shell",
                "input",
                "tap",
                str(int(width * 0.15)),
                str(int(height * 0.95)),
            ]
        )

    @classmethod
    def _open_settings_page(cls, *, controller: Any) -> bool:
        for _ in range(4):
            ui_xml = cls._dump_ui_xml(controller=controller)
            if ui_xml and cls._settings_page_visible(ui_xml):
                return True
            if ui_xml and cls._tap_settings_button(controller=controller, ui_xml=ui_xml):
                time.sleep(0.7)
                continue

            width = int(getattr(controller, "width", 1080) or 1080)
            height = int(getattr(controller, "height", 2400) or 2400)
            controller.execute_adb(
                [
                    "shell",
                    "input",
                    "tap",
                    str(int(width * 0.93)),
                    str(int(height * 0.085)),
                ]
            )
            time.sleep(0.7)

        ui_xml = cls._dump_ui_xml(controller=controller)
        return bool(ui_xml and cls._settings_page_visible(ui_xml))

    @staticmethod
    def _settings_page_visible(ui_xml: str) -> bool:
        try:
            root = ET.fromstring(ui_xml)
        except ET.ParseError:
            return False
        tokens = []
        for node in root.iter("node"):
            tokens.append(
                f"{node.attrib.get('text', '')} {node.attrib.get('content-desc', '')}".strip().lower()
            )
        combined = "\n".join(tokens)
        return (
            "settings" in combined
            and (
                "language" in combined
                or "marketplace region" in combined
                or "accent color" in combined
                or "normalize audio" in combined
                or "plugins" in combined
            )
        )

    @staticmethod
    def _tap_settings_button(*, controller: Any, ui_xml: str) -> bool:
        try:
            root = ET.fromstring(ui_xml)
        except ET.ParseError:
            return False

        clickable_candidates: list[tuple[int, int, int, int, int]] = []
        for node in root.iter("node"):
            if str(node.attrib.get("clickable", "")).lower() != "true":
                continue
            bounds = str(node.attrib.get("bounds") or "")
            matched = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not matched:
                continue
            x1, y1, x2, y2 = (int(matched.group(i)) for i in range(1, 5))
            if y1 > 360:
                continue
            # Settings is the rightmost top-bar icon in Spotube.
            clickable_candidates.append((x2, x1, y1, x2, y2))
        if not clickable_candidates:
            return False

        _rank, x1, y1, x2, y2 = sorted(clickable_candidates, reverse=True)[0]
        controller.execute_adb(
            ["shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)]
        )
        return True
