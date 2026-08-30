"""API-backed evaluator for the OpenShop shopping desktop app on macOS."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux.openshop import OpenShopApiEvaluator


class OpenShopMacOSApiEvaluator(BaseEvaluator):
    """Validate session, cart, and order state through OpenShop's local API."""

    DEFAULT_PORT = 4310
    DEFAULT_BUNDLE_ID = "com.killt.openshop"
    DEFAULT_APP_NAME = "OpenShop"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_python_script is required")

        params = dict(context.get("params") or {})
        port = int(params.get("port", self.DEFAULT_PORT) or self.DEFAULT_PORT)
        timeout = int(params.get("timeout", 15) or 15)
        metadata: dict[str, Any] = {}

        try:
            if isinstance(params.get("session"), Mapping):
                session_payload = self._fetch_json(controller, "/api/session", port=port, timeout=timeout)
                metadata["session"] = session_payload
                OpenShopApiEvaluator._validate_session(dict(params["session"]), session_payload)

            if isinstance(params.get("cart"), Mapping):
                cart_payload = self._fetch_json(controller, "/api/cart", port=port, timeout=timeout)
                metadata["cart"] = cart_payload
                OpenShopApiEvaluator._validate_cart(dict(params["cart"]), cart_payload)

            if isinstance(params.get("orders"), Mapping):
                orders_payload = self._fetch_json(controller, "/api/orders", port=port, timeout=timeout)
                metadata["orders"] = orders_payload
                OpenShopApiEvaluator._validate_orders(dict(params["orders"]), orders_payload)

            if isinstance(params.get("benchmark"), Mapping):
                benchmark_payload = self._fetch_json(controller, "/api/benchmark", port=port, timeout=timeout)
                metadata["benchmark"] = benchmark_payload
                self._validate_benchmark(dict(params["benchmark"]), benchmark_payload)

            ui_expectation = params.get("ui")
            if isinstance(ui_expectation, Mapping):
                metadata["ui"] = self._validate_ui_evidence(controller, dict(ui_expectation))
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=metadata)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"OpenShop macOS API evaluation failed: {exc}")

        return EvalResult(status=EvalStatus.PASS, message="OpenShop macOS API evaluation passed", metadata=metadata)

    @staticmethod
    def _fetch_json(controller: Any, path: str, *, port: int, timeout: int) -> Mapping[str, Any]:
        code = f"""
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:{port}{path}", timeout={timeout}) as resp:
    body = resp.read().decode("utf-8")
    print(body)
"""
        result = controller.run_python_script(code, timeout=timeout + 5)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("stdout") or result.get("output") or "").strip()
        if returncode != 0:
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"guest API response was not valid JSON: {exc}: {output}") from exc

    def _validate_benchmark(self, expectation: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        benchmark_mode = str(payload.get("benchmarkMode") or "").strip()
        expected_mode = str(expectation.get("mode") or expectation.get("benchmark_mode") or "").strip()
        if expected_mode:
            assert benchmark_mode == expected_mode, (
                f"expected benchmarkMode={expected_mode!r}, got {benchmark_mode!r}"
            )

        events = list(payload.get("events") or [])
        if "ordered" in expectation:
            ordered = list(expectation.get("ordered") or [])
            cursor = 0
            for index, matcher in enumerate(ordered, start=1):
                assert isinstance(matcher, Mapping), f"benchmark ordered matcher #{index} must be a mapping"
                match_index = self._find_matching_event_index(events, matcher, start=cursor)
                assert match_index is not None, (
                    f"missing benchmark event #{index}: {json.dumps(dict(matcher), ensure_ascii=False)}"
                )
                cursor = match_index + 1

    @classmethod
    def _find_matching_event_index(
        cls,
        events: list[Mapping[str, Any]],
        matcher: Mapping[str, Any],
        *,
        start: int,
    ) -> int | None:
        for index in range(start, len(events)):
            if cls._event_matches(events[index], matcher):
                return index
        return None

    @classmethod
    def _event_matches(cls, event: Mapping[str, Any], matcher: Mapping[str, Any]) -> bool:
        for key, expected in matcher.items():
            actual = event.get(key)
            if isinstance(expected, str):
                if str(actual or "").strip().lower() != expected.strip().lower():
                    return False
                continue
            if isinstance(expected, bool):
                if bool(actual) != expected:
                    return False
                continue
            if isinstance(expected, int) and not isinstance(expected, bool):
                try:
                    if int(actual) != expected:
                        return False
                except (TypeError, ValueError):
                    return False
                continue
            if isinstance(expected, float):
                try:
                    if float(actual) != expected:
                        return False
                except (TypeError, ValueError):
                    return False
                continue
            if actual != expected:
                return False
        return True

    def _validate_ui_evidence(self, controller: Any, expectation: Mapping[str, Any]) -> Mapping[str, Any]:
        if not hasattr(controller, "observe"):
            raise RuntimeError("controller.observe is required for OpenShop UI evaluation")

        observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
        foreground_app = str(getattr(observation, "foreground_app", "") or "")
        foreground_bundle_id = str(getattr(observation, "foreground_bundle_id", "") or "")
        ui_nodes = list(getattr(observation, "ui_nodes", []) or [])

        metadata = {
            "foreground_app": foreground_app,
            "foreground_bundle_id": foreground_bundle_id,
            "ui_node_count": len(ui_nodes),
        }

        require_foreground = bool(expectation.get("require_foreground", False))
        app_names = [
            str(item).strip().lower()
            for item in (expectation.get("app_names") or [self.DEFAULT_APP_NAME])
            if str(item).strip()
        ]
        bundle_ids = [
            str(item).strip().lower()
            for item in (expectation.get("bundle_ids") or [self.DEFAULT_BUNDLE_ID])
            if str(item).strip()
        ]

        if require_foreground:
            fg_name = foreground_app.strip().lower()
            fg_bundle = foreground_bundle_id.strip().lower()
            name_match = any(name in fg_name for name in app_names)
            bundle_match = any(bundle in fg_bundle for bundle in bundle_ids)
            if not (name_match or bundle_match):
                raise AssertionError(
                    "expected OpenShop to remain foreground; observed foreground app="
                    f"{foreground_app!r}, bundle={foreground_bundle_id!r}"
                )

        return metadata
