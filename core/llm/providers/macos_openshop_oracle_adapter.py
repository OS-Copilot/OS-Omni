"""Deterministic oracle provider for macOS OpenShop benchmark runs."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class MacOSOpenShopOracleAdapter(ProviderAdapter):
    provider_name = "macos_openshop_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        task_key = self._resolve_task_key(request.messages, request.metadata)
        actions = self._actions_for_task(task_key)
        step_index = self._step_index(request.messages, request.metadata)

        action = dict(actions[step_index]) if step_index < len(actions) else {
            "type": "success",
            "message": "OpenShop oracle plan completed.",
            "assistant_text": "The OpenShop oracle plan is complete.",
        }

        action_type = str(action.get("type") or "").strip()
        if not action_type:
            raise ValueError("OpenShop oracle action requires non-empty type")

        assistant_text = str(action.get("assistant_text") or f"OpenShop oracle step {step_index + 1}: {action_type}")
        tool_payload = {k: v for k, v in action.items() if k not in {"type", "assistant_text"}}

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(tool_payload, ensure_ascii=False),
                        call_id=f"macos-openshop-oracle-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={
                    "provider": self.provider_name,
                    "task_key": task_key,
                    "step_index": step_index,
                    "action": action,
                },
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        return ProviderResult(
            text=self._code_adapter_text(action),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={
                "provider": self.provider_name,
                "task_key": task_key,
                "step_index": step_index,
                "action": action,
            },
        )


    @staticmethod
    def _code_adapter_text(action: Mapping[str, Any]) -> str:
        action_type = str(action.get("type") or "").strip()
        assistant_text = str(action.get("assistant_text") or action.get("message") or action_type or "Oracle action").strip()

        if action_type == "launch_app":
            app_name = json.dumps(str(action.get("app_name") or ""), ensure_ascii=False)
            code = (
                "import subprocess\n"
                f"subprocess.run(['open', '-a', {app_name}], check=False)\n"
            )
        elif action_type == "wait":
            ms = int(action.get("ms", 1000) or 1000)
            code = f"import time\ntime.sleep({max(ms, 0) / 1000.0!r})\n"
        elif action_type == "run_bash_script":
            script = json.dumps(str(action.get("script") or ""), ensure_ascii=False)
            timeout = max(1, int(action.get("timeout", 30) or 30))
            code = (
                "import os, subprocess, tempfile\n"
                f"script = {script}\n"
                "fd, path = tempfile.mkstemp(prefix='helloworld_macos_oracle_', suffix='.sh')\n"
                "try:\n"
                "    with os.fdopen(fd, 'w', encoding='utf-8') as fh:\n"
                "        fh.write('#!/bin/bash\\nset -e\\n')\n"
                "        fh.write(script)\n"
                "        fh.write('\\n')\n"
                "    os.chmod(path, 0o755)\n"
                f"    proc = subprocess.run(['/bin/bash', path], capture_output=True, text=True, timeout={timeout})\n"
                "    output = (proc.stdout or '') + (proc.stderr or '')\n"
                "    if output.strip():\n"
                "        print(output[-4000:])\n"
                "    if proc.returncode != 0:\n"
                "        raise SystemExit(proc.returncode)\n"
                "finally:\n"
                "    try:\n"
                "        os.unlink(path)\n"
                "    except FileNotFoundError:\n"
                "        pass\n"
            )
        elif action_type == "success":
            message = str(action.get("message") or "OpenShop oracle plan completed.")
            code = f"print('__HELLOWORLD_DONE__:{message}')\n"
        elif action_type == "fail":
            message = str(action.get("reason") or action.get("message") or "OpenShop oracle failed.")
            code = f"print('__HELLOWORLD_FAIL__:{message}')\n"
        else:
            code = f"raise RuntimeError({json.dumps('Unsupported OpenShop oracle action: ' + action_type)})\n"

        return f"{assistant_text}\n```python\n{code}```"

    @staticmethod
    def _step_index(messages: List[Message], metadata: Mapping[str, Any] | None = None) -> int:
        if isinstance(metadata, Mapping):
            completed_step_count = metadata.get("completed_step_count")
            if isinstance(completed_step_count, int) and completed_step_count >= 0:
                return completed_step_count
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    @classmethod
    def _resolve_task_key(cls, messages: List[Message], metadata: Mapping[str, Any] | None = None) -> str:
        if isinstance(metadata, Mapping):
            task_id = str(metadata.get("task_id") or "").strip()
            if task_id:
                task_map = {
                    "macos.openshop.login": "login",
                    "macos.openshop.add_two_items_to_cart": "add_two_items_to_cart",
                    "macos.openshop.checkout_two_items": "checkout_two_items",
                    "macos.openshop.oracle.login": "login",
                    "macos.openshop.oracle.add_two_items_to_cart": "add_two_items_to_cart",
                    "macos.openshop.oracle.checkout_two_items": "checkout_two_items",
                }
                matched = task_map.get(task_id)
                if matched:
                    return matched
        text = "\n".join(message.text_content() for message in messages).lower()
        if "macos.openshop.login" in text or "stop once sign-in is complete" in text:
            return "login"
        if (
            "macos.openshop.add_two_items_to_cart" in text
            or ("verdant pro noise-canceling headphones" in text and "mountain isle pour-over coffee 20 pack" in text and "both products" in text)
        ):
            return "add_two_items_to_cart"
        if (
            "macos.openshop.checkout_two_items" in text
            or ("proceed to checkout" in text and "office shipping address" in text and "wechat pay" in text)
        ):
            return "checkout_two_items"
        raise ValueError("macOS OpenShop oracle could not match the current task instruction.")

    @classmethod
    def _actions_for_task(cls, task_key: str) -> List[Dict[str, Any]]:
        benchmark_mode = cls._benchmark_mode(task_key)
        if task_key == "login":
            return [
                cls._launch_action(),
                cls._wait_action("Pause while OpenShop finishes opening."),
                cls._script_action(
                    "Apply the benchmark login through OpenShop's local API.",
                    cls._login_script(benchmark_mode),
                ),
                cls._wait_action("Pause while the login state refreshes."),
                {"type": "success", "message": "OpenShop sign-in should now be complete."},
            ]
        if task_key == "add_two_items_to_cart":
            return [
                cls._launch_action(),
                cls._wait_action("Pause while OpenShop finishes opening."),
                cls._script_action(
                    "Apply the benchmark login, catalog browsing, cart review, and both cart items through OpenShop's local API.",
                    cls._cart_script(benchmark_mode),
                ),
                cls._wait_action("Pause while the cart updates finish rendering."),
                {"type": "success", "message": "OpenShop should now show both required cart items."},
            ]
        if task_key == "checkout_two_items":
            return [
                cls._launch_action(),
                cls._wait_action("Pause while OpenShop finishes opening."),
                cls._script_action(
                    "Apply the benchmark login, catalog browsing, cart review, and checkout flow through OpenShop's local API.",
                    cls._checkout_script(benchmark_mode),
                ),
                cls._wait_action("Pause while the order confirmation finishes rendering."),
                {"type": "success", "message": "OpenShop should now contain the required completed order."},
            ]
        raise ValueError(f"Unsupported macOS OpenShop oracle task: {task_key!r}")

    @staticmethod
    def _launch_action() -> Dict[str, Any]:
        return {
            "type": "launch_app",
            "app_name": "OpenShop",
            "assistant_text": "Bring OpenShop to the foreground before applying the deterministic local state.",
        }

    @staticmethod
    def _wait_action(text: str) -> Dict[str, Any]:
        return {
            "type": "wait",
            "ms": 1500,
            "assistant_text": text,
        }

    @staticmethod
    def _script_action(assistant_text: str, script: str) -> Dict[str, Any]:
        return {
            "type": "run_bash_script",
            "script": script,
            "assistant_text": assistant_text,
        }

    @staticmethod
    def _benchmark_mode(task_key: str) -> str:
        return f"macos.openshop.{task_key}"

    @staticmethod
    def _login_script(benchmark_mode: str) -> str:
        return MacOSOpenShopOracleAdapter._api_script(
            [
                {
                    "method": "POST",
                    "path": "/api/login",
                    "payload": {"phone": "13800138000", "password": "spring2026"},
                },
            ],
            benchmark_mode=benchmark_mode,
        )

    @staticmethod
    def _cart_script(benchmark_mode: str) -> str:
        return MacOSOpenShopOracleAdapter._api_script(
            [
                {
                    "method": "POST",
                    "path": "/api/login",
                    "payload": {"phone": "13800138000", "password": "spring2026"},
                },
                {
                    "method": "GET",
                    "path": "/api/products?q=verdant%20pro%20noise-canceling%20headphones&category=Electronics&sort=priceDesc",
                },
                {"method": "GET", "path": "/api/products/p1001"},
                {
                    "method": "POST",
                    "path": "/api/cart/items",
                    "payload": {"productId": "p1001", "quantity": 1, "selectedSpec": "Bluetooth 5.4"},
                },
                {
                    "method": "POST",
                    "path": "/api/benchmark/event",
                    "payload": {"type": "cart_continue_shopping", "payload": {}},
                },
                {
                    "method": "GET",
                    "path": "/api/products?q=mountain%20isle%20pour-over%20coffee%2020%20pack&category=Grocery&sort=priceAsc",
                },
                {"method": "GET", "path": "/api/products/p1005"},
                {
                    "method": "POST",
                    "path": "/api/cart/items",
                    "payload": {"productId": "p1005", "quantity": 1, "selectedSpec": "20 sachets"},
                },
            ],
            benchmark_mode=benchmark_mode,
            cart_review_advances=8,
        )

    @staticmethod
    def _checkout_script(benchmark_mode: str) -> str:
        return MacOSOpenShopOracleAdapter._api_script(
            [
                {
                    "method": "POST",
                    "path": "/api/login",
                    "payload": {"phone": "13800138000", "password": "spring2026"},
                },
                {
                    "method": "GET",
                    "path": "/api/products?q=verdant%20pro%20noise-canceling%20headphones&category=Electronics&sort=priceDesc",
                },
                {"method": "GET", "path": "/api/products/p1001"},
                {
                    "method": "POST",
                    "path": "/api/cart/items",
                    "payload": {"productId": "p1001", "quantity": 1, "selectedSpec": "Bluetooth 5.4"},
                },
                {
                    "method": "POST",
                    "path": "/api/benchmark/event",
                    "payload": {"type": "cart_continue_shopping", "payload": {}},
                },
                {
                    "method": "GET",
                    "path": "/api/products?q=mountain%20isle%20pour-over%20coffee%2020%20pack&category=Grocery&sort=priceAsc",
                },
                {"method": "GET", "path": "/api/products/p1005"},
                {
                    "method": "POST",
                    "path": "/api/cart/items",
                    "payload": {"productId": "p1005", "quantity": 1, "selectedSpec": "20 sachets"},
                },
            ],
            benchmark_mode=benchmark_mode,
            cart_review_advances=8,
            checkout_advances=6,
        )

    @staticmethod
    def _api_script(
        operations: List[Mapping[str, Any]],
        *,
        benchmark_mode: str,
        cart_review_advances: int = 0,
        checkout_advances: int = 0,
    ) -> str:
        request_lines: list[str] = []
        for operation in operations:
            method = str(operation.get("method") or "POST").strip().upper()
            path = str(operation.get("path") or "").strip()
            if not path:
                raise ValueError("OpenShop oracle operation is missing path")
            if method == "GET":
                request_lines.append(f"request_json({json.dumps(path)}, method='GET')")
                continue
            if method == "POST":
                payload = dict(operation.get("payload") or {})
                request_lines.append(
                    "request_json("
                    f"{json.dumps(path)}, method='POST', payload={json.dumps(payload, ensure_ascii=False)}"
                    ")"
                )
                continue
            raise ValueError(f"Unsupported OpenShop oracle HTTP method: {method!r}")

        if cart_review_advances > 0:
            request_lines.append(
                f"for _ in range({int(cart_review_advances)}):\n"
                "    request_json('/api/benchmark/cart-review/advance', method='POST', payload={})"
            )
        if checkout_advances > 0:
            request_lines.append(
                f"for _ in range({int(checkout_advances)}):\n"
                "    request_json('/api/benchmark/checkout/advance', method='POST', payload={})"
            )

        benchmark_mode_literal = json.dumps(str(benchmark_mode or "").strip(), ensure_ascii=False)
        request_block = "\n".join(request_lines)
        return (
            "python3 - <<'PY'\n"
            "import json\n"
            "import time\n"
            "import urllib.request\n"
            "\n"
            'BASE = "http://127.0.0.1:4310"\n'
            "DEADLINE = time.time() + 20\n"
            "BENCHMARK_MODE = "
            f"{benchmark_mode_literal}\n"
            'HEADERS = {"Content-Type": "application/json"}\n'
            "\n"
            "def request_json(path, method='GET', payload=None):\n"
            "    data = None\n"
            "    if payload is not None:\n"
            '        data = json.dumps(payload).encode("utf-8")\n'
            "    request = urllib.request.Request(\n"
            "        BASE + path,\n"
            "        data=data,\n"
            "        headers=HEADERS,\n"
            "        method=method,\n"
            "    )\n"
            "    with urllib.request.urlopen(request, timeout=5) as response:\n"
            '        body = response.read().decode("utf-8")\n'
            "        return json.loads(body) if body else {}\n"
            "\n"
            "while True:\n"
            "    try:\n"
            "        request_json('/api/bootstrap', method='GET')\n"
            "        break\n"
            "    except Exception:\n"
            "        if time.time() >= DEADLINE:\n"
            "            raise\n"
            "        time.sleep(0.25)\n"
            "\n"
            "request_json('/api/dev/reset', method='POST', payload={'benchmarkMode': BENCHMARK_MODE})\n"
            f"{request_block}\n"
            "benchmark = request_json('/api/benchmark', method='GET')\n"
            "cart = request_json('/api/cart', method='GET')\n"
            "print(json.dumps({\n"
            "    'benchmarkMode': benchmark.get('benchmarkMode'),\n"
            "    'eventCount': len(list(benchmark.get('events') or [])),\n"
            "    'cartItemCount': len(list(cart.get('items') or [])),\n"
            "}, ensure_ascii=False))\n"
            "PY"
        )
