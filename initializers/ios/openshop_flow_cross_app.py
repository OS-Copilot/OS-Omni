"""Cross-app initializer for OpenShop + Flow benchmark tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.ios.flow_seed_open_app import FlowSeedOpenAppInitializer
from initializers.ios.openshop_seed_open_app import OpenShopSeedOpenAppInitializer


class OpenShopFlowCrossAppInitializer(BaseInitializer):
    """Seed Flow first, then leave OpenShop open as the starting app."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        params = dict(context.get("params") or {})
        flow_params = dict(params.get("flow_params") or {})
        openshop_params = dict(params.get("openshop_params") or {})

        if not flow_params or not openshop_params:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires non-empty flow_params and openshop_params",
            )

        flow_result = self._run_child_initializer(
            FlowSeedOpenAppInitializer(),
            context=context,
            params=flow_params,
        )
        if flow_result.status is not InitStatus.PASS:
            return InitResult(
                status=flow_result.status,
                message=f"Flow initialization failed: {flow_result.message}",
                metadata={"stage": "flow", "child_metadata": dict(flow_result.metadata)},
            )

        openshop_result = self._run_child_initializer(
            OpenShopSeedOpenAppInitializer(),
            context=context,
            params=openshop_params,
        )
        if openshop_result.status is not InitStatus.PASS:
            return InitResult(
                status=openshop_result.status,
                message=f"OpenShop initialization failed: {openshop_result.message}",
                metadata={"stage": "openshop", "child_metadata": dict(openshop_result.metadata)},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared OpenShop and Flow for the cross-app task",
            metadata={
                "stage": "complete",
                "flow": dict(flow_result.metadata),
                "openshop": dict(openshop_result.metadata),
            },
        )

    @staticmethod
    def _run_child_initializer(
        initializer: BaseInitializer,
        *,
        context: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> InitResult:
        child_context = dict(context)
        child_context["params"] = dict(params)
        return initializer.initialize(child_context)
