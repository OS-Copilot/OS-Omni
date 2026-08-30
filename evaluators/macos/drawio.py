"""Evaluate macOS draw.io diagram files."""

from __future__ import annotations

import base64
import html
import json
import re
import zlib
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


def _resolve_local_path(raw_path: str, *, task: Any, run_dir: Any) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path

    task_source = getattr(task, "source_file", None)
    if task_source:
        candidate = (Path(task_source).expanduser().resolve().parent / path).resolve()
        if candidate.exists():
            return candidate

    if run_dir is not None:
        candidate = (Path(run_dir) / path).resolve()
        if candidate.exists():
            return candidate

    return (Path.cwd() / path).resolve()


def _normalize_value(value: str | None) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?i)<br\\s*/?>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _decode_diagram_payload(diagram_el: ET.Element, *, compressed: bool) -> ET.Element:
    if not compressed:
        graph_el = next(iter(diagram_el), None)
        if graph_el is None:
            raise ValueError("uncompressed draw.io diagram is missing mxGraphModel payload")
        return graph_el

    payload = diagram_el.text or ""
    compressed_bytes = base64.b64decode(payload)
    xml_bytes = zlib.decompress(compressed_bytes, -15)
    xml_text = unquote(xml_bytes.decode("utf-8"))
    return ET.fromstring(xml_text)


def extract_drawio_semantics(raw_xml: str) -> dict[str, Any]:
    root = ET.fromstring(raw_xml)
    compressed = str(root.attrib.get("compressed", "true")).strip().lower() == "true"

    pages: list[dict[str, Any]] = []
    for diagram_el in root.findall("diagram"):
        graph_root = _decode_diagram_payload(diagram_el, compressed=compressed)
        cells: dict[str, dict[str, Any]] = {}

        root_el = graph_root.find("root")
        for cell_el in root_el.findall("mxCell") if root_el is not None else []:
            cell_id = str(cell_el.attrib.get("id") or "").strip()
            if not cell_id or cell_id in {"0", "1"}:
                continue

            value = _normalize_value(cell_el.attrib.get("value"))
            if not value:
                continue

            cells[cell_id] = {
                "id": cell_id,
                "value": value,
                "vertex": str(cell_el.attrib.get("vertex") or "").strip() == "1",
                "edge": str(cell_el.attrib.get("edge") or "").strip() == "1",
                "parent": str(cell_el.attrib.get("parent") or "").strip(),
                "style": str(cell_el.attrib.get("style") or "").strip(),
            }

        pages.append(
            {
                "id": str(diagram_el.attrib.get("id") or "").strip(),
                "name": str(diagram_el.attrib.get("name") or "").strip(),
                "cells": cells,
            }
        )

    return {"pages": pages}


class DrawIODiagramEvaluator(BaseEvaluator):
    """Compare a saved draw.io file against an expected semantic fixture."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        task = context.get("task")
        run_dir = context.get("run_dir")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.get_file is required")

        actual_path = str(params.get("actual_path") or "").strip()
        expected_path_raw = str(params.get("expected_path") or "").strip()
        compare_page_names = bool(params.get("compare_page_names", True))

        if not actual_path or not expected_path_raw:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="DrawIO evaluation requires actual_path and expected_path",
            )

        expected_path = _resolve_local_path(expected_path_raw, task=task, run_dir=run_dir)
        if not expected_path.exists() or not expected_path.is_file():
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"expected fixture missing: {expected_path}",
            )

        try:
            actual_bytes = controller.get_file(actual_path)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"failed to fetch actual draw.io file: {exc}",
                metadata={"actual_path": actual_path},
            )

        try:
            actual_xml = actual_bytes.decode("utf-8")
            expected_xml = expected_path.read_text(encoding="utf-8")
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"failed to decode draw.io file: {exc}")

        try:
            actual_semantics = extract_drawio_semantics(actual_xml)
            expected_semantics = extract_drawio_semantics(expected_xml)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"failed to parse draw.io file: {exc}")

        failures: list[str] = []
        actual_pages = actual_semantics["pages"]
        expected_pages = expected_semantics["pages"]

        if len(actual_pages) != len(expected_pages):
            failures.append(
                f"page count mismatch: expected {len(expected_pages)}, observed {len(actual_pages)}"
            )

        actual_pages_by_id = {page["id"]: page for page in actual_pages}
        actual_pages_by_name = {page["name"]: page for page in actual_pages}

        for expected_page in expected_pages:
            actual_page = actual_pages_by_id.get(expected_page["id"])
            if actual_page is None:
                actual_page = actual_pages_by_name.get(expected_page["name"])
            if actual_page is None:
                failures.append(
                    f"missing page: id={expected_page['id']!r} name={expected_page['name']!r}"
                )
                continue

            if compare_page_names and actual_page["name"] != expected_page["name"]:
                failures.append(
                    f"page name mismatch for {expected_page['id']}: expected {expected_page['name']!r}, observed {actual_page['name']!r}"
                )

            actual_cells = actual_page["cells"]
            for cell_id, expected_cell in expected_page["cells"].items():
                actual_cell = actual_cells.get(cell_id)
                if actual_cell is None:
                    failures.append(f"missing cell {cell_id} on page {expected_page['name']}")
                    continue
                if actual_cell["value"] != expected_cell["value"]:
                    failures.append(
                        f"cell {cell_id} mismatch on page {expected_page['name']}: expected {expected_cell['value']!r}, observed {actual_cell['value']!r}"
                    )

        status = EvalStatus.PASS if not failures else EvalStatus.FAIL
        message = (
            "draw.io file matches expected labels"
            if not failures
            else "; ".join(failures)
        )
        return EvalResult(
            status=status,
            message=message,
            metadata={
                "actual_path": actual_path,
                "expected_path": str(expected_path),
                "actual_semantics": actual_semantics,
                "expected_semantics": expected_semantics,
                "failures": failures,
            },
        )
