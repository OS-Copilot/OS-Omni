"""Combined evaluator for a longer multi-step Maily workflow."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.ios.maily_delete_specific_email import MailyDeleteSpecificEmailEvaluator
from evaluators.ios.maily_forward_specific_email import MailyForwardSpecificEmailEvaluator
from evaluators.ios.maily_send_email import MailySendEmailEvaluator


class MailyMultiStepWorkflowEvaluator(BaseEvaluator):
    """Require delete, forward, and compose actions to all succeed."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        delete_param_groups = self._coerce_param_groups(params.get("delete_params"))
        forward_param_groups = self._coerce_param_groups(params.get("forward_params"))
        send_param_groups = self._coerce_param_groups(params.get("send_params"))

        if not delete_param_groups or not forward_param_groups or not send_param_groups:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires non-empty delete_params, forward_params, and send_params",
            )

        delete_results = self._run_child_group(
            MailyDeleteSpecificEmailEvaluator,
            context=context,
            param_groups=delete_param_groups,
        )
        forward_results = self._run_child_group(
            MailyForwardSpecificEmailEvaluator,
            context=context,
            param_groups=forward_param_groups,
        )
        send_results = self._run_child_group(
            MailySendEmailEvaluator,
            context=context,
            param_groups=send_param_groups,
        )

        if (
            any(result.status is EvalStatus.ERROR for result in delete_results)
            or any(result.status is EvalStatus.ERROR for result in forward_results)
            or any(result.status is EvalStatus.ERROR for result in send_results)
        ):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Multi-step Maily evaluation hit an error",
                metadata={
                    "delete": [result.to_dict() for result in delete_results],
                    "forward": [result.to_dict() for result in forward_results],
                    "send": [result.to_dict() for result in send_results],
                },
            )

        if (
            any(result.status is not EvalStatus.PASS for result in delete_results)
            or any(result.status is not EvalStatus.PASS for result in forward_results)
            or any(result.status is not EvalStatus.PASS for result in send_results)
        ):
            failures: list[str] = []
            failures.extend(self._collect_failures("Delete", delete_results))
            failures.extend(self._collect_failures("Forward", forward_results))
            failures.extend(self._collect_failures("Send", send_results))
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Maily multi-step workflow does not match the expected outcome",
                metadata={
                    "failures": failures,
                    "delete": [result.to_dict() for result in delete_results],
                    "forward": [result.to_dict() for result in forward_results],
                    "send": [result.to_dict() for result in send_results],
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="All required Maily workflow outcomes were observed",
            metadata={
                "delete": [result.to_dict() for result in delete_results],
                "forward": [result.to_dict() for result in forward_results],
                "send": [result.to_dict() for result in send_results],
            },
        )

    @staticmethod
    def _coerce_param_groups(raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, Mapping):
            resolved = dict(raw)
            return [resolved] if resolved else []
        if not isinstance(raw, list):
            return []
        groups: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            resolved = dict(item)
            if resolved:
                groups.append(resolved)
        return groups

    @classmethod
    def _run_child_group(
        cls,
        evaluator_type: type[BaseEvaluator],
        *,
        context: Mapping[str, Any],
        param_groups: list[dict[str, Any]],
    ) -> list[EvalResult]:
        return [
            cls._run_child_evaluator(
                evaluator_type(),
                context=context,
                params=params,
            )
            for params in param_groups
        ]

    @staticmethod
    def _collect_failures(prefix: str, results: list[EvalResult]) -> list[str]:
        failures: list[str] = []
        for index, result in enumerate(results, start=1):
            if result.status is EvalStatus.PASS:
                continue
            label = prefix if len(results) == 1 else f"{prefix} {index}"
            failures.append(f"{label}: {result.message}")
        return failures

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
