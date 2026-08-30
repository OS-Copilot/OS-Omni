"""Deterministic macOS oracle adapter.

This adapter serves two neighboring oracle lanes:

1. file/materialization oracles, where the final evaluator-visible artifact can
   be written directly inside the guest; and
2. scripted GUI oracles, where the oracle replays a bounded deterministic
   action list through the same runtime tool surface used by benchmark runs.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping

from platforms.macos.host.core.oracle_specs import find_oracle_spec

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class MacOSScriptOracleAdapter(ProviderAdapter):
    provider_name = "macos_script_oracle"
    supported_response_modes = {"tool_calling", "json_text"}
    _WEEKDAY_INDEX = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        spec = self._resolve_oracle_spec(request)
        step_index = self._step_index(request.messages, request.metadata)
        scripted_actions = self._oracle_actions(spec)

        if scripted_actions:
            action = (
                dict(scripted_actions[step_index])
                if step_index < len(scripted_actions)
                else {
                    "type": "success",
                    "message": f"Oracle completed {self._oracle_for(spec)}.",
                    "assistant_text": "The scripted macOS oracle plan is complete.",
                }
            )
        elif step_index == 0:
            action = self._build_materialize_action(spec)
        else:
            action = {
                "type": "success",
                "message": f"Oracle completed {self._oracle_for(spec)}.",
                "assistant_text": "The deterministic macOS oracle state is now in place.",
            }

        action_type = str(action.get("type") or "").strip()
        assistant_text = str(action.get("assistant_text") or f"macOS oracle step {step_index + 1}: {action_type}")
        tool_payload = {k: v for k, v in action.items() if k not in {"type", "assistant_text"}}

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(tool_payload, ensure_ascii=False),
                        call_id=f"macos-script-oracle-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={
                    "provider": self.provider_name,
                    "task_id": spec.get("task_id"),
                    "oracle_for": self._oracle_for(spec),
                    "step_index": step_index,
                },
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        return ProviderResult(
            text=self._code_adapter_text(action),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={
                "provider": self.provider_name,
                "task_id": spec.get("task_id"),
                "oracle_for": self._oracle_for(spec),
                "step_index": step_index,
            },
        )

    @staticmethod
    def _code_adapter_text(action: Mapping[str, Any]) -> str:
        action_type = str(action.get("type") or "").strip()
        assistant_text = str(
            action.get("assistant_text")
            or action.get("message")
            or action_type
            or "macOS script oracle action"
        ).strip()

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
                "fd, path = tempfile.mkstemp(prefix='helloworld_macos_script_oracle_', suffix='.sh')\n"
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
            message = str(action.get("message") or "macOS script oracle plan completed.")
            code = f"print('__HELLOWORLD_DONE__:{message}')\n"
        elif action_type == "fail":
            message = str(action.get("reason") or action.get("message") or "macOS script oracle failed.")
            code = f"print('__HELLOWORLD_FAIL__:{message}')\n"
        else:
            code = f"raise RuntimeError({json.dumps('Unsupported macOS script oracle action: ' + action_type)})\n"

        return f"{assistant_text}\n```python\n{code}```"

    @staticmethod
    def _step_index(messages: List[Message], metadata: Mapping[str, Any] | None = None) -> int:
        if isinstance(metadata, Mapping):
            completed_step_count = metadata.get("completed_step_count")
            if isinstance(completed_step_count, int) and completed_step_count >= 0:
                return completed_step_count
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    @staticmethod
    def _oracle_for(spec: Mapping[str, Any]) -> str:
        metadata = spec.get("metadata") if isinstance(spec.get("metadata"), Mapping) else {}
        return str((metadata or {}).get("oracle_for") or spec.get("task_id") or "").strip()

    @classmethod
    def _oracle_actions(cls, spec: Mapping[str, Any]) -> list[dict[str, Any]]:
        metadata = spec.get("metadata") if isinstance(spec.get("metadata"), Mapping) else {}
        actions = (metadata or {}).get("oracle_actions")
        if not isinstance(actions, list):
            return []
        return [
            cls._resolve_action_templates(dict(item))
            for item in actions
            if isinstance(item, Mapping) and str(item.get("type") or "").strip()
        ]

    @classmethod
    def _resolve_action_templates(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            marker = str(value.get("_oracle_value") or "").strip().lower()
            if marker == "date":
                return cls._render_oracle_date(value)
            return {
                key: cls._resolve_action_templates(item)
                for key, item in value.items()
                if key != "_oracle_value"
            }
        if isinstance(value, list):
            return [cls._resolve_action_templates(item) for item in value]
        return value

    @classmethod
    def _render_oracle_date(cls, spec: Mapping[str, Any]) -> str:
        reference = cls._parse_reference_time(spec.get("reference_time_iso"))
        ref_date = reference.date()
        relative_day = str(spec.get("relative_day") or spec.get("date_kind") or "").strip().lower()
        weekday_name = str(spec.get("weekday") or "").strip().lower()
        days_from_today = spec.get("days_from_today")

        if relative_day == "tomorrow":
            target_date = ref_date + timedelta(days=1)
        elif relative_day == "today":
            target_date = ref_date
        elif relative_day in {"this_week", "current_week"}:
            weekday_index = cls._WEEKDAY_INDEX.get(weekday_name)
            if weekday_index is None:
                raise ValueError(f"invalid oracle date weekday for {relative_day}: {weekday_name!r}")
            monday = ref_date - timedelta(days=ref_date.weekday())
            target_date = monday + timedelta(days=weekday_index)
        elif relative_day == "next_week":
            weekday_index = cls._WEEKDAY_INDEX.get(weekday_name)
            if weekday_index is None:
                raise ValueError(f"invalid oracle date weekday for next_week: {weekday_name!r}")
            monday = ref_date - timedelta(days=ref_date.weekday()) + timedelta(days=7)
            target_date = monday + timedelta(days=weekday_index)
        elif days_from_today is not None:
            target_date = ref_date + timedelta(days=int(days_from_today))
        else:
            raise ValueError("oracle date template requires relative_day/date_kind or days_from_today")

        format_name = str(spec.get("format") or "mdy_slash_2digit_year").strip().lower()
        if format_name == "mdy_slash_2digit_year":
            return f"{target_date.month}/{target_date.day}/{target_date.year % 100:02d}"
        if format_name == "ymd_dash":
            return target_date.isoformat()
        if "%" in format_name:
            return target_date.strftime(str(spec.get("format")))
        raise ValueError(f"unsupported oracle date format: {spec.get('format')!r}")

    @staticmethod
    def _parse_reference_time(raw: Any) -> datetime:
        text = str(raw or "").strip()
        if not text:
            return datetime.now().astimezone()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return parsed.astimezone()

    def _resolve_oracle_spec(self, request: ProviderRequest) -> dict[str, Any]:
        task_id = str(request.metadata.get("task_id") or "").strip()
        message_text = "\n".join(message.text_content() for message in request.messages)
        spec = find_oracle_spec(task_id=task_id, message_text=message_text)
        if spec is None:
            raise ValueError("macOS script oracle could not match the current oracle task.")
        return spec

    def _build_materialize_action(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        evaluation = spec.get("evaluation") if isinstance(spec.get("evaluation"), Mapping) else {}
        evaluator_id = str((evaluation or {}).get("evaluator_id") or "").strip()
        params = (evaluation or {}).get("params") if isinstance((evaluation or {}).get("params"), Mapping) else {}
        metadata = spec.get("metadata") if isinstance(spec.get("metadata"), Mapping) else {}
        task_source = Path(str(spec.get("_source_path") or "")).resolve()

        explicit_fixture = (metadata or {}).get("oracle_fixture")
        if isinstance(explicit_fixture, Mapping):
            actual_path = str(
                explicit_fixture.get("actual_path")
                or explicit_fixture.get("output_path")
                or params.get("remote_path")
                or params.get("actual_path")
                or params.get("output_path")
                or ""
            ).strip()
            expected_path_raw = str(
                explicit_fixture.get("expected_path")
                or explicit_fixture.get("expected_image_path")
                or ""
            ).strip()
            if not actual_path or not expected_path_raw:
                raise ValueError("oracle_fixture requires actual_path/output_path and expected_path")
            expected_path = self._resolve_local_path(expected_path_raw, task_source=task_source)
            payload = self._serialize_file_payload(expected_path)
            script = self._build_single_file_write_script(
                actual_path=actual_path,
                payload=payload,
                pre_script=str(explicit_fixture.get("pre_script") or "").strip() or None,
                post_script=str(explicit_fixture.get("post_script") or "").strip() or None,
            )
            return {
                "type": "run_bash_script",
                "script": script,
                "timeout": 90,
                "assistant_text": f"Materialize the explicit oracle fixture for {self._oracle_for(spec)}.",
            }

        if evaluator_id.endswith("VSCodiumWorkspaceEvaluator"):
            workspace_root = str(params.get("workspace_root") or "").strip()
            expected_root_raw = str(params.get("expected_root") or "").strip()
            compare_paths = [
                str(item).strip()
                for item in list(params.get("compare_paths") or [])
                if str(item).strip()
            ]
            if not workspace_root or not expected_root_raw or not compare_paths:
                raise ValueError("VSCodium oracle requires workspace_root, expected_root, and compare_paths")
            expected_root = self._resolve_local_path(expected_root_raw, task_source=task_source)
            manifest = {
                relative: self._serialize_file_payload((expected_root / relative).resolve())
                for relative in compare_paths
            }
            script = self._build_tree_write_script(workspace_root=workspace_root, manifest=manifest)
            return {
                "type": "run_bash_script",
                "script": script,
                "timeout": 90,
                "assistant_text": f"Materialize the expected VSCodium workspace files for {self._oracle_for(spec)}.",
            }

        actual_path = str(params.get("actual_path") or params.get("output_path") or "").strip()
        expected_path_raw = str(params.get("expected_path") or params.get("expected_image_path") or "").strip()
        if actual_path and expected_path_raw:
            expected_path = self._resolve_local_path(expected_path_raw, task_source=task_source)
            payload = self._serialize_file_payload(expected_path)
            script = self._build_single_file_write_script(actual_path=actual_path, payload=payload)
            return {
                "type": "run_bash_script",
                "script": script,
                "timeout": 90,
                "assistant_text": f"Materialize the evaluator target artifact for {self._oracle_for(spec)}.",
            }

        raise ValueError(
            f"Unsupported macOS script oracle evaluator: {evaluator_id or '<missing>'}"
        )

    @staticmethod
    def _resolve_local_path(raw_path: str, *, task_source: Path) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path.resolve()
        candidates = [
            (task_source.parent / path).resolve(),
            (task_source.parent.parent / path).resolve(),
            (Path.cwd() / path).resolve(),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return (Path.cwd() / path).resolve()

    @staticmethod
    def _serialize_file_payload(path: Path) -> dict[str, str]:
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"oracle fixture missing: {path}")
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "encoding": "base64",
                "content": base64.b64encode(raw).decode("ascii"),
            }
        return {
            "encoding": "text",
            "content": text,
        }

    @staticmethod
    def _build_single_file_write_script(
        *,
        actual_path: str,
        payload: Mapping[str, str],
        pre_script: str | None = None,
        post_script: str | None = None,
    ) -> str:
        manifest = json.dumps({"path": actual_path, "payload": dict(payload)}, ensure_ascii=False)
        parts: list[str] = []
        if pre_script:
            parts.append(pre_script.rstrip())
        parts.append(
            "python3 - <<'PY'\n"
            "import base64\n"
            "import json\n"
            "from pathlib import Path\n"
            f"spec = json.loads({manifest!r})\n"
            "path = Path(spec['path']).expanduser()\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "payload = dict(spec['payload'])\n"
            "encoding = str(payload.get('encoding') or '')\n"
            "content = str(payload.get('content') or '')\n"
            "if encoding == 'text':\n"
            "    path.write_text(content, encoding='utf-8')\n"
            "elif encoding == 'base64':\n"
            "    path.write_bytes(base64.b64decode(content.encode('ascii')))\n"
            "else:\n"
            "    raise SystemExit(f'unsupported encoding: {encoding}')\n"
            "print(str(path))\n"
            "PY"
        )
        if post_script:
            parts.append(post_script.rstrip())
        return "\n".join(parts)

    @staticmethod
    def _build_tree_write_script(*, workspace_root: str, manifest: Mapping[str, Mapping[str, str]]) -> str:
        payload_json = json.dumps(
            {"workspace_root": workspace_root, "files": manifest},
            ensure_ascii=False,
        )
        return (
            "python3 - <<'PY'\n"
            "import base64\n"
            "import json\n"
            "from pathlib import Path\n"
            f"spec = json.loads({payload_json!r})\n"
            "root = Path(spec['workspace_root']).expanduser()\n"
            "root.mkdir(parents=True, exist_ok=True)\n"
            "for relative, payload in dict(spec.get('files') or {}).items():\n"
            "    target = root / relative\n"
            "    target.parent.mkdir(parents=True, exist_ok=True)\n"
            "    encoding = str(payload.get('encoding') or '')\n"
            "    content = str(payload.get('content') or '')\n"
            "    if encoding == 'text':\n"
            "        target.write_text(content, encoding='utf-8')\n"
            "    elif encoding == 'base64':\n"
            "        target.write_bytes(base64.b64decode(content.encode('ascii')))\n"
            "    else:\n"
            "        raise SystemExit(f'unsupported encoding for {relative}: {encoding}')\n"
            "print(str(root))\n"
            "PY"
        )
