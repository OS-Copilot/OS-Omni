"""Artifact-backed evaluator for Wireshark desktop tasks on Linux."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class WiresharkArtifactEvaluator(BaseEvaluator):
    """Validate Wireshark task outputs through tshark and file inspection."""

    DEFAULT_TIMEOUT = 30

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        artifacts = params.get("artifacts")
        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)
        if not isinstance(artifacts, list) or not artifacts:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.artifacts must be a non-empty list")

        script = f"""python3 - <<'PY'
import json
import pathlib
import subprocess

artifacts = json.loads({json.dumps(json.dumps(artifacts, ensure_ascii=False), ensure_ascii=False)})
results = []

for item in artifacts:
    kind = str(item.get("kind") or "pcap")
    path = pathlib.Path(str(item.get("path") or ""))
    result = {{"kind": kind, "path": str(path), "exists": path.exists()}}
    if not path.exists():
        results.append(result)
        continue

    if kind == "pcap":
        total = subprocess.run(
            ["tshark", "-n", "-r", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        result["packet_count"] = len(total.stdout.splitlines())
        result["tshark_ok"] = total.returncode == 0
        result["tshark_stderr"] = total.stderr.strip()
        display_filter = str(item.get("all_match_filter") or "")
        if display_filter:
            filtered = subprocess.run(
                ["tshark", "-n", "-r", str(path), "-Y", display_filter],
                check=False,
                capture_output=True,
                text=True,
            )
            result["filtered_count"] = len(filtered.stdout.splitlines())
            result["filter_ok"] = filtered.returncode == 0
            result["filter_stderr"] = filtered.stderr.strip()
            result["all_match_filter"] = display_filter
        field_specs = item.get("field_values") or []
        if isinstance(field_specs, list) and field_specs:
            field_results = []
            for field_spec in field_specs:
                if not isinstance(field_spec, dict):
                    continue
                field_name = str(field_spec.get("field") or "").strip()
                if not field_name:
                    continue
                field_run = subprocess.run(
                    ["tshark", "-n", "-r", str(path), "-T", "fields", "-e", field_name],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                observed = [
                    value
                    for line in field_run.stdout.splitlines()
                    for value in line.split(",")
                    if value
                ]
                normalized = []
                for value in observed:
                    normalized.append(value)
                    if value.endswith("."):
                        normalized.append(value.rstrip("."))
                field_results.append({{
                    "field": field_name,
                    "values": normalized,
                    "ok": field_run.returncode == 0,
                    "stderr": field_run.stderr.strip(),
                }})
            result["field_values"] = field_results
    elif kind == "text":
        result["content"] = path.read_text(encoding="utf-8")

    results.append(result)

print(json.dumps({{"results": results}}, ensure_ascii=False))
PY"""
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=output or f"guest command failed with exit code {returncode}",
            )

        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"Wireshark evaluator returned invalid JSON: {exc}: {output}",
            )

        actual_results = {str(item.get("path") or ""): dict(item) for item in payload.get("results") or []}

        try:
            for expected in artifacts:
                if not isinstance(expected, Mapping):
                    continue
                path = str(expected.get("path") or "")
                actual = actual_results.get(path)
                assert actual is not None, f"missing evaluation payload for {path}"
                assert bool(actual.get("exists")), f"expected artifact to exist: {path}"
                kind = str(expected.get("kind") or "pcap")
                if kind == "pcap":
                    assert bool(actual.get("tshark_ok")), f"tshark could not read {path}"
                    if "packet_count" in expected:
                        expected_count = int(expected.get("packet_count") or 0)
                        actual_count = int(actual.get("packet_count") or 0)
                        assert actual_count == expected_count, (
                            f"expected {path} to have {expected_count} packets, got {actual_count}"
                        )
                    if "all_match_filter" in expected:
                        assert bool(actual.get("filter_ok")), f"tshark display filter failed for {path}"
                        total_count = int(actual.get("packet_count") or 0)
                        filtered_count = int(actual.get("filtered_count") or 0)
                        assert filtered_count == total_count, (
                            f"expected all packets in {path} to match {expected.get('all_match_filter')!r}"
                        )
                    for field_spec in expected.get("field_values") or []:
                        if not isinstance(field_spec, Mapping):
                            continue
                        field_name = str(field_spec.get("field") or "").strip()
                        actual_field = next(
                            (
                                dict(item)
                                for item in actual.get("field_values") or []
                                if str(item.get("field") or "") == field_name
                            ),
                            None,
                        )
                        assert actual_field is not None, f"missing field values for {field_name} in {path}"
                        assert bool(actual_field.get("ok")), f"tshark field extraction failed for {field_name} in {path}"
                        observed_values = {str(value) for value in actual_field.get("values") or []}
                        for required in field_spec.get("contains") or []:
                            assert str(required) in observed_values, (
                                f"expected field {field_name} in {path} to contain {required!r}"
                            )
                elif kind == "text":
                    content = str(actual.get("content") or "")
                    if "equals" in expected:
                        expected_text = str(expected.get("equals") or "")
                        assert content == expected_text, f"text mismatch for {path}"
                    if "contains" in expected:
                        needle = str(expected.get("contains") or "")
                        assert needle in content, f"expected {path} to contain {needle!r}"
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=payload)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Wireshark evaluator failed: {exc}", metadata=payload)

        return EvalResult(status=EvalStatus.PASS, message="Wireshark artifact evaluation passed", metadata=payload)
