"""Visible-state evaluator for partially reconstructed Android tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from initializers.android.app_utils import foreground_summary


def _node_value(node: Any, key: str) -> Any:
    if isinstance(node, Mapping):
        return node.get(key)
    return getattr(node, key, None)


class ForegroundTextEvaluator(BaseEvaluator):
    """Check the foreground package and required/forbidden visible UI text."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        app_package = str(params.get("app_package") or "").strip()
        required = [str(value) for value in (params.get("required_text_tokens") or [])]
        required_any = [
            str(value) for value in (params.get("required_any_text_tokens") or [])
        ]
        forbidden = [
            str(value) for value in (params.get("forbidden_text_tokens") or [])
        ]
        case_sensitive = bool(params.get("case_sensitive", False))

        observation = context.get("final_observation")
        if (
            observation is None
            and controller is not None
            and hasattr(controller, "observe")
        ):
            try:
                observation = controller.observe(include_ui_tree=True)
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to observe final Android UI: {type(exc).__name__}: {exc}",
                )
        if observation is None:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="final_observation or controller.observe is required",
            )

        nodes = _node_value(observation, "ui_nodes") or []
        text_parts: list[str] = []
        for node in nodes:
            for key in ("text", "content_description", "content-desc"):
                value = str(_node_value(node, key) or "").strip()
                if value:
                    text_parts.append(value)
        visible_text = "\n".join(text_parts)
        compared_text = visible_text if case_sensitive else visible_text.casefold()

        def present(token: str) -> bool:
            compared = token if case_sensitive else token.casefold()
            return compared in compared_text

        missing = [token for token in required if not present(token)]
        any_matches = [token for token in required_any if present(token)]
        forbidden_matches = [token for token in forbidden if present(token)]

        foreground = ""
        foreground_ok = True
        if app_package:
            if controller is None or not hasattr(controller, "execute_adb"):
                foreground_ok = False
            else:
                try:
                    foreground = foreground_summary(controller)
                    foreground_ok = app_package in foreground
                except Exception:
                    foreground_ok = False

        passed = (
            foreground_ok
            and not missing
            and not forbidden_matches
            and (not required_any or bool(any_matches))
        )
        metadata = {
            "app_package": app_package,
            "foreground": foreground,
            "foreground_ok": foreground_ok,
            "required_text_tokens": required,
            "missing_required": missing,
            "required_any_text_tokens": required_any,
            "matched_required_any": any_matches,
            "forbidden_text_tokens": forbidden,
            "forbidden_matches": forbidden_matches,
            "ui_text_excerpt": visible_text[:4000],
        }
        if passed:
            return EvalResult(
                status=EvalStatus.PASS,
                message="Foreground application and visible text match the expected state",
                metadata=metadata,
            )
        return EvalResult(
            status=EvalStatus.FAIL,
            message="Foreground application or visible text did not match the expected state",
            metadata=metadata,
        )
