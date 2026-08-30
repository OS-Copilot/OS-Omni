"""Evaluator for the macOS one-plus-one task."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class OnePlusOneEvaluator(BaseEvaluator):
    """Validate that Calculator shows the expected result."""

    EXPECTED_BUNDLE_ID = "com.apple.calculator"

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

        params = dict(context.get("params") or {})
        expected_result = self._normalize_display_text(
            str(params.get("expected_result", params.get("result", "2")))
        )
        actual_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
        ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
        display_values = self._extract_display_values(ui_nodes)

        if actual_bundle_id != self.EXPECTED_BUNDLE_ID:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    f"Expected foreground bundle '{self.EXPECTED_BUNDLE_ID}', "
                    f"got '{actual_bundle_id or 'unknown'}'"
                ),
                metadata={
                    "expected_bundle_id": self.EXPECTED_BUNDLE_ID,
                    "actual_bundle_id": actual_bundle_id,
                    "display_values": display_values,
                },
            )

        if expected_result in display_values:
            return EvalResult(
                status=EvalStatus.PASS,
                message=f"Calculator shows result {expected_result}",
                metadata={
                    "expected_result": expected_result,
                    "display_values": display_values,
                },
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message=f"Calculator does not show expected result {expected_result}",
            metadata={
                "expected_result": expected_result,
                "display_values": display_values,
            },
        )

    @classmethod
    def _extract_display_values(cls, ui_nodes: list[dict[str, Any]]) -> list[str]:
        values: list[str] = []
        for node in ui_nodes:
            node_type = str(node.get("type") or "").strip()
            if node_type != "AXStaticText":
                continue
            text = cls._normalize_display_text(str(node.get("text") or ""))
            if text:
                values.append(text)
        return values

    @staticmethod
    def _normalize_display_text(text: str) -> str:
        cleaned = str(text).replace("\u200e", "").replace("\u200f", "").replace("\ufeff", "")
        return "".join(cleaned.split())
