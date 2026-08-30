"""Task-specific oracle provider for OpenShop benchmark sanity runs."""

from __future__ import annotations

import json
import shlex
import urllib.parse
from typing import Any, Dict, List

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class OpenShopOracleAdapter(ProviderAdapter):
    """Emit deterministic actions that drive OpenShop tasks to their expected end state."""

    provider_name = "openshop_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    _TASK_ACTIONS: Dict[str, List[Dict[str, Any]]] = {
        "login": [
            {
                "type": "launch_app",
                "app_name": "",
                "assistant_text": "Sign in and prepare the required one-item OpenShop coffee cart through the local app API.",
            },
            {
                "type": "wait",
                "ms": 2000,
                "assistant_text": "Wait for the login request to finish.",
            },
            {
                "type": "success",
                "message": "OpenShop sign-in and coffee cart preparation should now be complete.",
                "assistant_text": "The login-plus-cart task is complete.",
            },
        ],
        "add_headphones_to_cart": [
            {
                "type": "launch_app",
                "app_name": "",
                "assistant_text": "Sign in and add the six required OpenShop cart items through the local app API.",
            },
            {
                "type": "wait",
                "ms": 2000,
                "assistant_text": "Wait for the cart update to finish.",
            },
            {
                "type": "success",
                "message": "The OpenShop cart should now contain the six required items.",
                "assistant_text": "The cart task is complete.",
            },
        ],
        "checkout_coffee": [
            {
                "type": "launch_app",
                "app_name": "",
                "assistant_text": "Sign in and submit the expected six-item OpenShop order through the local app API.",
            },
            {
                "type": "wait",
                "ms": 2000,
                "assistant_text": "Wait for the checkout request to finish.",
            },
            {
                "type": "success",
                "message": "The OpenShop six-item checkout should now be complete.",
                "assistant_text": "The checkout task is complete.",
            },
        ],
    }

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        task_key = self._resolve_task_key(request.messages)
        actions = self._actions_for_task(task_key)
        step_index = self._step_index(request.messages)

        if step_index < len(actions):
            action = dict(actions[step_index])
        else:
            action = {"type": "success", "message": "Oracle plan completed."}

        if action.get("type") == "launch_app":
            action["app_name"] = self._build_command(task_key)

        action_type = str(action.get("type") or "").strip()
        assistant_text = str(action.get("assistant_text") or f"Oracle step {step_index + 1}: {action_type}")
        tool_payload = {k: v for k, v in action.items() if k not in {"type", "assistant_text"}}

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(tool_payload, ensure_ascii=False),
                        call_id=f"openshop-oracle-{step_index + 1}",
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

        json_action = dict(action)
        json_action.pop("assistant_text", None)
        return ProviderResult(
            text=json.dumps(json_action, ensure_ascii=False),
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
    def _step_index(messages: List[Message]) -> int:
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    @classmethod
    def _actions_for_task(cls, task_key: str) -> List[Dict[str, Any]]:
        actions = cls._TASK_ACTIONS.get(task_key)
        if not actions:
            raise ValueError(f"Unsupported OpenShop oracle task: {task_key}")
        return actions

    @staticmethod
    def _resolve_task_key(messages: List[Message]) -> str:
        system_text = "\n".join(
            message.text_content()
            for message in messages
            if getattr(message, "role", "") == "system"
        ).lower()

        if (
            "complete checkout for the coffee already in the cart" in system_text
            or "bring both items together" in system_text
            or "bring all six items together" in system_text
            or "six-item checkout cart" in system_text
            or "office delivery only; keep all six selected products" in system_text
            or "cash on delivery" in system_text
            or "submit the order" in system_text
        ):
            return "checkout_coffee"
        if "build a six-item cart" in system_text or "search for verdant pro noise-canceling headphones" in system_text:
            return "add_headphones_to_cart"
        if (
            "stop once sign-in is complete" in system_text
            or "signed-in cart contains just that coffee item" in system_text
            or "four-item comparison cart" in system_text
            or "two-item starter cart" in system_text
        ):
            return "login"
        raise ValueError("OpenShop oracle could not match the current task instruction.")

    @staticmethod
    def _build_command(task_key: str) -> str:
        code = OpenShopOracleAdapter._python_code_for_task(task_key)
        return f"python3 -c {shlex.quote(code)}"

    @staticmethod
    def _python_code_for_task(task_key: str) -> str:
        actions: List[str] = []
        actions.append("post('/api/login', {'phone': '13800138000', 'password': 'spring2026'})")

        if task_key == "login":
            actions.extend(OpenShopOracleAdapter._login_product_actions())
            quantity_plan = [
                ("p1005", (2, 1, 3, 1)),
                ("p1006", (2, 1)),
            ]
            for product_id, quantities in quantity_plan:
                for quantity in quantities:
                    actions.append(f"set_cart_quantity({product_id!r}, {quantity})")
        elif task_key == "add_headphones_to_cart":
            actions.extend(OpenShopOracleAdapter._add_six_product_actions())
            quantity_plan = [
                ("p1001", (2, 1, 4, 1, 2, 1)),
                ("p1005", (3, 1, 5, 1, 2, 1)),
                ("p1006", (2, 1, 4, 1, 3, 1)),
                ("p1004", (3, 1, 5, 1, 2, 1)),
                ("p1002", (2, 1, 4, 1, 3, 1)),
                ("p1003", (3, 1, 5, 1, 2, 1)),
            ]
            for product_id, quantities in quantity_plan:
                for quantity in quantities:
                    actions.append(f"set_cart_quantity({product_id!r}, {quantity})")
        elif task_key == "checkout_coffee":
            actions.extend(OpenShopOracleAdapter._add_six_product_actions())
            quantity_plan = [
                ("p1001", (2, 1, 3, 1, 4, 1)),
                ("p1005", (2, 1, 4, 1, 3, 1)),
                ("p1006", (3, 1, 2, 1)),
                ("p1004", (2, 1, 5, 1, 3, 1)),
                ("p1002", (4, 1, 2, 1)),
                ("p1003", (2, 1, 4, 1)),
            ]
            for product_id, quantities in quantity_plan:
                for quantity in quantities:
                    actions.append(f"set_cart_quantity({product_id!r}, {quantity})")
            actions.append(
                "post('/api/benchmark/event', {'type': 'checkout_address_selected', 'payload': {'addressId': 'addr-home'}})"
            )
            actions.append(
                "post('/api/benchmark/event', {'type': 'checkout_address_selected', 'payload': {'addressId': 'addr-office'}})"
            )
            actions.append(
                "post('/api/benchmark/event', {'type': 'checkout_address_selected', 'payload': {'addressId': 'addr-home'}})"
            )
            actions.append(
                "post('/api/benchmark/event', {'type': 'checkout_address_selected', 'payload': {'addressId': 'addr-office'}})"
            )
            actions.append(
                "post('/api/benchmark/event', {'type': 'checkout_payment_selected', 'payload': {'paymentMethodId': 'alipay'}})"
            )
            actions.append(
                "post('/api/benchmark/event', {'type': 'checkout_payment_selected', 'payload': {'paymentMethodId': 'cod'}})"
            )
            actions.append(
                "post('/api/benchmark/event', {'type': 'checkout_payment_selected', 'payload': {'paymentMethodId': 'wechat'}})"
            )
            actions.append(
                "post('/api/benchmark/event', {'type': 'checkout_payment_selected', 'payload': {'paymentMethodId': 'alipay'}})"
            )
            actions.append(
                "post('/api/benchmark/event', {'type': 'checkout_payment_selected', 'payload': {'paymentMethodId': 'wechat'}})"
            )
            actions.append(
                "post('/api/checkout', {'addressId': 'addr-office', 'paymentMethodId': 'wechat', 'note': 'Office delivery only; keep all six selected products in one shipment after final review.'})"
            )
        elif task_key != "login":
            raise ValueError(f"Unsupported OpenShop oracle task: {task_key}")

        action_code = "\n".join(actions)
        return f"""
import json
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:4310"
DEADLINE = time.time() + 20
HEADERS = {{"Content-Type": "application/json"}}

def post(path, payload):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()

def get(path):
    request = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))

def patch(path, payload):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=HEADERS,
        method="PATCH",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()

def cart_item_id(product_id):
    cart = get("/api/cart")
    for item in cart.get("items", []):
        product = item.get("product") or {{}}
        if str(product.get("id") or "") == product_id:
            return str(item["id"])
    raise RuntimeError(f"missing cart item for {{product_id}}")

def set_cart_quantity(product_id, quantity):
    item_id = urllib.parse.quote(cart_item_id(product_id), safe="")
    patch(f"/api/cart/items/{{item_id}}", {{"quantity": quantity}})

def ready():
    request = urllib.request.Request(BASE + "/api/bootstrap", method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()

while True:
    try:
        ready()
        break
    except Exception:
        if time.time() >= DEADLINE:
            raise
        time.sleep(0.25)

{action_code}
""".strip()

    @staticmethod
    def _login_product_actions() -> List[str]:
        return OpenShopOracleAdapter._product_actions(["p1005", "p1006"])

    @staticmethod
    def _add_six_product_actions() -> List[str]:
        return OpenShopOracleAdapter._product_actions(["p1001", "p1005", "p1006", "p1004", "p1002", "p1003"])

    @staticmethod
    def _product_actions(product_ids: List[str]) -> List[str]:
        products = {
            "p1001": {
                "query": "Verdant Pro Noise-Canceling Headphones",
                "category": "Electronics",
                "sort": "priceDesc",
                "selectedSpec": "Bluetooth 5.4",
            },
            "p1005": {
                "query": "Mountain Isle Pour-Over Coffee",
                "category": "Grocery",
                "sort": "priceAsc",
                "selectedSpec": "20 sachets",
            },
            "p1006": {
                "query": "Lumen Magnetic Phone Stand",
                "category": "Electronics",
                "sort": "priceAsc",
                "selectedSpec": "Magnetic mount",
            },
            "p1004": {
                "query": "Polar Day Slim Business Backpack",
                "category": "Bags",
                "sort": "priceDesc",
                "selectedSpec": "15.6-inch fit",
            },
            "p1002": {
                "query": "Mukawa Folding Camping Table and Chair Set",
                "category": "Home",
                "sort": "priceDesc",
                "selectedSpec": "Storage bag",
            },
            "p1003": {
                "query": "Garden White Cotton Bedding Set",
                "category": "Home",
                "sort": "priceAsc",
                "selectedSpec": "200x230cm",
            },
        }
        actions: List[str] = []
        for product_id in product_ids:
            product = products[product_id]
            query = urllib.parse.urlencode(
                {
                    "q": product["query"],
                    "category": product["category"],
                    "sort": product["sort"],
                }
            )
            actions.extend(
                [
                    f"get('/api/products?{query}')",
                    (
                        "post('/api/cart/items', "
                        f"{{'productId': {product_id!r}, 'quantity': 1, "
                        f"'selectedSpec': {product['selectedSpec']!r}}})"
                    ),
                ]
            )
        return actions
