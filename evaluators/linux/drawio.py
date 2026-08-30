"""File-backed evaluator for draw.io desktop tasks on Linux."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class DrawIOFileEvaluator(BaseEvaluator):
    """Validate draw.io task outcomes by checking shape labels in the saved XML file."""

    DEFAULT_TIMEOUT = 20

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        diagram_path = str(params.get("diagram_path") or "").strip()
        cell_expectations = params.get("cells")
        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)

        if not diagram_path:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.diagram_path is required")
        if not isinstance(cell_expectations, list) or not cell_expectations:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.cells must be a non-empty list")

        script = f"""python3 - <<'PY'
import json
import pathlib
import xml.etree.ElementTree as ET

diagram_path = pathlib.Path({json.dumps(diagram_path, ensure_ascii=False)})
if not diagram_path.exists():
    print(json.dumps({{"error": "file_not_found", "diagram_path": str(diagram_path)}}))
    raise SystemExit(0)

try:
    tree = ET.parse(diagram_path)
    root = tree.getroot()
except Exception as exc:
    print(json.dumps({{"error": "parse_error", "message": str(exc), "diagram_path": str(diagram_path)}}))
    raise SystemExit(0)

cells = []
for node in root.iter("mxCell"):
    node_id = node.attrib.get("id")
    if not node_id:
        continue
    cells.append(
        {{
            "id": node_id,
            "value": node.attrib.get("value", ""),
            "style": node.attrib.get("style", ""),
        }}
    )

print(json.dumps({{"diagram_path": str(diagram_path), "cells": cells}}, ensure_ascii=False))
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
            return EvalResult(status=EvalStatus.ERROR, message=f"draw.io evaluator returned invalid JSON: {exc}: {output}")

        error = str(payload.get("error") or "")
        if error == "file_not_found":
            return EvalResult(status=EvalStatus.FAIL, message=f"diagram file not found: {diagram_path}", metadata=payload)
        if error:
            return EvalResult(status=EvalStatus.ERROR, message=f"draw.io evaluator error: {error}", metadata=payload)

        by_id = {str(item.get("id") or ""): dict(item) for item in payload.get("cells") or []}

        try:
            for expected in cell_expectations:
                if not isinstance(expected, Mapping):
                    continue
                cell_id = str(expected.get("id") or "").strip()
                actual = by_id.get(cell_id)
                assert actual is not None, f"missing cell in diagram: {cell_id}"
                actual_value = str(actual.get("value") or "")
                if "equals" in expected:
                    expected_value = str(expected.get("equals") or "")
                    assert actual_value == expected_value, f"cell {cell_id} expected {expected_value!r}, got {actual_value!r}"
                if "contains" in expected:
                    needle = str(expected.get("contains") or "")
                    assert needle in actual_value, f"cell {cell_id} expected to contain {needle!r}"
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=payload)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"draw.io evaluator failed: {exc}", metadata=payload)

        return EvalResult(status=EvalStatus.PASS, message="draw.io file evaluation passed", metadata=payload)
