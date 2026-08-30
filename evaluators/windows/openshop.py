"""API-backed evaluator for the OpenShop shopping desktop app on Windows."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux.openshop import OpenShopApiEvaluator as LinuxOpenShopApiEvaluator


class OpenShopApiEvaluator(BaseEvaluator):
    """Validate session, cart, and order state through OpenShop's local API."""

    DEFAULT_PORT = 4310

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_python_script is required")

        params = dict(context.get("params") or {})
        port = int(params.get("port", self.DEFAULT_PORT) or self.DEFAULT_PORT)
        timeout = float(params.get("timeout", 10) or 10)
        poll_interval = float(params.get("poll_interval", 0.5) or 0.5)
        metadata: dict[str, Any] = {}

        last_assertion: AssertionError | None = None
        last_exception: Exception | None = None
        deadline = time.time() + max(timeout, 0.1)
        while True:
            try:
                metadata = self._evaluate_api_expectations(controller, params, port=port)
                last_assertion = None
                last_exception = None
                break
            except AssertionError as exc:
                last_assertion = exc
            except Exception as exc:
                last_exception = exc

            if time.time() >= deadline:
                break
            time.sleep(poll_interval)

        if last_assertion is not None:
            return EvalResult(status=EvalStatus.FAIL, message=str(last_assertion), metadata=metadata)
        if last_exception is not None:
            return EvalResult(status=EvalStatus.ERROR, message=f"OpenShop API evaluation failed: {last_exception}")

        try:
            ui_expectation = params.get("ui")
            if isinstance(ui_expectation, Mapping):
                ui_metadata = self._validate_ui_evidence(controller, dict(ui_expectation))
                metadata["ui"] = ui_metadata
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=metadata)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"OpenShop UI evaluation failed: {exc}")

        return EvalResult(status=EvalStatus.PASS, message="OpenShop API evaluation passed", metadata=metadata)

    def _evaluate_api_expectations(
        self,
        controller: Any,
        params: Mapping[str, Any],
        *,
        port: int,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if isinstance(params.get("session"), Mapping):
            session_payload = self._fetch_json(controller, f"/api/session", port=port)
            metadata["session"] = session_payload
            LinuxOpenShopApiEvaluator._validate_session(dict(params["session"]), session_payload)

        if isinstance(params.get("cart"), Mapping):
            cart_payload = self._fetch_json(controller, f"/api/cart", port=port)
            metadata["cart"] = cart_payload
            LinuxOpenShopApiEvaluator._validate_cart(dict(params["cart"]), cart_payload)

        if isinstance(params.get("orders"), Mapping):
            orders_payload = self._fetch_json(controller, f"/api/orders", port=port)
            metadata["orders"] = orders_payload
            LinuxOpenShopApiEvaluator._validate_orders(dict(params["orders"]), orders_payload)

        if isinstance(params.get("benchmark_events"), list):
            benchmark_payload = self._fetch_json(controller, f"/api/benchmark", port=port)
            metadata["benchmark"] = benchmark_payload
            LinuxOpenShopApiEvaluator._validate_benchmark_events(list(params["benchmark_events"]), benchmark_payload)

        if isinstance(params.get("benchmark_event_sequence"), list):
            benchmark_payload = metadata.get("benchmark") or self._fetch_json(controller, f"/api/benchmark", port=port)
            metadata["benchmark"] = benchmark_payload
            LinuxOpenShopApiEvaluator._validate_benchmark_event_sequence(
                list(params["benchmark_event_sequence"]),
                benchmark_payload,
            )

        return metadata

    @staticmethod
    def _validate_ui_evidence(controller: Any, expectation: Mapping[str, Any]) -> Mapping[str, Any]:
        process_names = [
            str(item).strip()
            for item in (expectation.get("process_names") or [])
            if str(item).strip()
        ]
        window_keywords = [
            str(item).strip().lower()
            for item in (expectation.get("window_keywords") or [])
            if str(item).strip()
        ]
        require_foreground = bool(expectation.get("require_foreground", False))
        require_window = bool(expectation.get("require_window", True))

        ui_metadata: dict[str, Any] = {}

        if hasattr(controller, "run_powershell_script"):
            quoted_process_names = []
            for name in process_names:
                quoted_process_names.append("'" + name.replace("'", "''") + "'")
            ps_process_names = ",".join(quoted_process_names)
            script = f"""
$ErrorActionPreference = "Stop"
$targets = @({ps_process_names})
$procs = @()
foreach ($name in $targets) {{
  $procs += Get-Process -Name $name -ErrorAction SilentlyContinue
}}
$procs = $procs | Sort-Object Id -Unique
$visible = @(
  $procs |
  Where-Object {{ $_.MainWindowHandle -ne 0 -and -not [string]::IsNullOrWhiteSpace($_.MainWindowTitle) }} |
  ForEach-Object {{
    [pscustomobject]@{{
      process_name = $_.ProcessName
      pid = $_.Id
      window_title = $_.MainWindowTitle
    }}
  }}
)
$payload = [pscustomobject]@{{
  visible_count = $visible.Count
  windows = $visible
}}
$payload | ConvertTo-Json -Depth 4 -Compress
"""
            result = controller.run_powershell_script(script, timeout=20)
            returncode = int(result.get("returncode", -1))
            output = str(result.get("output", "")).strip()
            if returncode != 0:
                raise RuntimeError(output or f"guest PowerShell failed with exit code {returncode}")
            try:
                ui_metadata["process_check"] = json.loads(output)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"guest process/window output was not valid JSON: {exc}: {output}") from exc

            process_check = dict(ui_metadata.get("process_check") or {})
            visible_windows = process_check.get("windows") or []
            if require_window and not visible_windows:
                raise AssertionError(
                    f"expected a visible OpenShop desktop window for process names {process_names}, got none"
                )

        observation = None
        if hasattr(controller, "observe"):
            try:
                observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            except Exception as exc:  # pragma: no cover - best-effort metadata capture
                ui_metadata["observation_error"] = str(exc)
            else:
                ui_metadata["foreground_app"] = str(getattr(observation, "foreground_app", "") or "")
                ui_metadata["foreground_window"] = str(getattr(observation, "foreground_window", "") or "")
                ui_metadata["ui_node_count"] = len(list(getattr(observation, "ui_nodes", []) or []))

        if require_foreground:
            foreground_tokens = [
                str(ui_metadata.get("foreground_app", "") or "").lower(),
                str(ui_metadata.get("foreground_window", "") or "").lower(),
            ]
            process_windows = ui_metadata.get("process_check") or {}
            for item in process_windows.get("windows") or []:
                foreground_tokens.append(str((item or {}).get("window_title") or "").lower())
                foreground_tokens.append(str((item or {}).get("process_name") or "").lower())

            name_matches = [name.lower() for name in process_names]
            if not any(any(name in token for name in name_matches) for token in foreground_tokens if token):
                raise AssertionError(
                    f"expected OpenShop to remain visible/foreground; observed foreground app="
                    f"{ui_metadata.get('foreground_app')!r}, window={ui_metadata.get('foreground_window')!r}"
                )

        if window_keywords:
            all_window_text = []
            all_window_text.append(str(ui_metadata.get("foreground_window", "") or "").lower())
            process_check = ui_metadata.get("process_check") or {}
            for item in process_check.get("windows") or []:
                all_window_text.append(str((item or {}).get("window_title") or "").lower())
            if not any(any(keyword in text for keyword in window_keywords) for text in all_window_text if text):
                raise AssertionError(
                    f"expected an OpenShop window containing one of {window_keywords}, observed {all_window_text}"
                )

        return ui_metadata

    @staticmethod
    def _fetch_json(controller: Any, path: str, *, port: int) -> Mapping[str, Any]:
        code = f"""
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:{port}{path}", timeout=10) as resp:
    body = resp.read().decode("utf-8")
    print(body)
"""
        result = controller.run_python_script(code)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"guest API response was not valid JSON: {exc}: {output}") from exc
