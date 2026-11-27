from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


def _rid(node: Mapping[str, Any]) -> str:
    return str(node.get("resource_id") or node.get("resource-id") or "")


def _text(node: Mapping[str, Any]) -> str:
    return str(node.get("text") or "").strip()


def _desc(node: Mapping[str, Any]) -> str:
    return str(node.get("content_description") or node.get("content-desc") or "").strip()


class CalculatorAdditionEvaluator(BaseEvaluator):
    """Check that the *main* calculator display shows the expected result.

    Google Calculator exposes a *history* row (`history_result`) that can still
    show "46" from a previous session. Counting any `text=="46"` in the tree
    therefore produces false PASS. We only accept a match on the primary
    result preview (`result_preview`).
    """

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        expected = str(params.get("expected_result") or "46").strip()
        if not expected:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.expected_result is empty",
            )

        final_observation = context.get("final_observation")
        controller = context.get("controller")

        if final_observation is None and controller is not None and hasattr(controller, "observe"):
            try:
                final_observation = controller.observe(include_ui_tree=True)
            except Exception:
                pass

        if final_observation is None:
            return EvalResult(
                status=EvalStatus.UNDETERMINED,
                message="No observation available",
            )

        ui_nodes = getattr(final_observation, "ui_nodes", []) or []

        history_hit = False
        preview_text = ""
        preview_desc = ""

        for node in ui_nodes:
            if not isinstance(node, dict):
                continue
            rid = _rid(node)
            t = _text(node)
            d = _desc(node)

            if "history_result" in rid and t == expected:
                history_hit = True

            if "result_preview" in rid or rid.endswith(":id/result"):
                preview_text = t
                preview_desc = d

        # Main display must show the number (not stale history-only).
        if preview_text == expected or (preview_text and expected in preview_text):
            return EvalResult(
                status=EvalStatus.PASS,
                message=f"Expected result {expected!r} found on main display",
                metadata={
                    "result_preview_text": preview_text,
                    "result_preview_desc": preview_desc,
                    "history_also_has_expected": history_hit,
                },
            )

        if history_hit:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=(
                    f"Found {expected!r} only in history, not on main result display "
                    f"(result_preview text={preview_text!r}, desc={preview_desc!r}). "
                    "Clear calculator history or require the agent to compute in-session."
                ),
                metadata={
                    "result_preview_text": preview_text,
                    "result_preview_desc": preview_desc,
                    "history_also_has_expected": True,
                },
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message=(
                f"Result {expected!r} not found on main display "
                f"(result_preview text={preview_text!r})"
            ),
            metadata={
                "result_preview_text": preview_text,
                "result_preview_desc": preview_desc,
                "history_also_has_expected": False,
            },
        )
