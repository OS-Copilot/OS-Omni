"""Combined evaluator for a longer multi-step Delta Chat workflow."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.ios.deltachat_send_message import DeltaChatSendMessageEvaluator


class DeltaChatMultiStepWorkflowEvaluator(BaseEvaluator):
    """Require all expected outbound Delta Chat messages to be delivered."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        forward_params = dict(params.get("forward_params") or {})
        courier_followup_params = dict(params.get("courier_followup_params") or {})
        teammate_notify_params = dict(params.get("teammate_notify_params") or {})
        additional_message_params = params.get("additional_message_params", [])

        if not forward_params or not courier_followup_params or not teammate_notify_params:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=(
                    "evaluation requires non-empty forward_params, "
                    "courier_followup_params, and teammate_notify_params"
                ),
            )

        if additional_message_params is None:
            additional_message_params = []
        if not isinstance(additional_message_params, list):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params additional_message_params must be a list when provided",
            )

        required_messages: list[tuple[str, str, Mapping[str, Any]]] = [
            ("forward", "Forward", forward_params),
            ("courier_followup", "Courier follow-up", courier_followup_params),
            ("teammate_notify", "Teammate notify", teammate_notify_params),
        ]
        for index, item in enumerate(additional_message_params, start=1):
            if not isinstance(item, Mapping) or not item:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=(
                        "evaluation.params additional_message_params entries "
                        "must be non-empty mappings"
                    ),
                    metadata={"invalid_index": index},
                )
            required_messages.append((f"additional_{index}", f"Additional message {index}", dict(item)))

        results: dict[str, EvalResult] = {}
        for key, _label, message_params in required_messages:
            results[key] = self._run_child_evaluator(
                DeltaChatSendMessageEvaluator(),
                context=context,
                params=message_params,
            )

        metadata = self._build_metadata(results)

        if any(result.status is EvalStatus.ERROR for result in results.values()):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Multi-step Delta Chat evaluation hit an error",
                metadata=metadata,
            )

        if any(result.status is not EvalStatus.PASS for result in results.values()):
            failures: list[str] = []
            for key, label, _message_params in required_messages:
                result = results[key]
                if result.status is not EvalStatus.PASS:
                    failures.append(f"{label}: {result.message}")
            metadata["failures"] = failures
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Delta Chat multi-step workflow does not match the expected outcome",
                metadata=metadata,
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="All required Delta Chat workflow outcomes were observed",
            metadata=metadata,
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

    @staticmethod
    def _build_metadata(results: Mapping[str, EvalResult]) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "forward": results["forward"].to_dict(),
            "courier_followup": results["courier_followup"].to_dict(),
            "teammate_notify": results["teammate_notify"].to_dict(),
        }
        additional_results = [
            result.to_dict()
            for key, result in sorted(results.items())
            if key.startswith("additional_")
        ]
        if additional_results:
            metadata["additional_messages"] = additional_results
        return metadata
