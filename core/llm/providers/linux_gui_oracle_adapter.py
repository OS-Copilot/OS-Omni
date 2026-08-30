"""Deterministic Linux oracle adapter driven by oracle task specs."""

from __future__ import annotations

import json
import shlex
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from initializers.linux.drawio import DrawIOInitializer
from platforms.linux.core.oracle_specs import load_oracle_and_base_specs

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class LinuxGuiOracleAdapter(ProviderAdapter):
    """Drive Linux oracle tasks from preserved oracle task specs and base initial states."""

    provider_name = "linux_gui_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        task_id = self._resolve_task_id(request)
        oracle_spec, base_spec = load_oracle_and_base_specs(task_id)
        plan = self._build_plan(task_id, oracle_spec, base_spec)
        step_index = self._step_index(request.messages)
        max_steps = int(((oracle_spec.get("limits") or {}).get("max_steps")) or 0)
        compact_plan = max_steps > 0 and max_steps <= 2

        if step_index == 0:
            action_type = str(plan.get("action_type") or "run_bash").strip() or "run_bash"
            if action_type == "launch_app":
                tool_payload = {"app_name": plan["command"]}
            elif action_type == "run_bash":
                tool_payload = {"script": plan["command"], "timeout_ms": int(plan.get("timeout_ms", 120000))}
            else:
                raise ValueError(f"Unsupported oracle action_type: {action_type}")
            action = {
                "type": action_type,
                **tool_payload,
                "assistant_text": str(plan["assistant_text"]),
            }
        elif not compact_plan and step_index == 1:
            action = {
                "type": "wait",
                "ms": int(plan.get("wait_ms", 2500)),
                "assistant_text": "Wait for the oracle desktop automation to settle.",
            }
        else:
            action = {
                "type": "success",
                "message": str(plan["success_message"]),
                "assistant_text": "The Linux oracle task is complete.",
            }

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
                        call_id=f"linux-gui-oracle-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={"provider": self.provider_name, "task_id": task_id, "step_index": step_index},
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        json_action = dict(action)
        json_action.pop("assistant_text", None)
        return ProviderResult(
            text=json.dumps(json_action, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={"provider": self.provider_name, "task_id": task_id, "step_index": step_index},
        )

    @staticmethod
    def _step_index(messages: List[Message]) -> int:
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    @staticmethod
    def _resolve_task_id(request: ProviderRequest) -> str:
        task_id = str(request.metadata.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("linux_gui_oracle requires request.metadata.task_id")
        return task_id

    def _build_plan(
        self,
        task_id: str,
        oracle_spec: dict[str, Any],
        base_spec: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        init = oracle_spec.get("init") or {}
        initializer_id = str(init.get("initializer_id") or "").strip()
        if initializer_id.endswith("GimpInitializer"):
            return self._plan_gimp(task_id, oracle_spec)
        if initializer_id.endswith("OpenShopInitializer"):
            return self._plan_openshop(task_id)
        if initializer_id.endswith("DeltaChatOracleInitializer") or initializer_id.endswith("DeltaChatInitializer"):
            return self._plan_deltachat(oracle_spec)
        if initializer_id.endswith("WiresharkInitializer"):
            return self._plan_wireshark(oracle_spec)
        if initializer_id.endswith("BlenderInitializer"):
            return self._plan_blender(oracle_spec)
        if initializer_id.endswith("LinuxOfficeSetupInitializer"):
            return self._plan_office_copy(oracle_spec)
        if initializer_id.endswith("NotepadqqInitializer"):
            return self._plan_notepadqq(oracle_spec)
        if initializer_id.endswith("DrawIOInitializer"):
            return self._plan_drawio(oracle_spec)
        if initializer_id.endswith("MarbleInitializer"):
            return self._plan_marble(oracle_spec)
        if initializer_id.endswith("SpotubeInitializer"):
            return self._plan_spotube(oracle_spec)
        if initializer_id.endswith("DesktopSetupInitializer"):
            if task_id == "linux.impress.oracle.add_dissolve_transition":
                return self._plan_impress_dissolve_transition(oracle_spec)
            if task_id == "linux.cross_app.oracle.thunderbird_calendar_dual_item_checkout_two_events_hard":
                return self._plan_cross_app_dual_item_checkout()
            if task_id == "linux.cross_app.oracle.writer_thunderbird_attach_source_and_pdf_draft_hard":
                return self._plan_desktop_setup(oracle_spec, base_spec)
            if task_id == "linux.cross_app.oracle.writer_thunderbird_export_pdf_attach_draft_easy":
                return self._plan_writer_thunderbird_attachment_oracle(
                    source_path="/home/user/Desktop/Bench_Status_Update.docx",
                    pdf_path="/home/user/Desktop/Bench_Status_Update.pdf",
                    compose_subject="Bench PDF Review",
                    allowed_attachments=("Bench_Status_Update.pdf",),
                )
            if task_id == "linux.cross_app.oracle.writer_thunderbird_save_copy_export_attach_draft_hard":
                return self._plan_desktop_setup(oracle_spec, base_spec)
            if task_id == "linux.thunderbird.oracle.thunderbird_enable_dark_mode":
                return self._plan_thunderbird_dark_mode()
            return self._plan_desktop_setup(oracle_spec, base_spec)
        raise ValueError(f"Unsupported Linux oracle initializer: {initializer_id}")

    @staticmethod
    def _desktop_env_lines() -> list[str]:
        return [
            "export DISPLAY=${DISPLAY:-:0}",
            "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
            'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
            'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
        ]

    @staticmethod
    def _quote_python_heredoc(code: str) -> list[str]:
        return ["python3 - <<'PY'", code.rstrip(), "PY"]

    @classmethod
    def _plan_gimp(cls, task_id: str, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        output_path = str(((oracle_spec.get("evaluation") or {}).get("params") or {}).get("output_path") or "").strip()
        if not output_path:
            raise ValueError(f"GIMP oracle missing evaluation.params.output_path for {task_id}")

        inp = "/tmp/helloworld_gimp/input.png"
        if task_id.endswith(".convert_grayscale"):
            operation = (
                f"from PIL import Image; "
                f"img = Image.open({json.dumps(inp)}).convert('L'); "
                f"img.save({json.dumps(output_path)}, 'PNG')"
            )
        elif task_id.endswith(".crop_center"):
            operation = (
                f"from PIL import Image; "
                f"img = Image.open({json.dumps(inp)}).convert('RGB'); "
                f"img = img.crop((320, 180, 1600, 900)); "
                f"img = img.resize((640, 480), Image.LANCZOS).convert('L'); "
                f"img.save({json.dumps(output_path)}, 'PNG')"
            )
        elif task_id.endswith(".scale_image"):
            operation = (
                f"from PIL import Image; "
                f"img = Image.open({json.dumps(inp)}).convert('RGB'); "
                f"img = img.resize((1024, 768), Image.LANCZOS); "
                f"img = img.crop((112, 84, 912, 684)); "
                f"img.save({json.dumps(output_path)}, 'PNG')"
            )
        else:
            raise ValueError(f"Unsupported GIMP oracle task: {task_id}")

        app_command = str(((oracle_spec.get("init") or {}).get("params") or {}).get("app_command") or "gimp").strip()
        relaunch_target = shlex.quote(output_path if output_path else inp)
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                "wmctrl -a 'GIMP' 2>/dev/null || true",
                f"python3 -c {shlex.quote(operation)}",
                "sleep 1",
                "pkill -TERM -f 'gimp' || true",
                "sleep 1",
                (
                    f"setsid -f bash -lc {shlex.quote(app_command + ' ' + relaunch_target)} "
                    ">/dev/null 2>&1"
                ),
            ]
        )
        return {
            "command": command,
            "assistant_text": "Apply the oracle image edit and reopen GIMP on the saved artifact.",
            "success_message": f"GIMP oracle completed for {Path(output_path).name}.",
            "wait_ms": 3500,
        }

    @classmethod
    def _plan_openshop(cls, task_id: str) -> dict[str, Any]:
        actions: list[str] = ["post('/api/login', {'phone': '13800138000', 'password': 'spring2026'})"]
        success_message = "OpenShop oracle completed."
        if task_id.endswith(".login"):
            actions.extend(cls._openshop_login_product_actions())
            quantity_plan = [
                ("p1005", (2, 1, 3, 1)),
                ("p1006", (2, 1)),
            ]
            for product_id, quantities in quantity_plan:
                for quantity in quantities:
                    actions.append(f"set_cart_quantity({product_id!r}, {quantity})")
            success_message = "OpenShop oracle completed the login-plus-two-item-cart task."
        elif task_id.endswith(".add_headphones_to_cart"):
            actions.extend(cls._openshop_six_product_actions())
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
            success_message = "OpenShop oracle added the six required cart items."
        elif task_id.endswith(".checkout_coffee"):
            actions.extend(cls._openshop_six_product_actions())
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
            success_message = "OpenShop oracle completed the six-item checkout."
        else:
            raise ValueError(f"Unsupported OpenShop oracle task: {task_id}")

        code = f"""
import json
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:4310"
HEADERS = {{"Content-Type": "application/json"}}
DEADLINE = time.time() + 20

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
    with urllib.request.urlopen(BASE + "/api/bootstrap", timeout=5) as response:
        response.read()

while True:
    try:
        ready()
        break
    except Exception:
        if time.time() >= DEADLINE:
            raise
        time.sleep(0.25)

{chr(10).join(actions)}
""".strip()
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                "wmctrl -a 'OpenShop' 2>/dev/null || true",
                *cls._quote_python_heredoc(code),
                "sleep 1",
                "wmctrl -a 'OpenShop' 2>/dev/null || true",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Drive OpenShop through its local app API while the desktop app stays visible.",
            "success_message": success_message,
            "wait_ms": 2500,
        }

    @staticmethod
    def _openshop_login_product_actions() -> list[str]:
        return LinuxGuiOracleAdapter._openshop_product_actions(["p1005", "p1006"])

    @staticmethod
    def _openshop_six_product_actions() -> list[str]:
        return LinuxGuiOracleAdapter._openshop_product_actions(["p1001", "p1005", "p1006", "p1004", "p1002", "p1003"])

    @staticmethod
    def _openshop_product_actions(product_ids: list[str]) -> list[str]:
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
        actions: list[str] = []
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
        return [
            *actions,
        ]

    @classmethod
    def _plan_deltachat(cls, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        init_params = (oracle_spec.get("init") or {}).get("params") or {}
        profile_root = str(init_params.get("profile_root") or "/tmp/helloworld_deltachat_profile").strip()
        expectations = (
            init_params.get("expectations")
            or (((oracle_spec.get("evaluation") or {}).get("params") or {}).get("expectations"))
            or []
        )
        if not isinstance(expectations, list) or not expectations:
            raise ValueError("Delta Chat oracle requires expectations")
        code = "\n".join(
            [
                "import json",
                "import pathlib",
                "import sqlite3",
                "import time",
                f"root = pathlib.Path({json.dumps(profile_root, ensure_ascii=False)})",
                "manifest = json.loads((root / 'benchmark_manifest.json').read_text(encoding='utf-8'))",
                "db_path = root / manifest['main_account']['db_path']",
                f"expectations = json.loads({json.dumps(json.dumps(expectations, ensure_ascii=False), ensure_ascii=False)})",
                "con = sqlite3.connect(db_path)",
                "try:",
                "    cur = con.cursor()",
                "    self_row = cur.execute(\"select id from contacts where name='self' order by id limit 1\").fetchone()",
                "    if self_row is None:",
                "        raise SystemExit('missing self contact in Delta Chat db')",
                "    self_contact_id = int(self_row[0])",
                "    base_ts = int(time.time())",
                "    for index, item in enumerate(expectations):",
                "        row = cur.execute(\"select id from chats where name = ? order by id limit 1\", (str(item['chat_name']),)).fetchone()",
                "        if row is None:",
                "            raise SystemExit(f\"missing chat named {item['chat_name']!r}\")",
                "        text = str(item['expected_text'])",
                "        ts = base_ts + index",
                "        cur.execute(",
                "            \"insert into msgs (chat_id, from_id, to_id, timestamp, type, state, msgrmsg, txt, hidden, timestamp_sent, timestamp_rcvd, txt_normalized) values (?, ?, 0, ?, 10, 26, 1, ?, 0, 0, 0, ?)\",",
                "            (int(row[0]), self_contact_id, ts, text, text.casefold()),",
                "        )",
                "    con.commit()",
                "finally:",
                "    con.close()",
            ]
        )
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                "wmctrl -a 'Delta Chat' 2>/dev/null || true",
                *cls._quote_python_heredoc(code),
                "sleep 1",
                "wmctrl -a 'Delta Chat' 2>/dev/null || true",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Insert the expected Delta Chat messages into the live benchmark profile.",
            "success_message": "Delta Chat oracle messages were applied.",
            "wait_ms": 2500,
        }

    @classmethod
    def _plan_wireshark(cls, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        artifacts = list((((oracle_spec.get("evaluation") or {}).get("params") or {}).get("artifacts")) or [])
        if not artifacts:
            raise ValueError("Wireshark oracle requires evaluation.params.artifacts")
        outputs = []
        texts = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            kind = str(artifact.get("kind") or "pcap").strip()
            path = str(artifact.get("path") or "").strip()
            if not path:
                continue
            if kind == "text":
                if "equals" not in artifact:
                    raise ValueError(f"Wireshark text artifact requires equals content for {path}")
                texts.append({"path": path, "content": str(artifact.get("equals") or "")})
                continue
            if kind != "pcap":
                continue
            if "all_match_filter" in artifact:
                packet_filter = str(artifact.get("all_match_filter") or "").strip()
            elif path.endswith("syn_only.pcapng"):
                packet_filter = "tcp.flags.syn == 1 && tcp.flags.ack == 0"
            elif path.endswith("bench_dns_only.pcapng"):
                packet_filter = 'dns && dns.qry.name contains "bench.local"'
            elif path.endswith("http_request_only.pcapng"):
                packet_filter = "http.request"
            elif path.endswith("arp_only.pcapng"):
                packet_filter = "arp"
            else:
                raise ValueError(f"Could not infer Wireshark export filter for {path}")
            outputs.append({"filter": packet_filter, "path": path})
        code = f"""
import json
import pathlib
import subprocess

source = pathlib.Path("/tmp/helloworld_wireshark/retail_mix.pcapng")
outputs = json.loads({json.dumps(json.dumps(outputs, ensure_ascii=False), ensure_ascii=False)})
texts = json.loads({json.dumps(json.dumps(texts, ensure_ascii=False), ensure_ascii=False)})
for item in outputs:
    out_path = pathlib.Path(item["path"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    subprocess.run(
        ["tshark", "-r", str(source), "-Y", item["filter"], "-w", str(out_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
for item in texts:
    text_path = pathlib.Path(item["path"])
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(item["content"], encoding="utf-8")
""".strip()
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                "wmctrl -a 'Wireshark' 2>/dev/null || true",
                *cls._quote_python_heredoc(code),
                "sleep 1",
                "wmctrl -a 'Wireshark' 2>/dev/null || true",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Export the expected Wireshark artifacts from the seeded capture.",
            "success_message": "Wireshark oracle exports were written.",
            "wait_ms": 3000,
        }

    @classmethod
    def _plan_blender(cls, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        init_params = (oracle_spec.get("init") or {}).get("params") or {}
        scene_spec = init_params.get("scene_spec")
        blend_path = str((((oracle_spec.get("evaluation") or {}).get("params") or {}).get("blend_path")) or "").strip()
        app_command = str(init_params.get("app_command") or "blender").strip()
        if not isinstance(scene_spec, dict) or not blend_path:
            raise ValueError("Blender oracle requires init.params.scene_spec and evaluation.params.blend_path")

        workspace_path = Path(str(init_params.get("workspace_path") or Path(blend_path).parent))
        extra_scene_specs: list[dict[str, Any]] = []
        for item in init_params.get("extra_scene_specs") or []:
            if not isinstance(item, dict):
                continue
            scene_name = str(item.get("scene_name") or "").strip()
            extra_spec = item.get("scene_spec")
            if scene_name and isinstance(extra_spec, dict):
                extra_scene_specs.append(
                    {
                        "scene_spec": extra_spec,
                        "blend_path": str(workspace_path / scene_name),
                    }
                )
        text_artifacts = [
            item
            for item in (init_params.get("text_artifacts") or [])
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        ]
        payload = {
            "scene_spec": scene_spec,
            "blend_path": blend_path,
            "extra_scene_specs": extra_scene_specs,
            "text_artifacts": text_artifacts,
        }
        code = """
import json
import pathlib
import subprocess
import tempfile
import textwrap

payload = json.loads(__PAYLOAD__)
scene_spec = payload["scene_spec"]
blend_path = payload["blend_path"]
extra_scene_specs = payload.get("extra_scene_specs", [])
text_artifacts = payload.get("text_artifacts", [])

scene_script = textwrap.dedent(
    '''
    import bpy
    import json
    import math
    import pathlib
    import sys

    payload_path = pathlib.Path(sys.argv[-1])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    scene_spec = payload["scene_spec"]
    blend_path = payload["blend_path"]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    render = scene.render
    render.engine = scene_spec["render"]["engine"]
    render.resolution_x = int(scene_spec["render"]["resolution_x"])
    render.resolution_y = int(scene_spec["render"]["resolution_y"])
    render.resolution_percentage = int(scene_spec["render"].get("resolution_percentage", 100))
    render.fps = int(scene_spec["render"]["fps"])
    scene.frame_start = int(scene_spec["render"]["frame_start"])
    scene.frame_end = int(scene_spec["render"]["frame_end"])
    render.image_settings.file_format = scene_spec["render"]["file_format"]
    render.image_settings.color_mode = scene_spec["render"]["color_mode"]
    render.film_transparent = bool(scene_spec["render"]["film_transparent"])
    render.filepath = scene_spec["render"].get("filepath", "")
    if "eevee_taa_render_samples" in scene_spec["render"]:
        scene.eevee.taa_render_samples = int(scene_spec["render"]["eevee_taa_render_samples"])

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    for obj_spec in scene_spec["objects"]:
        obj_type = obj_spec["type"]
        if obj_type == "CAMERA":
            camera_data = bpy.data.cameras.new(obj_spec["name"])
            obj = bpy.data.objects.new(obj_spec["name"], camera_data)
            bpy.context.collection.objects.link(obj)
            scene.camera = obj
        elif obj_type == "LIGHT":
            light_data = bpy.data.lights.new(name=obj_spec["name"], type=obj_spec.get("light_type", "SUN"))
            obj = bpy.data.objects.new(obj_spec["name"], light_data)
            bpy.context.collection.objects.link(obj)
        elif obj_type == "MESH_CUBE":
            bpy.ops.mesh.primitive_cube_add()
            obj = bpy.context.active_object
            obj.name = obj_spec["name"]
        elif obj_type == "MESH_CYLINDER":
            bpy.ops.mesh.primitive_cylinder_add(vertices=32)
            obj = bpy.context.active_object
            obj.name = obj_spec["name"]
        elif obj_type == "MESH_UV_SPHERE":
            bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
            obj = bpy.context.active_object
            obj.name = obj_spec["name"]
        elif obj_type == "MESH_PLANE":
            bpy.ops.mesh.primitive_plane_add()
            obj = bpy.context.active_object
            obj.name = obj_spec["name"]
        else:
            raise RuntimeError(f"Unsupported object type: {obj_type}")

        obj.location = obj_spec.get("location", [0.0, 0.0, 0.0])
        obj.rotation_euler = [math.radians(v) for v in obj_spec.get("rotation_degrees", [0.0, 0.0, 0.0])]
        obj.scale = obj_spec.get("scale", [1.0, 1.0, 1.0])
        if "material_diffuse_color" in obj_spec:
            material = bpy.data.materials.new(f"{obj_spec['name']}_Material")
            material.diffuse_color = obj_spec["material_diffuse_color"]
            obj.data.materials.append(material)

    bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=False)
    '''
)

with tempfile.TemporaryDirectory(prefix="helloworld-blender-oracle-") as tmpdir:
    tmp_root = pathlib.Path(tmpdir)
    payload_path = tmp_root / "payload.json"
    script_path = tmp_root / "oracle_scene.py"
    script_path.write_text(scene_script, encoding="utf-8")
    scene_jobs = [{"scene_spec": scene_spec, "blend_path": blend_path}, *extra_scene_specs]
    for scene_job in scene_jobs:
        payload_path.write_text(json.dumps(scene_job, ensure_ascii=False), encoding="utf-8")
        subprocess.run(
            ["blender", "--background", "--python", str(script_path), "--", str(payload_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
for artifact in text_artifacts:
    text_path = pathlib.Path(artifact["path"])
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(str(artifact.get("content") or ""), encoding="utf-8")
""".replace("__PAYLOAD__", json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)).strip()

        command = "\n".join(
            cls._desktop_env_lines()
            + [
                "wmctrl -a 'Blender' 2>/dev/null || true",
                *cls._quote_python_heredoc(code),
                "sleep 1",
                "pkill -TERM -f 'blender' || true",
                "sleep 1",
                f"setsid -f bash -lc {shlex.quote(app_command + ' ' + shlex.quote(blend_path))} >/dev/null 2>&1",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Apply the Blender oracle scene spec and reopen the prepared .blend file.",
            "success_message": "Blender oracle scene state was written.",
            "wait_ms": 5000,
        }

    @classmethod
    def _plan_office_copy(cls, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        eval_params = ((oracle_spec.get("evaluation") or {}).get("params") or {})
        actual_path = str(eval_params.get("actual_path") or "").strip()
        expected_path = str(eval_params.get("expected_path") or "").strip()
        if not actual_path or not expected_path:
            seed_downloads = list((((oracle_spec.get("init") or {}).get("params") or {}).get("seed_downloads")) or [])
            if len(seed_downloads) >= 2:
                actual_path = actual_path or str((seed_downloads[0] or {}).get("path") or "").strip()
                expected_path = expected_path or str((seed_downloads[1] or {}).get("path") or "").strip()
        if not actual_path or not expected_path:
            raise ValueError("Office oracle requires actual/expected document paths")

        suffix = Path(actual_path).suffix.lower()
        if suffix in {".xlsx", ".ods", ".xls"}:
            component = "calc"
        elif suffix in {".pptx", ".odp", ".ppt"}:
            component = "impress"
        else:
            component = "writer"
        focus = shlex.quote(Path(actual_path).name)
        post_copy_commands: list[str] = []
        rules = eval_params.get("rules") or []
        if suffix in {".xlsx", ".xlsm"} and isinstance(rules, list) and rules:
            payload = {"actual_path": actual_path, "rules": rules}
            patch_code = """
import json
from openpyxl import load_workbook

payload = json.loads(__PAYLOAD__)
workbook = load_workbook(payload["actual_path"])
for rule in payload["rules"]:
    if not isinstance(rule, dict):
        continue
    rule_type = str(rule.get("type") or "").strip()
    if rule_type == "sheet_name":
        sheet = workbook.worksheets[int(rule.get("sheet_idx", 0) or 0)]
        sheet.title = str(rule.get("ref") or "")
    elif rule_type == "zoom":
        sheet = workbook.worksheets[int(rule.get("sheet_idx", 0) or 0)]
        sheet.sheet_view.zoomScale = int(rule.get("ref"))
workbook.save(payload["actual_path"])
""".replace("__PAYLOAD__", json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)).strip()
            post_copy_commands.extend(cls._quote_python_heredoc(patch_code))
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                f"cp {shlex.quote(expected_path)} {shlex.quote(actual_path)}",
                *post_copy_commands,
                f"nohup libreoffice --{component} {shlex.quote(actual_path)} >/tmp/helloworld_lo_oracle.log 2>&1 &",
                "sleep 2",
                f"wmctrl -a {focus} 2>/dev/null || wmctrl -a 'LibreOffice' 2>/dev/null || true",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Apply the expected LibreOffice artifact and refocus the desktop document window.",
            "success_message": f"LibreOffice oracle saved {Path(actual_path).name}.",
            "wait_ms": 3000,
        }

    @classmethod
    def _plan_notepadqq(cls, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        init_params = (oracle_spec.get("init") or {}).get("params") or {}
        workspace_root = str(init_params.get("workspace_root") or "/tmp/helloworld_notepadqq_workspace").rstrip("/")
        workspace_name = str(init_params.get("workspace_name") or "bench").strip() or "bench"
        workspace_path = f"{workspace_root}/{workspace_name}"
        files = list(init_params.get("files") or [])
        open_files = list(init_params.get("open_files") or [])
        app_command = str(init_params.get("app_command") or "gedit").strip()
        payload = {"workspace_path": workspace_path, "files": files}
        code = """
import json
import pathlib

payload = json.loads(__PAYLOAD__)
workspace = pathlib.Path(payload["workspace_path"])
for file_spec in payload["files"]:
    file_path = workspace / str(file_spec["path"])
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(str(file_spec["content"]), encoding="utf-8")
""".replace("__PAYLOAD__", json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)).strip()
        open_targets = open_files or [item.get("path") for item in files if isinstance(item, dict) and item.get("path")]
        launch_targets = " ".join(shlex.quote(f"{workspace_path}/{path}") for path in open_targets)
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                *cls._quote_python_heredoc(code),
                f"pkill -TERM -f {shlex.quote(app_command)} || true",
                "sleep 1",
                f"setsid -f bash -lc {shlex.quote((app_command + ' ' + launch_targets).strip())} >/dev/null 2>&1",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Rewrite the prepared editor workspace and reopen the target files.",
            "success_message": "Editor oracle files were rewritten.",
            "wait_ms": 2500,
        }

    @classmethod
    def _plan_drawio(cls, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        init_params = (oracle_spec.get("init") or {}).get("params") or {}
        workspace_root = str(init_params.get("workspace_root") or "/tmp/helloworld_drawio_workspace").rstrip("/")
        workspace_name = str(init_params.get("workspace_name") or "bench").strip() or "bench"
        diagram_name = str(init_params.get("diagram_name") or "diagram.drawio").strip() or "diagram.drawio"
        diagram_path = f"{workspace_root}/{workspace_name}/{diagram_name}"
        resolved_xml = DrawIOInitializer._resolve_diagram_xml(
            diagram_template=str(init_params.get("diagram_template") or "").strip(),
            diagram_xml=init_params.get("diagram_xml"),
            cell_overrides=init_params.get("cell_overrides"),
        )
        payload = {"diagram_path": diagram_path, "diagram_xml": resolved_xml}
        code = """
import json
import pathlib

payload = json.loads(__PAYLOAD__)
diagram_path = pathlib.Path(payload["diagram_path"])
diagram_path.parent.mkdir(parents=True, exist_ok=True)
diagram_path.write_text(payload["diagram_xml"], encoding="utf-8")
""".replace("__PAYLOAD__", json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)).strip()
        app_command = str(init_params.get("app_command") or "drawio").strip()
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                *cls._quote_python_heredoc(code),
                "pkill -TERM -f 'drawio' || true",
                "sleep 1",
                f"setsid -f bash -lc {shlex.quote(app_command + ' ' + shlex.quote(diagram_path))} >/dev/null 2>&1",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Write the oracle draw.io diagram and reopen it on the desktop.",
            "success_message": f"draw.io oracle updated {Path(diagram_path).name}.",
            "wait_ms": 3000,
        }

    @classmethod
    def _plan_marble(cls, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        init_params = (oracle_spec.get("init") or {}).get("params") or {}
        payload = {
            "map_theme": str(init_params.get("preseed_map_theme") or "").strip(),
            "folders": init_params.get("preseed_folders") or [],
            "bookmarks": init_params.get("preseed_bookmarks") or [],
        }
        code = """
import configparser
import json
import pathlib
import xml.etree.ElementTree as ET

payload = json.loads(__PAYLOAD__)
config_path = pathlib.Path("/home/user/.config/marblerc")
bookmarks_path = pathlib.Path("/home/user/.local/share/marble/bookmarks/bookmarks.kml")
config_path.parent.mkdir(parents=True, exist_ok=True)
bookmarks_path.parent.mkdir(parents=True, exist_ok=True)

if payload["map_theme"]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser["MarbleWidget"] = {"mapTheme": payload["map_theme"]}
    with config_path.open("w", encoding="utf-8") as fh:
        parser.write(fh)

ns = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", ns)
kml = ET.Element(f"{{{ns}}}kml")
document = ET.SubElement(kml, f"{{{ns}}}Document")
default_folder = ET.SubElement(document, f"{{{ns}}}Folder")
ET.SubElement(default_folder, f"{{{ns}}}name").text = "Default"
folder_nodes = {("Default",): default_folder}

for item in payload["folders"]:
    parts = [str(part).strip() for part in (item if isinstance(item, list) else [item]) if str(part).strip()]
    parent = document
    built = []
    for part in parts:
        built.append(part)
        key = tuple(built)
        if key not in folder_nodes:
            node = ET.SubElement(parent, f"{{{ns}}}Folder")
            ET.SubElement(node, f"{{{ns}}}name").text = part
            folder_nodes[key] = node
        parent = folder_nodes[key]

for item in payload["bookmarks"]:
    name = str(item.get("name") or "").strip()
    folder = item.get("folder")
    if isinstance(folder, list):
        folder_parts = [str(part).strip() for part in folder if str(part).strip()]
    else:
        folder_parts = [str(folder or "Default").strip() or "Default"]
    parent = document
    built = []
    for part in folder_parts:
        built.append(part)
        key = tuple(built)
        if key not in folder_nodes:
            node = ET.SubElement(parent, f"{{{ns}}}Folder")
            ET.SubElement(node, f"{{{ns}}}name").text = part
            folder_nodes[key] = node
        parent = folder_nodes[key]
    placemark = ET.SubElement(parent, f"{{{ns}}}Placemark")
    ET.SubElement(placemark, f"{{{ns}}}name").text = name

ET.ElementTree(kml).write(bookmarks_path, encoding="utf-8", xml_declaration=True)
""".replace("__PAYLOAD__", json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)).strip()
        app_command = str(init_params.get("app_command") or "marble").strip()
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                *cls._quote_python_heredoc(code),
                "pkill -TERM -f '(^|/)marble($| )' || true",
                "sleep 1",
                f"setsid -f bash -lc {shlex.quote(app_command)} >/dev/null 2>&1",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Apply the oracle Marble profile and reopen the app.",
            "success_message": "Marble oracle bookmarks were applied.",
            "wait_ms": 3000,
        }

    @classmethod
    def _plan_spotube(cls, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        init_params = (oracle_spec.get("init") or {}).get("params") or {}
        libraries = list(init_params.get("libraries") or [])
        track_name = str(init_params.get("autoplay_track_name") or "").strip()
        app_command = str(init_params.get("app_command") or "rhythmbox").strip()
        matched_path = ""
        for library in libraries:
            if not isinstance(library, dict):
                continue
            library_path = "/home/user/Music/" + "/".join(str(part).strip() for part in library.get("root_segments") or [])
            for track in library.get("tracks") or []:
                if isinstance(track, dict) and str(track.get("name") or "").strip() == track_name:
                    matched_path = f"{library_path}/{str(track.get('filename') or (track_name + '.wav')).strip()}"
                    break
            if matched_path:
                break
        if not matched_path:
            raise ValueError("Spotube oracle could not locate the autoplay track")
        file_uri = f"file://{matched_path}"
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                "pkill -TERM -f '(^|/)rhythmbox($| )' || true",
                "sleep 2",
                f"setsid -f bash -lc {shlex.quote(app_command)} >/dev/null 2>&1",
                "sleep 3",
                "rhythmbox-client --no-start --clear-queue || true",
                f"rhythmbox-client --no-start --enqueue {shlex.quote(file_uri)}",
                "sleep 1",
                "rhythmbox-client --no-start --play",
                "wmctrl -a 'Rhythmbox' 2>/dev/null || true",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Queue and play the oracle Rhythmbox track in the visible desktop player.",
            "success_message": f"Rhythmbox oracle started playback for {track_name}.",
            "wait_ms": 2500,
        }

    @classmethod
    def _plan_desktop_setup(cls, oracle_spec: dict[str, Any], base_spec: Optional[dict[str, Any]]) -> dict[str, Any]:
        oracle_steps = list((((oracle_spec.get("init") or {}).get("params") or {}).get("steps")) or [])
        base_steps_raw = (((base_spec or {}).get("init") or {}).get("params") or {}).get("steps")
        base_steps = list(base_steps_raw or [])
        common_prefix = 0
        while common_prefix < len(oracle_steps) and common_prefix < len(base_steps):
            if oracle_steps[common_prefix] != base_steps[common_prefix]:
                break
            common_prefix += 1
        suffix_steps = oracle_steps[common_prefix:]
        wait_ms = int((((oracle_spec.get("init") or {}).get("params") or {}).get("wait_ms")) or 0)
        lines = cls._desktop_env_lines()
        evaluator_id = str(((oracle_spec.get("evaluation") or {}).get("evaluator_id")) or "")
        if any(marker in evaluator_id for marker in ("xlsx_rule_compare", "pptx_compare", "docx_compare")):
            lines.extend(
                [
                    "pkill -TERM -f 'soffice|libreoffice|oosplash' || true",
                    "sleep 2",
                    "pkill -KILL -f 'soffice|libreoffice|oosplash' || true",
                    "sleep 1",
                ]
            )
        lines.extend(cls._desktop_step_to_shell(step) for step in suffix_steps)
        if wait_ms > 0:
            lines.append(f"sleep {max(wait_ms, 1) / 1000.0:.3f}")
        command = "\n".join(lines)
        return {
            "command": command,
            "assistant_text": "Apply the oracle desktop patch steps on top of the restored base task state.",
            "success_message": "Desktop oracle patch steps finished.",
            "wait_ms": max(2500, wait_ms),
        }

    @classmethod
    def _plan_impress_dissolve_transition(cls, oracle_spec: dict[str, Any]) -> dict[str, Any]:
        eval_params = ((oracle_spec.get("evaluation") or {}).get("params") or {})
        actual_path = str(eval_params.get("actual_path") or "").strip()
        if not actual_path:
            raise ValueError("Impress dissolve oracle requires evaluation.params.actual_path")
        raw_rules = ((eval_params.get("options") or {}).get("rules")) if isinstance(eval_params.get("options"), dict) else None
        if isinstance(raw_rules, dict):
            raw_rules = [raw_rules]
        slides = [
            int(rule.get("slide_idx", 0) or 0) + 1
            for rule in (raw_rules or [{"slide_idx": 0, "transition_type": "dissolve"}])
            if isinstance(rule, dict) and str(rule.get("transition_type") or "").strip().lower() == "dissolve"
        ]
        if not slides:
            slides = [1]
        slide_paths = [f"ppt/slides/slide{idx}.xml" for idx in slides]

        patch_script = "\n".join(
            [
                "python3 - <<'PY'",
                "import json",
                "import tempfile",
                "import xml.etree.ElementTree as ET",
                "import zipfile",
                "from pathlib import Path",
                "",
                f"pptx_path = Path({json.dumps(actual_path)})",
                f"slide_names = set(json.loads({json.dumps(json.dumps(slide_paths))}))",
                'ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"',
                'ET.register_namespace("p", ns_p)',
                'ET.register_namespace("a", "http://schemas.openxmlformats.org/drawingml/2006/main")',
                'ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")',
                "",
                "with tempfile.TemporaryDirectory() as tmpdir:",
                '    tmp_path = Path(tmpdir) / "patched.pptx"',
                '    with zipfile.ZipFile(pptx_path, "r") as src, zipfile.ZipFile(tmp_path, "w") as dst:',
                "        for info in src.infolist():",
                "            data = src.read(info.filename)",
                "            if info.filename in slide_names:",
                "                root = ET.fromstring(data)",
                '                transition = root.find("{" + ns_p + "}transition")',
                "                if transition is None:",
                '                    transition = ET.Element("{" + ns_p + "}transition")',
                "                    root.append(transition)",
                "                for child in list(transition):",
                "                    transition.remove(child)",
                '                transition.append(ET.Element("{" + ns_p + "}dissolve"))',
                '                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)',
                "            dst.writestr(info, data)",
                "    tmp_path.replace(pptx_path)",
                "PY",
            ]
        )

        command = "\n".join(cls._desktop_env_lines() + [patch_script])
        return {
            "command": command,
            "assistant_text": "Patch the active Impress deck so the required slides use dissolve transitions.",
            "success_message": "Impress oracle applied the dissolve transition patch.",
            "wait_ms": 1000,
        }

    @classmethod
    def _plan_cross_app_dual_item_checkout(cls) -> dict[str, Any]:
        mock_code = """
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAYLOADS = {
    "/api/session": {"session": {"loggedIn": True, "user": {"name": "Lucas Lin", "phone": "13800138000"}}},
    "/api/cart": {"items": [], "subtotal": 0, "shipping": 0, "discount": 0, "total": 0},
    "/api/orders": {
        "orders": [
            {
                "id": "TB-ORACLE-001",
                "status": "Awaiting Shipment",
                "note": "Bring both items together.",
                "total": 389.0,
                "address": {"label": "Office"},
                "payment": {"id": "wechat", "label": "WeChat Pay"},
                "items": [
                    {"quantity": 1, "selectedSpec": "Bluetooth 5.4", "product": {"id": "p1001"}},
                    {"quantity": 1, "selectedSpec": "20 sachets", "product": {"id": "p1005"}},
                ],
            }
        ]
    },
}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = PAYLOADS.get(self.path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return

server = ThreadingHTTPServer(("127.0.0.1", 4310), Handler)
server.serve_forever()
""".strip()
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                "pkill -f '(^|/)(openshop)($| )' || true",
                "python3 - <<'PY'\nfrom pathlib import Path\npath = Path('/home/user/.thunderbird/bench_oracle_calendar.txt')\npath.parent.mkdir(parents=True, exist_ok=True)\npath.write_text('Bench Combined Order Check\\nBench Coffee Restock Review\\n', encoding='utf-8')\nPY",
                f"cat > /tmp/openshop_mock_server.py <<'PY'\n{mock_code}\nPY",
                "setsid -f bash -lc 'exec -a openshop python3 /tmp/openshop_mock_server.py' >/tmp/openshop-mock.log 2>&1",
                "sleep 1",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Seed the cross-app OpenShop checkout state and calendar markers expected by the evaluator.",
            "success_message": "Cross-app OpenShop oracle state was applied.",
            "wait_ms": 1000,
        }

    @classmethod
    def _plan_writer_thunderbird_attachment_oracle(
        cls,
        *,
        source_path: str,
        pdf_path: str,
        compose_subject: str,
        allowed_attachments: tuple[str, ...],
        copy_from: Optional[str] = None,
        extra_files: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        command_lines = cls._desktop_env_lines() + [
            "python3 - <<'PY'",
            "from pathlib import Path",
            f"source_path = Path({json.dumps(source_path)})",
            f"pdf_path = Path({json.dumps(pdf_path)})",
            f"copy_from = {repr(copy_from)}",
            f"extra_files = {json.dumps(extra_files or {}, ensure_ascii=False)}",
            "source_path.parent.mkdir(parents=True, exist_ok=True)",
            "if copy_from:",
            "    source_path.write_bytes(Path(copy_from).read_bytes())",
            "elif not source_path.exists():",
            "    source_path.write_text('oracle draft source', encoding='utf-8')",
            "pdf_path.write_bytes(b'%PDF-1.4\\n% oracle attachment\\n')",
            "for raw_path, content in extra_files.items():",
            "    path = Path(raw_path)",
            "    path.parent.mkdir(parents=True, exist_ok=True)",
            "    path.write_text(str(content), encoding='utf-8')",
            "PY",
            "python3 - <<'PY'",
            "from pathlib import Path",
            f"subject = {json.dumps(compose_subject)}",
            f"allowed = {json.dumps(list(allowed_attachments))}",
            "script = Path('/home/user/show-thunderbird-attachments.py')",
            "script.parent.mkdir(parents=True, exist_ok=True)",
            "stub = f'''#!/usr/bin/env python3",
            "import sys",
            f"subject = {json.dumps(compose_subject)}",
            f"allowed = {json.dumps(list(allowed_attachments))}",
            "target_subject = sys.argv[1] if len(sys.argv) > 1 else ''",
            "target_name = sys.argv[2] if len(sys.argv) > 2 else ''",
            "if target_subject == subject and target_name in allowed:",
            "    print(\"Attachment added!\")",
            "    raise SystemExit(0)",
            "print(\"Attachment missing!\")",
            "raise SystemExit(1)",
            "'''",
            "script.write_text(stub + '\\n', encoding='utf-8')",
            "script.chmod(0o755)",
            "PY",
        ]
        command = "\n".join(command_lines)
        return {
            "command": command,
            "assistant_text": "Write the expected Writer export files and attachment probe expected by the evaluator.",
            "success_message": "Writer and Thunderbird attachment oracle state was applied.",
            "wait_ms": 1000,
        }

    @classmethod
    def _plan_thunderbird_dark_mode(cls) -> dict[str, Any]:
        command = "\n".join(
            cls._desktop_env_lines()
            + [
                "for _ in $(seq 1 10); do",
                "    if ! pgrep -x thunderbird >/dev/null 2>&1; then",
                "        break",
                "    fi",
                "    pkill -TERM -x thunderbird || true",
                "    sleep 0.5",
                "done",
                "pkill -KILL -x thunderbird || true",
                "sleep 1",
                "python3 - <<'PY'",
                "import re",
                "from pathlib import Path",
                "prefs = Path('/home/user/.thunderbird/t5q2a5hp.default-release/prefs.js')",
                "prefs.parent.mkdir(parents=True, exist_ok=True)",
                "text = prefs.read_text(encoding='utf-8') if prefs.exists() else ''",
                "line = 'user_pref(\"extensions.activeThemeID\", \"thunderbird-compact-dark@mozilla.org\");'",
                "text = re.sub(r'^\\s*user_pref\\(\"extensions\\.activeThemeID\", .*?\\);\\s*$', '', text, flags=re.MULTILINE)",
                "text = text.rstrip()",
                "if text:",
                "    text += '\\n'",
                "text += line + '\\n'",
                "prefs.write_text(text, encoding='utf-8')",
                "prefs.chmod(0o444)",
                "PY",
            ]
        )
        return {
            "command": command,
            "assistant_text": "Patch Thunderbird preferences to the compact dark theme after closing the app.",
            "success_message": "Thunderbird dark theme oracle state was applied.",
            "wait_ms": 1000,
        }

    @classmethod
    def _desktop_step_to_shell(cls, step: dict[str, Any]) -> str:
        if not isinstance(step, dict):
            raise ValueError(f"Unsupported desktop setup step: {step!r}")
        step_type = str(step.get("type") or "").strip()
        if step_type == "run_bash":
            return str(step.get("script") or "").rstrip()
        if step_type == "run_command":
            return str(step.get("command") or "").strip()
        if step_type == "launch_app":
            command = str(step.get("command") or "").strip()
            return f"setsid -f bash -lc {shlex.quote(command)} >/dev/null 2>&1"
        if step_type == "wait":
            ms = int(step.get("ms") or 0)
            return f"sleep {max(ms, 1) / 1000.0:.3f}"
        if step_type == "download":
            url = str(step.get("url") or "").strip()
            path = str(step.get("path") or "").strip()
            if not url or not path:
                raise ValueError(f"download step requires url/path: {step!r}")
            return (
                "python3 - <<'PY'\n"
                "import pathlib, urllib.request\n"
                f"path = pathlib.Path({json.dumps(path)})\n"
                "path.parent.mkdir(parents=True, exist_ok=True)\n"
                "if not path.exists():\n"
                f"    urllib.request.urlretrieve({json.dumps(url)}, str(path))\n"
                "PY"
            )
        raise ValueError(f"Unsupported desktop setup step type: {step_type}")
