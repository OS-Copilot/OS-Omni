"""Shape membership and layout regressions against the launch-matrix fixture."""

from __future__ import annotations

import base64
import copy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from xml.etree import ElementTree as ET
import zlib

import pytest
import yaml

from core.evaluation import EvalStatus
from evaluators.macos.drawio import DrawIODiagramEvaluator


ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = ROOT / "tasks/v1/macos/drawio_launch_matrix_sync.yaml"
EXPECTED_FILE = ROOT / "tasks/v1/macos/files/drawio/launch_matrix_sync/expected/launch_matrix_sync.drawio"


class FileController:
    def __init__(self, content: bytes, expected_path: str):
        self.content = content
        self.expected_path = expected_path

    def get_file(self, path: str) -> bytes:
        assert path == self.expected_path
        return self.content


def actual_xml(case: str) -> bytes:
    original = EXPECTED_FILE.read_bytes()
    if case == "correct_expected":
        return original
    root = ET.fromstring(original)
    diagram = root.find("diagram")
    graph = diagram.find("mxGraphModel")
    cells = graph.find("root")
    if case in {"extra_wrapped_blank", "extra_wrapped_labeled", "duplicate_wrapped_id"}:
        extra = copy.deepcopy(next(cell for cell in cells if cell.get("id") == "card_1"))
        extra.attrib.pop("id")
        extra.attrib.pop("value", None)
        wrapper = ET.SubElement(cells, "object", {
            "id": "card_1" if case == "duplicate_wrapped_id" else "audit_wrapped_shape",
            "label": "Unexpected shape" if case == "extra_wrapped_labeled" else "",
        })
        wrapper.append(extra)
    elif case in {"equivalent_wrapped_save", "equivalent_wrapped_normalized_save"}:
        for cell in list(cells):
            if cell.get("vertex") == "1":
                wrapper = ET.Element("object", {"id": cell.attrib.pop("id"),
                                                 "label": cell.attrib.pop("value", "")})
                index = list(cells).index(cell)
                cells.remove(cell)
                wrapper.append(cell)
                cells.insert(index, wrapper)
        if case == "equivalent_wrapped_normalized_save":
            card = next(entry.find("mxCell") for entry in cells if entry.get("id") == "card_1")
            card.set("style", ";".join(reversed(card.get("style").rstrip(";").split(";"))).replace("fontSize=22", "fontSize=22.0"))
            card.find("mxGeometry").set("width", "1.80e2")
    elif case in {"extra_blank_vertex", "extra_labeled_vertex", "duplicate_blank_id"}:
        extra = copy.deepcopy(next(cell for cell in cells if cell.get("id") == "card_1"))
        extra.set("id", "card_1" if case == "duplicate_blank_id" else "audit_extra_shape")
        extra.set("value", "Unexpected shape" if case == "extra_labeled_vertex" else "")
        cells.append(extra)
    elif case == "delete_required_shape":
        cells.remove(next(cell for cell in cells if cell.get("id") == "card_1"))
    elif case == "wrong_label":
        next(cell for cell in cells if cell.get("id") == "card_1").set("value", "Wrong label")
    elif case == "save_normalization":
        # Metadata, numeric spelling, style-key order and cell order preserve layout.
        root.set("modified", "2026-11-05T00:00:00Z")
        root.set("agent", "draw.io Desktop save")
        graph.set("dx", "1801")
        card = next(cell for cell in cells if cell.get("id") == "card_1")
        card.set("style", ";".join(reversed(card.get("style").rstrip(";").split(";"))).replace("fontSize=22", "fontSize=22.0"))
        card.find("mxGeometry").set("x", "110.0")
        cells.remove(card)
        cells.append(card)
    elif case == "correct_compressed_save":
        encoded = quote(ET.tostring(graph, encoding="unicode"), safe="~()*!.'").encode("utf-8")
        compressor = zlib.compressobj(wbits=-15)
        packed = compressor.compress(encoded) + compressor.flush()
        diagram.remove(graph)
        diagram.text = base64.b64encode(packed).decode("ascii")
        root.set("compressed", "true")
    elif case.startswith("geometry_"):
        card = next(cell for cell in cells if cell.get("id") == "card_1")
        geometry = card.find("mxGeometry")
        if case == "geometry_missing":
            card.remove(geometry)
        elif case == "geometry_offset":
            ET.SubElement(geometry, "mxPoint", {"as": "offset", "x": "5", "y": "0"})
        elif case == "geometry_duplicate":
            extra = copy.deepcopy(geometry)
            extra.set("x", "9999")
            card.append(extra)
        elif case == "geometry_precision":
            geometry.set("x", "110.0000000000000000000000000001")
        else:
            field = case.removeprefix("geometry_")
            geometry.set(field, "1" if field == "relative" else "9999")
    elif case.startswith("style_"):
        card = next(cell for cell in cells if cell.get("id") == "card_1")
        style = card.get("style")
        if case == "style_shape":
            card.set("style", "ellipse;fillColor=#ff0000;")
        elif case == "style_fill":
            card.set("style", style.replace("fillColor=#dae8fc", "fillColor=#ff0000"))
        elif case == "style_font":
            card.set("style", style.replace("fontSize=22", "fontSize=23"))
        elif case == "style_precision":
            card.set("style", style.replace("fontSize=22", "fontSize=22.000000000000000000000000001"))
        elif case == "style_missing_key":
            card.set("style", style.replace("rounded=1;", ""))
        elif case == "style_extra_key":
            card.set("style", style + "rotation=15;")
        elif case == "style_missing":
            del card.attrib["style"]
        else:
            raise ValueError(case)
    elif case == "parent_shape":
        next(cell for cell in cells if cell.get("id") == "card_1").set("parent", "card_2")
    elif case == "parent_layer":
        next(cell for cell in cells if cell.get("id") == "1").set("parent", "card_2")
    elif case == "parent_missing_layer":
        cells.remove(next(cell for cell in cells if cell.get("id") == "1"))
    elif case == "parent_layer_geometry":
        layer = next(cell for cell in cells if cell.get("id") == "1")
        ET.SubElement(layer, "mxGeometry", {"x": "200", "y": "0", "as": "geometry"})
    else:
        raise ValueError(case)
    return ET.tostring(root, encoding="utf-8")


def evaluate_case(evaluator_type: type, case: str):
    task = yaml.safe_load(TASK_FILE.read_text(encoding="utf-8"))
    params = task["evaluation"]["params"]
    return evaluator_type().evaluate({
        "controller": FileController(actual_xml(case), params["actual_path"]),
        "params": params,
        "task": SimpleNamespace(source_file=TASK_FILE),
    })


@pytest.mark.parametrize("case", ["correct_expected", "correct_compressed_save", "save_normalization", "equivalent_wrapped_save", "equivalent_wrapped_normalized_save"])
def test_correct_saved_diagram_passes(case):
    result = evaluate_case(DrawIODiagramEvaluator, case)
    assert result.status == EvalStatus.PASS, result.message


@pytest.mark.parametrize("case", ["extra_blank_vertex", "extra_labeled_vertex", "duplicate_blank_id", "delete_required_shape", "extra_wrapped_blank", "extra_wrapped_labeled", "duplicate_wrapped_id", "wrong_label"])
def test_added_or_deleted_shape_fails(case):
    result = evaluate_case(DrawIODiagramEvaluator, case)
    assert result.status == EvalStatus.FAIL, result.message


@pytest.mark.parametrize("case", [
    "geometry_x", "geometry_y", "geometry_width", "geometry_height",
    "geometry_relative", "geometry_missing", "geometry_offset", "geometry_duplicate",
    "geometry_precision", "style_shape", "style_fill", "style_font", "style_precision",
    "style_missing_key", "style_extra_key", "style_missing", "parent_shape", "parent_layer",
    "parent_missing_layer", "parent_layer_geometry",
])
def test_changed_launch_matrix_layout_fails(case):
    result = evaluate_case(DrawIODiagramEvaluator, case)
    assert result.status == EvalStatus.FAIL, result.message


def test_unrelated_expected_fixture_keeps_existing_comparison_contract(tmp_path):
    expected = tmp_path / "other_diagram.drawio"
    expected.write_bytes(EXPECTED_FILE.read_bytes())
    params = {"actual_path": "/Users/bench/Downloads/other_diagram.drawio", "expected_path": str(expected)}
    result = DrawIODiagramEvaluator().evaluate({
        "controller": FileController(actual_xml("geometry_x"), params["actual_path"]),
        "params": params,
        "task": SimpleNamespace(id="macos.drawio.other_diagram"),
    })
    assert result.status == EvalStatus.PASS, result.message
