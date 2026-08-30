"""Evaluator for Android Fossify Calendar + OpenShop cross-app tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.android.fossify_calendar import FossifyCalendarEventStateEvaluator
from evaluators.android.openshop import OpenShopStateEvaluator


class CalendarShoppingCrossAppEvaluator(BaseEvaluator):
    """PASS only when both Calendar and OpenShop expectations pass."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        calendar_params = params.get("calendar") if isinstance(params.get("calendar"), Mapping) else {}
        openshop_params = params.get("openshop") if isinstance(params.get("openshop"), Mapping) else {}

        if not calendar_params or not openshop_params:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.calendar and evaluation.params.openshop are required",
            )

        calendar_result = FossifyCalendarEventStateEvaluator().evaluate(
            {
                **dict(context),
                "params": dict(calendar_params),
            }
        )
        openshop_result = OpenShopStateEvaluator().evaluate(
            {
                **dict(context),
                "params": dict(openshop_params),
            }
        )

        metadata = {
            "calendar": {
                "status": _status_text(calendar_result.status),
                "message": calendar_result.message,
                "metadata": dict(calendar_result.metadata or {}),
            },
            "openshop": {
                "status": _status_text(openshop_result.status),
                "message": openshop_result.message,
                "metadata": dict(openshop_result.metadata or {}),
            },
        }

        if calendar_result.status == EvalStatus.PASS and openshop_result.status == EvalStatus.PASS:
            return EvalResult(
                status=EvalStatus.PASS,
                message="Calendar+Shopping cross-app checks passed",
                metadata=metadata,
            )

        if calendar_result.status == EvalStatus.ERROR or openshop_result.status == EvalStatus.ERROR:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Calendar+Shopping cross-app evaluation hit an error",
                metadata=metadata,
            )

        return EvalResult(
            status=EvalStatus.FAIL,
            message="Calendar+Shopping cross-app checks did not pass",
            metadata=metadata,
        )


def _status_text(value: Any) -> str:
    return str(getattr(value, "value", getattr(value, "name", value)))
