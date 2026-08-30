"""Evaluator for the iOS Action Button silent-mode task."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class ActionButtonSilentEvaluator(BaseEvaluator):
    DEFAULT_BUNDLE_ID = "com.apple.Preferences"
    DEFAULT_TARGET_MODE_TEXTS = ("Silent Mode",)
    BACK_BUTTON_TEXTS = ("Back",)
    PAGE_CONTROLLER_TEXT = "action-button-view-controller"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        final_observation = context.get("final_observation")

        observation = final_observation
        if observation is None:
            if controller is None or not hasattr(controller, "observe"):
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message="final_observation is missing and controller.observe is unavailable",
                )
            observation = controller.observe(include_ui_tree=True)

        params = dict(context.get("params") or {})
        required_bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip()
        accepted_modes = self._resolve_accepted_modes(params)

        actual_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
        if actual_bundle_id != required_bundle_id:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    f"Expected foreground bundle '{required_bundle_id}', "
                    f"got '{actual_bundle_id or 'unknown'}'"
                ),
                metadata={
                    "required_bundle_id": required_bundle_id,
                    "actual_bundle_id": actual_bundle_id,
                },
            )

        ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
        page_ok = self._is_action_button_page(ui_nodes)
        current_mode = self._extract_current_mode_label(ui_nodes)

        if not page_ok:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Expected to be on the Action Button settings page",
                metadata={
                    "actual_bundle_id": actual_bundle_id,
                    "current_mode": current_mode,
                    "has_back_button": self._has_back_button(ui_nodes),
                    "has_page_controller": self._has_page_controller(ui_nodes),
                },
            )

        normalized_mode = self._normalize_text(current_mode)
        if normalized_mode not in accepted_modes:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Action Button is not set to Silent Mode",
                metadata={
                    "actual_bundle_id": actual_bundle_id,
                    "current_mode": current_mode,
                    "accepted_modes": sorted(accepted_modes),
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Action Button is open and set to Silent Mode",
            metadata={
                "actual_bundle_id": actual_bundle_id,
                "current_mode": current_mode,
                "accepted_modes": sorted(accepted_modes),
            },
        )

    def _resolve_accepted_modes(self, params: Mapping[str, Any]) -> set[str]:
        texts: list[str] = []

        expected_mode = str(params.get("expected_mode") or "").strip()
        if expected_mode:
            texts.append(expected_mode)

        raw_expected_modes = params.get("expected_modes")
        if isinstance(raw_expected_modes, list):
            for item in raw_expected_modes:
                text = str(item or "").strip()
                if text:
                    texts.append(text)

        if not texts:
            texts.extend(self.DEFAULT_TARGET_MODE_TEXTS)

        return {self._normalize_text(text) for text in texts if self._normalize_text(text)}

    def _is_action_button_page(self, ui_nodes: list[dict[str, Any]]) -> bool:
        if self._has_page_controller(ui_nodes):
            return True
        return self._has_back_button(ui_nodes) and bool(self._extract_current_mode_label(ui_nodes))

    def _has_page_controller(self, ui_nodes: list[dict[str, Any]]) -> bool:
        wanted = self._normalize_text(self.PAGE_CONTROLLER_TEXT)
        for node in ui_nodes:
            for key in ("text", "selector"):
                value = self._normalize_text(str(node.get(key) or ""))
                if value == wanted:
                    return True
        return False

    def _extract_current_mode_label(self, ui_nodes: list[dict[str, Any]]) -> str:
        candidates: list[str] = []
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
                candidates.append(text)

        for text in candidates:
            if self._normalize_text(text) in {
                self._normalize_text("Silent Mode"),
            }:
                return text

        return candidates[0] if candidates else ""

    def _has_back_button(self, ui_nodes: list[dict[str, Any]]) -> bool:
        wanted = {self._normalize_text(text) for text in self.BACK_BUTTON_TEXTS}
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "Button":
                continue
            rect = node.get("rect") or {}
            node_y = float(rect.get("y", 0.0))
            if node_y > 120.0:
                continue
            text = self._normalize_text(str(node.get("text") or ""))
            selector = self._normalize_text(str(node.get("selector") or ""))
            if text in wanted or selector == self._normalize_text("BackButton"):
                return True
        return False

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text).strip().casefold().split())
