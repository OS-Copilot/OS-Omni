from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class PrepareActionButtonNoActionInitializer(BaseInitializer):
    DEFAULT_BUNDLE_ID = "com.apple.Preferences"
    DEFAULT_APP_WAIT_MS = 150
    DEFAULT_NAV_WAIT_MS = 150
    DEFAULT_SWIPE_WAIT_MS = 100
    MAX_NAV_ATTEMPTS = 6
    MAX_SWIPE_ATTEMPTS = 5

    ACTION_BUTTON_TEXTS = ("Action Button",)
    NO_ACTION_TEXTS = ("No Action",)
    BACK_BUTTON_TEXTS = ("Back",)
    ACTION_BUTTON_MODE_TEXTS = (
        "No Action",
        "Silent Mode",
    )

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS initialization",
            )

        bundle_id = str(
            params.get("bundle_id")
            or params.get("app_id")
            or params.get("launch_app_bundle_id")
            or self.DEFAULT_BUNDLE_ID
        ).strip()
        app_wait_ms = self.DEFAULT_APP_WAIT_MS
        nav_wait_ms = self.DEFAULT_NAV_WAIT_MS
        swipe_wait_ms = self.DEFAULT_SWIPE_WAIT_MS

        try:
            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.35)

            controller.activate_app(bundle_id)
            if app_wait_ms > 0:
                time.sleep(app_wait_ms / 1000.0)

            page_error = self._ensure_action_button_page(controller, wait_ms=nav_wait_ms)
            if page_error is not None:
                return page_error

            set_error = self._ensure_no_action_selected(controller, wait_ms=swipe_wait_ms)
            if set_error is not None:
                return set_error

            back_error = self._return_to_settings_home(controller, wait_ms=nav_wait_ms)
            if back_error is not None:
                return back_error

            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.35)

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Action Button state: {exc}",
                metadata={"bundle_id": bundle_id},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Action Button state as 'No Action' and returned to Home",
            metadata={"bundle_id": bundle_id, "target_state": "No Action"},
        )

    def _ensure_action_button_page(
        self,
        controller: Any,
        *,
        wait_ms: int,
    ) -> InitResult | None:
        for _ in range(self.MAX_NAV_ATTEMPTS):
            ui_nodes = self._observe_ui_nodes(controller)
            if self._is_action_button_page(ui_nodes):
                return None

            target_node = self._find_node_by_texts(ui_nodes, self.ACTION_BUTTON_TEXTS)
            if target_node is not None:
                tap_result = controller.execute_action(
                    {"type": "tap", "target": target_node["id"]},
                    ui_nodes,
                )
                if not bool(tap_result.get("success")):
                    return InitResult(
                        status=InitStatus.FAIL,
                        message="Failed to open Action Button settings page",
                        metadata={"action_result": tap_result, "target_node": target_node},
                    )
                if wait_ms > 0:
                    time.sleep(wait_ms / 1000.0)
                continue

            back_button = self._find_back_button(ui_nodes)
            if back_button is not None and not self._looks_like_settings_root(ui_nodes):
                tap_result = controller.execute_action(
                    {"type": "tap", "target": back_button["id"]},
                    ui_nodes,
                )
                if not bool(tap_result.get("success")):
                    return InitResult(
                        status=InitStatus.FAIL,
                        message="Failed to navigate back while searching for Action Button page",
                        metadata={"action_result": tap_result, "back_button": back_button},
                    )
                if wait_ms > 0:
                    time.sleep(wait_ms / 1000.0)
                continue

            break

        ui_nodes = self._observe_ui_nodes(controller)
        return InitResult(
            status=InitStatus.FAIL,
            message="Could not reach Action Button settings page",
            metadata={"ui_node_count": len(ui_nodes)},
        )

    def _ensure_no_action_selected(
        self,
        controller: Any,
        *,
        wait_ms: int,
    ) -> InitResult | None:
        preferred_direction = "right"

        for _ in range(self.MAX_SWIPE_ATTEMPTS):
            ui_nodes = self._observe_ui_nodes(controller)
            if self._contains_any_text(ui_nodes, self.NO_ACTION_TEXTS):
                return None

            scroll_node = self._find_action_button_scroll_view(ui_nodes)
            if scroll_node is None:
                return InitResult(
                    status=InitStatus.FAIL,
                    message="Could not find Action Button scroll view",
                )

            previous_label = self._extract_current_mode_label(ui_nodes)
            swipe_error, next_label, used_direction = self._advance_until_mode_changes(
                controller=controller,
                node=scroll_node,
                ui_nodes=ui_nodes,
                previous_label=previous_label,
                wait_ms=wait_ms,
                preferred_direction=preferred_direction,
            )
            if swipe_error is not None:
                return swipe_error
            preferred_direction = used_direction or preferred_direction

            next_nodes = self._observe_ui_nodes(controller)
            if self._contains_any_text(next_nodes, self.NO_ACTION_TEXTS):
                return None

            if previous_label and next_label and previous_label == next_label:
                return InitResult(
                    status=InitStatus.FAIL,
                    message="Action Button swipe did not change the current mode",
                    metadata={
                        "current_mode": previous_label,
                        "hint": "Swipe likely missed the active carousel area; adjust drag coordinates or direction.",
                    },
                )

        ui_nodes = self._observe_ui_nodes(controller)
        return InitResult(
            status=InitStatus.FAIL,
            message="Could not switch Action Button to 'No Action'",
            metadata={"ui_node_count": len(ui_nodes)},
        )

    def _advance_until_mode_changes(
        self,
        *,
        controller: Any,
        node: dict[str, Any],
        ui_nodes: list[dict[str, Any]],
        previous_label: str,
        wait_ms: int,
        preferred_direction: str,
    ) -> tuple[InitResult | None, str, str | None]:
        directions = [preferred_direction]
        fallback_direction = "left" if preferred_direction == "right" else "right"
        if fallback_direction not in directions:
            directions.append(fallback_direction)

        for direction in directions:
            swipe_error = self._advance_in_scroll_view(
                controller=controller,
                node=node,
                ui_nodes=ui_nodes,
                direction=direction,
            )
            if swipe_error is not None:
                return swipe_error, previous_label, None
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            next_nodes = self._observe_ui_nodes(controller)
            next_label = self._extract_current_mode_label(next_nodes)
            if next_label and next_label != previous_label:
                return None, next_label, direction

        return (
            InitResult(
                status=InitStatus.FAIL,
                message="Action Button swipe did not change the current mode",
                metadata={
                    "current_mode": previous_label,
                    "hint": "Tried both swipe directions but the active mode did not change.",
                },
            ),
            previous_label,
            None,
        )

    def _return_to_settings_home(
        self,
        controller: Any,
        *,
        wait_ms: int,
    ) -> InitResult | None:
        ui_nodes = self._observe_ui_nodes(controller)
        back_button = self._find_back_button(ui_nodes)
        if back_button is None:
            return InitResult(
                status=InitStatus.FAIL,
                message="Could not find back button on Action Button page",
            )

        tap_result = controller.execute_action(
            {"type": "tap", "target": back_button["id"]},
            ui_nodes,
        )
        if not bool(tap_result.get("success")):
            return InitResult(
                status=InitStatus.FAIL,
                message="Failed to return to Settings home",
                metadata={"action_result": tap_result, "back_button": back_button},
            )
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
        return None

    def _advance_in_scroll_view(
        self,
        *,
        controller: Any,
        node: dict[str, Any],
        ui_nodes: list[dict[str, Any]],
        direction: str,
    ) -> InitResult | None:
        try:
            action_result = controller.execute_action(
                {
                    "type": "scroll",
                    "direction": direction,
                    "distance": 0.75,
                    "target": node["id"],
                    "duration_ms": 220,
                },
                ui_nodes,
            )
            if bool(action_result.get("success")):
                return None
        except Exception:
            pass

        return self._drag_in_node(
            controller=controller,
            node=node,
            direction=direction,
        )

    def _drag_in_node(
        self,
        *,
        controller: Any,
        node: dict[str, Any],
        direction: str,
    ) -> InitResult | None:
        rect = node.get("rect") or {}
        try:
            x = float(rect["x"])
            y = float(rect["y"])
            w = float(rect["w"])
            h = float(rect["h"])
        except Exception:
            return InitResult(
                status=InitStatus.FAIL,
                message="Action Button scroll view does not have a usable rect",
                metadata={"node": node},
            )

        if str(direction).strip().lower() == "left":
            start_x = int(x + w * 0.82)
            end_x = int(x + w * 0.16)
        else:
            start_x = int(x + w * 0.20)
            end_x = int(x + w * 0.88)

        if h >= 700:
            center_y = int(y + h * 0.46)
        elif h >= 260:
            center_y = int(y + h * 0.30)
        else:
            center_y = int(y + h * 0.50)

        try:
            controller.drag_px(start_x, center_y, end_x, center_y, duration_s=0.32)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to swipe Action Button control: {exc}",
                metadata={"node": node},
            )
        return None

    def _observe_ui_nodes(self, controller: Any) -> list[dict[str, Any]]:
        observation = controller.observe(include_ui_tree=True)
        return list(getattr(observation, "ui_nodes", []) or [])

    def _is_action_button_page(self, ui_nodes: list[dict[str, Any]]) -> bool:
        controller_node = self._find_node_by_exact_texts(
            ui_nodes,
            ("action-button-view-controller",),
        )
        if controller_node is not None:
            return True

        has_mode_label = self._contains_any_text(ui_nodes, self.ACTION_BUTTON_MODE_TEXTS)
        has_back_button = self._find_back_button(ui_nodes) is not None
        return has_mode_label and has_back_button

    def _looks_like_settings_root(self, ui_nodes: list[dict[str, Any]]) -> bool:
        return self._find_node_by_texts(ui_nodes, self.ACTION_BUTTON_TEXTS) is not None

    def _find_action_button_scroll_view(
        self,
        ui_nodes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for node in ui_nodes:
            selector = self._normalize_text(str(node.get("selector") or node.get("text") or ""))
            if selector == self._normalize_text("action-button-view-controller"):
                return node

        best_node: dict[str, Any] | None = None
        best_area = -1.0

        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "ScrollView":
                continue
            rect = node.get("rect") or {}
            try:
                area = float(rect.get("w", 0.0)) * float(rect.get("h", 0.0))
            except Exception:
                area = 0.0
            if area > best_area:
                best_area = area
                best_node = node
        return best_node

    def _find_back_button(self, ui_nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        wanted = {self._normalize_text(text) for text in self.BACK_BUTTON_TEXTS}
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Button":
                continue
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector == self._normalize_text("BackButton"):
                return node
        return None

    def _find_node_by_texts(
        self,
        ui_nodes: list[dict[str, Any]],
        texts: tuple[str, ...],
    ) -> dict[str, Any] | None:
        wanted = {self._normalize_text(text) for text in texts}
        for node in ui_nodes:
            for key in ("text", "selector"):
                value = self._normalize_text(str(node.get(key) or ""))
                if value in wanted:
                    return node
        return None

    def _find_node_by_exact_texts(
        self,
        ui_nodes: list[dict[str, Any]],
        texts: tuple[str, ...],
    ) -> dict[str, Any] | None:
        wanted = {self._normalize_text(text) for text in texts}
        for node in ui_nodes:
            for key in ("text", "selector"):
                raw_value = str(node.get(key) or "").strip()
                if self._normalize_text(raw_value) in wanted:
                    return node
        return None

    def _contains_any_text(
        self,
        ui_nodes: list[dict[str, Any]],
        texts: tuple[str, ...],
    ) -> bool:
        wanted = {self._normalize_text(text) for text in texts}
        for node in ui_nodes:
            for key in ("text", "selector"):
                value = self._normalize_text(str(node.get(key) or ""))
                if value in wanted:
                    return True
        return False

    def _extract_current_mode_label(self, ui_nodes: list[dict[str, Any]]) -> str:
        for node in ui_nodes:
            node_type = str(node.get("type") or "").strip()
            if node_type not in {"PageIndicator", "StaticText"}:
                continue
            text = str(node.get("text") or node.get("selector") or "").strip()
            normalized = self._normalize_text(text)
            if normalized in {
                self._normalize_text("No Action"),
                self._normalize_text("Silent Mode"),
            }:
                return text
        return ""

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text).strip().casefold().split())
