"""Reset Calculator into a deterministic baseline state."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class ResetCalculatorInitializer(BaseInitializer):
    """Launch Calculator and clear its current value back to 0."""

    DEFAULT_APP_NAME = "Calculator"
    DEFAULT_WAIT_MS = 800
    DEFAULT_ESCAPE_COUNT = 2
    DEFAULT_REOPEN_WAIT_MS = 400
    DEFAULT_POST_DRAG_WAIT_MS = 250
    DEFAULT_CLOSE_HOTKEY = "cmd+w"
    DEFAULT_WINDOW_TOP_PADDING = 120
    DEFAULT_MAX_WINDOW_Y = 320
    DEFAULT_TITLE_BAR_OFFSET = 18
    DEFAULT_DRAG_DURATION_MS = 300
    EXPECTED_BUNDLE_ID = "com.apple.calculator"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for macOS initialization",
            )

        app_name = str(params.get("app_name") or self.DEFAULT_APP_NAME).strip() or self.DEFAULT_APP_NAME
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        escape_count = int(params.get("escape_count", self.DEFAULT_ESCAPE_COUNT) or 0)
        reopen_wait_ms = int(params.get("reopen_wait_ms", self.DEFAULT_REOPEN_WAIT_MS) or 0)
        post_drag_wait_ms = int(params.get("post_drag_wait_ms", self.DEFAULT_POST_DRAG_WAIT_MS) or 0)
        window_top_padding = int(params.get("window_top_padding", self.DEFAULT_WINDOW_TOP_PADDING) or 0)
        max_window_y = int(params.get("max_window_y", self.DEFAULT_MAX_WINDOW_Y) or 0)
        title_bar_offset = int(params.get("title_bar_offset", self.DEFAULT_TITLE_BAR_OFFSET) or 0)
        drag_duration_ms = int(params.get("drag_duration_ms", self.DEFAULT_DRAG_DURATION_MS) or 0)
        close_hotkey = str(params.get("close_hotkey") or self.DEFAULT_CLOSE_HOTKEY).strip() or self.DEFAULT_CLOSE_HOTKEY
        expected_display = self._normalize_display_text(str(params.get("expected_display", "0")))

        try:
            self._launch_and_prepare(controller, app_name=app_name, wait_ms=wait_ms, escape_count=escape_count)
            pre_reopen_observation = self._observe(controller)
            pre_reopen_relocation = self._reposition_window_if_needed(
                controller,
                observation=pre_reopen_observation,
                window_top_padding=window_top_padding,
                max_window_y=max_window_y,
                title_bar_offset=title_bar_offset,
                drag_duration_ms=drag_duration_ms,
                post_drag_wait_ms=post_drag_wait_ms,
            )

            controller.execute_action({"type": "hotkey", "keys": close_hotkey}, [])
            if reopen_wait_ms > 0:
                time.sleep(reopen_wait_ms / 1000.0)

            self._launch_and_prepare(controller, app_name=app_name, wait_ms=wait_ms, escape_count=escape_count)
            observation = self._observe(controller)
            post_reopen_relocation = self._reposition_window_if_needed(
                controller,
                observation=observation,
                window_top_padding=window_top_padding,
                max_window_y=max_window_y,
                title_bar_offset=title_bar_offset,
                drag_duration_ms=drag_duration_ms,
                post_drag_wait_ms=post_drag_wait_ms,
            )
            if post_reopen_relocation.get("moved"):
                observation = self._observe(controller)
            relocation = {
                "before_reopen": pre_reopen_relocation,
                "after_reopen": post_reopen_relocation,
            }
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to reset Calculator: {exc}",
                metadata={
                    "app_name": app_name,
                    "wait_ms": wait_ms,
                    "escape_count": escape_count,
                    "window_top_padding": window_top_padding,
                    "max_window_y": max_window_y,
                },
            )

        actual_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
        display_values = self._extract_display_values(list(getattr(observation, "ui_nodes", []) or []))
        final_window = self._extract_window_node(list(getattr(observation, "ui_nodes", []) or []))

        if actual_bundle_id != self.EXPECTED_BUNDLE_ID:
            return InitResult(
                status=InitStatus.FAIL,
                message=(
                    f"Expected foreground bundle '{self.EXPECTED_BUNDLE_ID}', "
                    f"got '{actual_bundle_id or 'unknown'}'"
                ),
                metadata={
                    "app_name": app_name,
                    "actual_bundle_id": actual_bundle_id,
                    "display_values": display_values,
                    "window_position": self._window_position_metadata(final_window),
                },
            )

        if expected_display and expected_display not in display_values:
            return InitResult(
                status=InitStatus.FAIL,
                message=f"Calculator did not reset to expected display {expected_display}",
                metadata={
                    "app_name": app_name,
                    "actual_bundle_id": actual_bundle_id,
                    "display_values": display_values,
                    "window_position": self._window_position_metadata(final_window),
                },
            )

        if final_window is not None and int(final_window.get("y", 0) or 0) > max_window_y:
            return InitResult(
                status=InitStatus.FAIL,
                message=(
                    f"Calculator window baseline is too low: y={int(final_window.get('y', 0) or 0)} "
                    f"(expected <= {max_window_y})"
                ),
                metadata={
                    "app_name": app_name,
                    "actual_bundle_id": actual_bundle_id,
                    "display_values": display_values,
                    "window_position": self._window_position_metadata(final_window),
                    "window_top_padding": window_top_padding,
                    "max_window_y": max_window_y,
                    "relocation": relocation,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Reset '{app_name}' to {expected_display or 'expected baseline'}",
            metadata={
                "app_name": app_name,
                "actual_bundle_id": actual_bundle_id,
                "display_values": display_values,
                "escape_count": escape_count,
                "window_position": self._window_position_metadata(final_window),
                "window_top_padding": window_top_padding,
                "max_window_y": max_window_y,
                "relocation": relocation,
            },
        )

    @staticmethod
    def _observe(controller: Any) -> Any:
        try:
            return controller.observe(include_ui_tree=True, include_screenshot_data=False)
        except TypeError:
            return controller.observe(include_ui_tree=True)

    @classmethod
    def _extract_display_values(cls, ui_nodes: list[dict[str, Any]]) -> list[str]:
        values: list[str] = []
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "AXStaticText":
                continue
            text = cls._normalize_display_text(str(node.get("text") or ""))
            if text:
                values.append(text)
        return values

    @staticmethod
    def _normalize_display_text(text: str) -> str:
        cleaned = str(text).replace("\u200e", "").replace("\u200f", "").replace("\ufeff", "")
        return "".join(cleaned.split())

    @staticmethod
    def _launch_and_prepare(controller: Any, *, app_name: str, wait_ms: int, escape_count: int) -> None:
        if hasattr(controller, "launch_app"):
            controller.launch_app(app_name)
        else:
            controller.execute_action({"type": "launch_app", "app_name": app_name}, [])
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        for _ in range(max(escape_count, 0)):
            controller.execute_action({"type": "keyboard", "action": "escape"}, [])
            time.sleep(0.15)

    @classmethod
    def _extract_window_node(cls, ui_nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        preferred: dict[str, Any] | None = None
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "AXWindow":
                continue
            width = int(node.get("width", 0) or 0)
            height = int(node.get("height", 0) or 0)
            if width <= 0 or height <= 0:
                continue
            if str(node.get("identifier") or "").strip() == "main":
                return node
            preferred = preferred or node
        return preferred

    @classmethod
    def _reposition_window_if_needed(
        cls,
        controller: Any,
        *,
        observation: Any,
        window_top_padding: int,
        max_window_y: int,
        title_bar_offset: int,
        drag_duration_ms: int,
        post_drag_wait_ms: int,
    ) -> dict[str, Any]:
        ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
        window = cls._extract_window_node(ui_nodes)
        if window is None:
            return {"found": False, "moved": False}

        x = int(window.get("x", 0) or 0)
        y = int(window.get("y", 0) or 0)
        width = int(window.get("width", 0) or 0)
        height = int(window.get("height", 0) or 0)

        if y <= max_window_y:
            return {
                "found": True,
                "moved": False,
                "from": cls._window_position_metadata(window),
            }

        screen_width = int(getattr(observation, "width", 0) or 0)
        screen_height = int(getattr(observation, "height", 0) or 0)
        title_bar_offset = max(10, min(title_bar_offset, max(height - 1, 10)))
        target_origin_x = cls._clamp_window_origin(x, size=width, screen_size=screen_width, margin=40)
        target_origin_y = cls._clamp_window_origin(
            window_top_padding,
            size=height,
            screen_size=screen_height,
            margin=40,
        )
        from_target = [x + width // 2, y + title_bar_offset]
        to_target = [target_origin_x + width // 2, target_origin_y + title_bar_offset]
        controller.execute_action(
            {
                "type": "drag",
                "from_target": from_target,
                "to_target": to_target,
                "duration_ms": max(drag_duration_ms, 0),
            },
            ui_nodes,
        )
        if post_drag_wait_ms > 0:
            time.sleep(post_drag_wait_ms / 1000.0)
        return {
            "found": True,
            "moved": True,
            "from": cls._window_position_metadata(window),
            "to": {
                "x": target_origin_x,
                "y": target_origin_y,
                "width": width,
                "height": height,
            },
        }

    @staticmethod
    def _clamp_window_origin(origin: int, *, size: int, screen_size: int, margin: int) -> int:
        if screen_size <= 0 or size <= 0:
            return max(origin, margin)
        max_origin = max(margin, screen_size - size - margin)
        return max(margin, min(origin, max_origin))

    @staticmethod
    def _window_position_metadata(window: dict[str, Any] | None) -> dict[str, int] | None:
        if window is None:
            return None
        return {
            "x": int(window.get("x", 0) or 0),
            "y": int(window.get("y", 0) or 0),
            "width": int(window.get("width", 0) or 0),
            "height": int(window.get("height", 0) or 0),
        }
