"""Evaluator skeleton for the macOS open-calculator task."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class OpenCalculatorEvaluator(BaseEvaluator):
    """Validate the macOS open-calculator task result."""

    EXPECTED_BUNDLE_ID = "com.apple.calculator"
    EXPECTED_IDENTIFIERS = {
        "StandardInputView",
        "AllClear",
        "Divide",
        "Multiply",
        "Add",
        "Equals",
        "Decimal",
    }

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        observation = context.get("final_observation")
        if observation is None:
            controller = context.get("controller")
            if controller is None or not hasattr(controller, "observe"):
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message="final_observation is missing and controller.observe is unavailable",
                )
            observation = controller.observe(include_ui_tree=True)

        actual_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
        ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
        window_titles = self._extract_window_titles(ui_nodes)
        identifiers = self._extract_identifiers(ui_nodes)
        matched_identifiers = sorted(set(identifiers) & self.EXPECTED_IDENTIFIERS)

        if (
            actual_bundle_id == self.EXPECTED_BUNDLE_ID
            and bool(window_titles)
            and len(matched_identifiers) >= 3
        ):
            return EvalResult(
                status=EvalStatus.PASS,
                message="Calculator is open in the foreground",
                metadata={
                    "actual_bundle_id": actual_bundle_id,
                    "window_titles": window_titles,
                    "matched_identifiers": matched_identifiers,
                },
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Calculator is not open in the expected state",
            metadata={
                "actual_bundle_id": actual_bundle_id,
                "window_titles": window_titles,
                "matched_identifiers": matched_identifiers,
            },
        )

    @staticmethod
    def _extract_window_titles(ui_nodes: list[dict[str, Any]]) -> list[str]:
        titles: list[str] = []
        for node in ui_nodes:
            if str(node.get("type") or "").strip() != "AXWindow":
                continue
            title = str(node.get("text") or "").strip()
            if title:
                titles.append(title)
        return titles

    @staticmethod
    def _extract_identifiers(ui_nodes: list[dict[str, Any]]) -> list[str]:
        identifiers: list[str] = []
        for node in ui_nodes:
            identifier = str(node.get("identifier") or "").strip()
            if identifier:
                identifiers.append(identifier)
        return identifiers
