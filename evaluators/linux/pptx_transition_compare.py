"""PPTX transition evaluator for OSWorld-style Impress tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux.office_path_resolve import resolve_office_file_pair, unlink_if_temp
from platforms.linux.office_metrics.slides import check_transition


class PptxTransitionEvaluator(BaseEvaluator):
    """Check slide transition in a PPTX file using OSWorld-style rules."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        actual = str(params.get("actual_path") or "").strip()
        expected = str(params.get("expected_path") or "").strip()

        if not actual:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.actual_path is required",
            )

        options = params.get("options") or {}
        raw_rules = options.get("rules", {})
        if isinstance(raw_rules, list):
            rules_list = [dict(item) for item in raw_rules if isinstance(item, Mapping)]
        elif isinstance(raw_rules, Mapping):
            rules_list = [dict(raw_rules)]
        else:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.options.rules must be an object or list")
        if not rules_list:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.options.rules must not be empty")

        try:
            actual_path, expected_path, actual_tmp, expected_tmp = resolve_office_file_pair(
                actual,
                expected,
                controller,
                actual_prefix="helloworld_pptx_actual_",
                expected_prefix="helloworld_pptx_expected_",
                actual_suffix=".pptx",
                expected_suffix=".pptx",
            )
        except FileNotFoundError as exc:
            return EvalResult(status=EvalStatus.ERROR, message=str(exc))
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"failed to resolve PPTX paths: {exc}",
            )

        meta = {
            "actual_path": str(actual_path),
            "expected_path": str(expected_path) if expected_path else None,
            "actual_temp": actual_tmp,
            "expected_temp": expected_tmp,
            "rules": rules_list,
        }

        try:
            scores = [
                float(
                    check_transition(
                        str(actual_path),
                        rules={
                            "slide_idx": rule.get("slide_idx", 0),
                            "transition_type": rule.get("transition_type", ""),
                        },
                    )
                )
                for rule in rules_list
            ]
            score = 1.0 if all(item >= 1.0 for item in scores) else 0.0
        except Exception as exc:
            meta["error"] = repr(exc)
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"PPTX transition check raised: {exc}",
                metadata=meta,
            )
        finally:
            unlink_if_temp(actual_path, actual_tmp)
            unlink_if_temp(expected_path, expected_tmp)

        meta["score"] = float(score)
        meta["rule_scores"] = scores
        if float(score) >= 1.0:
            return EvalResult(status=EvalStatus.PASS, message="PPTX transition check passed", metadata=meta)
        return EvalResult(status=EvalStatus.FAIL, message="PPTX transition check failed", metadata=meta)
