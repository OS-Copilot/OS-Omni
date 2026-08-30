"""Task-specific oracle provider for Linux Wireshark benchmark sanity runs."""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class LinuxWiresharkOracleAdapter(ProviderAdapter):
    """Emit deterministic Linux shell commands that write the expected Wireshark outputs."""

    provider_name = "linux_wireshark_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    _TASK_SPECS: Dict[str, Dict[str, Any]] = {
        "export_dns": {
            "outputs": [
                {
                    "filter": "dns",
                    "path": "/tmp/helloworld_wireshark/dns_only.pcapng",
                }
            ],
            "wait_ms": 2500,
        },
        "export_protocol_bundle": {
            "outputs": [
                {
                    "filter": "dns",
                    "path": "/tmp/helloworld_wireshark/dns_only.pcapng",
                },
                {
                    "filter": "icmp",
                    "path": "/tmp/helloworld_wireshark/icmp_only.pcapng",
                },
                {
                    "filter": "http.request",
                    "path": "/tmp/helloworld_wireshark/http_request_only.pcapng",
                },
                {
                    "filter": "http.response",
                    "path": "/tmp/helloworld_wireshark/http_response_only.pcapng",
                },
                {
                    "filter": "arp",
                    "path": "/tmp/helloworld_wireshark/arp_only.pcapng",
                },
                {
                    "filter": "tcp.flags.syn == 1 && tcp.flags.ack == 0",
                    "path": "/tmp/helloworld_wireshark/syn_only.pcapng",
                },
                {
                    "filter": "tcp",
                    "path": "/tmp/helloworld_wireshark/tcp_only.pcapng",
                },
                {
                    "filter": "ip",
                    "path": "/tmp/helloworld_wireshark/ip_only.pcapng",
                },
                {
                    "filter": "udp",
                    "path": "/tmp/helloworld_wireshark/udp_only.pcapng",
                },
                {
                    "filter": "tcp.port == 80",
                    "path": "/tmp/helloworld_wireshark/tcp80_only.pcapng",
                },
                {
                    "filter": "http",
                    "path": "/tmp/helloworld_wireshark/http_only.pcapng",
                },
                {
                    "filter": 'http.request.uri == "/checkout" || http.response.code == 200',
                    "path": "/tmp/helloworld_wireshark/checkout_http_only.pcapng",
                },
                {
                    "filter": 'dns && dns.qry.name contains "bench.local"',
                    "path": "/tmp/helloworld_wireshark/bench_dns_only.pcapng",
                },
            ],
            "texts": [
                {
                    "path": "/tmp/helloworld_wireshark/protocol_bundle_manifest.txt",
                    "content": (
                        "DNS ICMP exported\n"
                        "HTTP request-response exported\n"
                        "ARP SYN exported\n"
                        "TCP IP UDP TCP80 exported\n"
                        "HTTP combined exported\n"
                        "checkout HTTP pair exported\n"
                        "bench DNS subset exported\n"
                    ),
                }
            ],
            "wait_ms": 5000,
        },
        "export_link_and_syn_bundle": {
            "outputs": [
                {
                    "filter": "arp",
                    "path": "/tmp/helloworld_wireshark/arp_only.pcapng",
                },
                {
                    "filter": "icmp",
                    "path": "/tmp/helloworld_wireshark/icmp_only.pcapng",
                },
                {
                    "filter": "tcp.flags.syn == 1 && tcp.flags.ack == 0",
                    "path": "/tmp/helloworld_wireshark/syn_only.pcapng",
                },
                {
                    "filter": 'dns && dns.qry.name contains "bench.local"',
                    "path": "/tmp/helloworld_wireshark/bench_dns_only.pcapng",
                },
                {
                    "filter": "dns",
                    "path": "/tmp/helloworld_wireshark/dns_all_for_link.pcapng",
                },
                {
                    "filter": "http.request",
                    "path": "/tmp/helloworld_wireshark/http_request_only.pcapng",
                },
                {
                    "filter": "http.response",
                    "path": "/tmp/helloworld_wireshark/http_response_only.pcapng",
                },
                {
                    "filter": "udp",
                    "path": "/tmp/helloworld_wireshark/udp_only.pcapng",
                },
                {
                    "filter": "tcp.port == 80",
                    "path": "/tmp/helloworld_wireshark/tcp80_only.pcapng",
                },
            ],
            "texts": [
                {
                    "path": "/tmp/helloworld_wireshark/link_syn_manifest.txt",
                    "content": (
                        "arp/syn split complete\n"
                        "ICMP echo pair exported\n"
                        "bench DNS isolated\n"
                        "all DNS copy exported\n"
                        "HTTP request-response plus UDP exported\n"
                        "TCP80 slice exported\n"
                    ),
                }
            ],
            "wait_ms": 5000,
        },
    }

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        task_key = self._resolve_task_key(request.messages)
        task_spec = self._task_spec(task_key)
        step_index = self._step_index(request.messages)

        if step_index == 0:
            action = {
                "type": "launch_app",
                "app_name": self._build_command(task_spec),
                "assistant_text": "Write the expected Wireshark export artifacts with tshark.",
            }
        elif step_index == 1:
            action = {
                "type": "wait",
                "ms": int(task_spec["wait_ms"]),
                "assistant_text": "Wait for the tshark export commands to finish.",
            }
        else:
            action = {
                "type": "success",
                "message": "Linux Wireshark oracle task completed.",
                "assistant_text": "The Linux Wireshark oracle task is complete.",
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
                        call_id=f"linux-wireshark-oracle-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={"provider": self.provider_name, "task_key": task_key, "step_index": step_index},
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        json_action = dict(action)
        json_action.pop("assistant_text", None)
        return ProviderResult(
            text=json.dumps(json_action, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={"provider": self.provider_name, "task_key": task_key, "step_index": step_index},
        )

    @staticmethod
    def _step_index(messages: List[Message]) -> int:
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    @classmethod
    def _task_spec(cls, task_key: str) -> Dict[str, Any]:
        spec = cls._TASK_SPECS.get(task_key)
        if not spec:
            raise ValueError(f"Unsupported Linux Wireshark oracle task: {task_key}")
        return spec

    @staticmethod
    def _resolve_task_key(messages: List[Message]) -> str:
        system_text = "\n".join(
            message.text_content()
            for message in messages
            if getattr(message, "role", "") == "system"
        ).lower()

        if (
            "/tmp/helloworld_wireshark/protocol_bundle_manifest.txt" in system_text
            or "/tmp/helloworld_wireshark/checkout_http_only.pcapng" in system_text
            or "/tmp/helloworld_wireshark/tcp_only.pcapng" in system_text
            or "/tmp/helloworld_wireshark/ip_only.pcapng" in system_text
        ):
            return "export_protocol_bundle"
        if "/tmp/helloworld_wireshark/link_syn_manifest.txt" in system_text:
            return "export_link_and_syn_bundle"
        if "/tmp/helloworld_wireshark/bench_dns_only.pcapng" in system_text:
            return "export_link_and_syn_bundle"
        if "/tmp/helloworld_wireshark/http_request_only.pcapng" in system_text:
            return "export_protocol_bundle"
        if "/tmp/helloworld_wireshark/dns_only.pcapng" in system_text:
            return "export_dns"
        raise ValueError("Linux Wireshark oracle could not match the current task instruction.")

    @staticmethod
    def _build_command(task_spec: Dict[str, Any]) -> str:
        command_code = LinuxWiresharkOracleAdapter._python_code(task_spec)
        return f"python3 -c {shlex.quote(command_code)}"

    @staticmethod
    def _python_code(task_spec: Dict[str, Any]) -> str:
        outputs = json.dumps(task_spec["outputs"], ensure_ascii=False)
        texts = json.dumps(task_spec.get("texts", []), ensure_ascii=False)
        return f"""
import json
import pathlib
import subprocess

source = pathlib.Path("/tmp/helloworld_wireshark/retail_mix.pcapng")
if not source.exists():
    raise SystemExit(f"missing source capture: {{source}}")

outputs = json.loads({json.dumps(outputs, ensure_ascii=False)})
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

texts = json.loads({json.dumps(texts, ensure_ascii=False)})
for item in texts:
    text_path = pathlib.Path(item["path"])
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(item["content"], encoding="utf-8")
""".strip()
