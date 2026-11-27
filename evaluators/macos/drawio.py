"""Evaluate macOS draw.io diagram files."""

from __future__ import annotations

import base64
import html
import json
import re
import zlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


_LAUNCH_MATRIX_EXPECTED = (
    Path(__file__).resolve().parents[2]
    / "tasks/v1/macos/files/drawio/launch_matrix_sync/expected/launch_matrix_sync.drawio"
)


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


def _normalize_layout_number(raw_value: str) -> str:
    """Compare decimal spellings exactly, without float rounding or defaults."""
    value = raw_value.strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
        return value
    try:
        number = Decimal(value)
    except InvalidOperation:
        return value
    if number.is_zero():
        return "0"
    sign, digits, exponent = number.as_tuple()
    coefficient = list(digits)
    while coefficient[-1] == 0:
        coefficient.pop()
        exponent += 1
    return f"{'-' if sign else ''}{''.join(str(digit) for digit in coefficient)}e{exponent}"


def _normalize_style(raw_style: str) -> dict[str, Any]:
    named_styles: list[str] = []
    values: dict[str, str] = {}
    for token in raw_style.split(";"):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            # Named styles may inherit in order; only explicit key order is immaterial.
            named_styles.append(token)
            continue
        key, value = token.split("=", 1)
        values[key.strip()] = _normalize_layout_number(value)
    return {"named_styles": named_styles, "values": values}


def _normalize_geometry(element: ET.Element) -> dict[str, Any]:
    return {
        "tag": element.tag,
        "attributes": {
            key: _normalize_layout_number(value) for key, value in element.attrib.items()
        },
        "children": [_normalize_geometry(child) for child in element],
    }


def extract_drawio_semantics(raw_xml: str, *, include_layout: bool = False) -> dict[str, Any]:
    root = ET.fromstring(raw_xml)
    compressed = str(root.attrib.get("compressed", "true")).strip().lower() == "true"

    pages: list[dict[str, Any]] = []
    for diagram_el in root.findall("diagram"):
        graph_root = _decode_diagram_payload(diagram_el, compressed=compressed)
        cells: dict[str, dict[str, Any]] = {}
        shape_ids: list[str] = []
        layout_cells: dict[str, dict[str, Any]] = {}

        root_el = graph_root.find("root")
        for entry in list(root_el) if root_el is not None else []:
            if entry.tag == "mxCell":
                cell_el = entry
                cell_id = str(cell_el.attrib.get("id") or "").strip()
                raw_value = cell_el.attrib.get("value")
            else:
                # mxCellCodec moves the ID onto a user-object wrapper and
                # stores its display text in the wrapper's label attribute.
                cell_el = entry.find("mxCell")
                if cell_el is None:
                    continue
                cell_id = str(entry.attrib.get("id") or "").strip()
                raw_value = entry.attrib.get("label")

            if any(str(cell_el.attrib.get(kind) or "").strip() == "1" for kind in ("vertex", "edge")):
                shape_ids.append(cell_id)
            if include_layout and cell_id:
                # Include the root/layer cells: changing an ancestor's parent or
                # geometry can move the rectangles while their own x/y stay intact.
                layout_cells[cell_id] = {
                    "parent": str(cell_el.attrib.get("parent") or "").strip(),
                    "style": _normalize_style(str(cell_el.attrib.get("style") or "")),
                    "geometry": [_normalize_geometry(item) for item in cell_el.findall("mxGeometry")],
                }
            if not cell_id or cell_id in {"0", "1"}:
                continue

            value = _normalize_value(raw_value)
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

        page = {
            "id": str(diagram_el.attrib.get("id") or "").strip(),
            "name": str(diagram_el.attrib.get("name") or "").strip(),
            "cells": cells,
            "shape_ids": shape_ids,
        }
        if include_layout:
            page["layout_cells"] = layout_cells
        pages.append(page)

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

        # This task explicitly permits text replacement only. Keep other draw.io
        # tasks' existing label/membership contract unchanged.
        preserve_layout = expected_path.resolve() == _LAUNCH_MATRIX_EXPECTED
        try:
            actual_semantics = extract_drawio_semantics(actual_xml, include_layout=preserve_layout)
            expected_semantics = extract_drawio_semantics(expected_xml, include_layout=preserve_layout)
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

            actual_shape_ids = actual_page["shape_ids"]
            expected_shape_ids = expected_page["shape_ids"]
            if sorted(actual_shape_ids) != sorted(expected_shape_ids):
                failures.append(
                    f"shape IDs mismatch on page {expected_page['name']!r}: "
                    f"expected count {len(expected_shape_ids)}, observed {len(actual_shape_ids)}; "
                    f"missing={sorted(set(expected_shape_ids) - set(actual_shape_ids))}, "
                    f"unexpected={sorted(set(actual_shape_ids) - set(expected_shape_ids))}"
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

            if preserve_layout:
                actual_layout = actual_page["layout_cells"]
                for cell_id, expected_cell in expected_page["layout_cells"].items():
                    actual_cell = actual_layout.get(cell_id)
                    if actual_cell is None:
                        failures.append(f"missing layout cell {cell_id} on page {expected_page['name']}")
                        continue
                    for field in ("parent", "style", "geometry"):
                        if actual_cell[field] != expected_cell[field]:
                            failures.append(
                                f"cell {cell_id} {field} mismatch on page {expected_page['name']}: "
                                f"expected {expected_cell[field]!r}, observed {actual_cell[field]!r}"
                            )

        status = EvalStatus.PASS if not failures else EvalStatus.FAIL
        message = (
            ("draw.io file matches expected labels and preserved layout" if preserve_layout
             else "draw.io file matches expected labels")
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
