"""Cross-app evaluator for OpenShop + Flow benchmark tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.ios.flow_state import FlowStateEvaluator
from evaluators.ios.openshop_state import OpenShopStateEvaluator


class OpenShopFlowCrossAppEvaluator(BaseEvaluator):
    """Require both OpenShop order state and Flow ledger state to match."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        openshop_params = dict(params.get("openshop_params") or {})
        flow_params = dict(params.get("flow_params") or {})

        if not openshop_params or not flow_params:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires non-empty openshop_params and flow_params",
            )

        openshop_result = self._run_child_evaluator(
            OpenShopStateEvaluator(),
            context=context,
            params=openshop_params,
        )
        flow_result = self._run_child_evaluator(
            FlowStateEvaluator(),
            context=context,
            params=flow_params,
        )

        if openshop_result.status is EvalStatus.ERROR or flow_result.status is EvalStatus.ERROR:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Cross-app OpenShop/Flow evaluation hit an error",
                metadata={
                    "openshop": openshop_result.to_dict(),
                    "flow": flow_result.to_dict(),
                },
            )

        if openshop_result.status is not EvalStatus.PASS or flow_result.status is not EvalStatus.PASS:
            failures: list[str] = []
            if openshop_result.status is not EvalStatus.PASS:
                failures.append(f"OpenShop: {openshop_result.message}")
            if flow_result.status is not EvalStatus.PASS:
                failures.append(f"Flow: {flow_result.message}")
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Cross-app OpenShop/Flow state does not match the expected outcome",
                metadata={
                    "failures": failures,
                    "openshop": openshop_result.to_dict(),
                    "flow": flow_result.to_dict(),
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="OpenShop and Flow both match the expected cross-app outcome",
            metadata={
                "openshop": openshop_result.to_dict(),
                "flow": flow_result.to_dict(),
            },
        )

    @staticmethod
    def _run_child_evaluator(
        evaluator: BaseEvaluator,
        *,
        context: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> EvalResult:
        child_context = dict(context)
        child_context["params"] = dict(params)
        return evaluator.evaluate(child_context)
