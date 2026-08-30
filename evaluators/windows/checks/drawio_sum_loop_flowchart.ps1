$ErrorActionPreference = "Stop"

$documentPath = "C:\Users\User\Documents\drawio_sum_loop_flowchart.drawio"
if (-not (Test-Path $documentPath)) {
  Write-Output "EVAL_RESULT:FAIL diagram file not found"
  exit 0
}

$drawioProc = Get-Process "draw.io" -ErrorAction SilentlyContinue |
  Where-Object { $_.MainWindowHandle -ne 0 } |
  Select-Object -First 1

if ($null -ne $drawioProc) {
  Add-Type -AssemblyName Microsoft.VisualBasic
  [void][Microsoft.VisualBasic.Interaction]::AppActivate($drawioProc.Id)
  Start-Sleep -Milliseconds 400

  $pySave = @'
import pyautogui
import time

time.sleep(0.6)
pyautogui.hotkey("ctrl", "s")
time.sleep(1.5)
'@
  $pySave | py -3 -W ignore -
}

Start-Sleep -Milliseconds 600

$pyEval = @'
import base64
import html
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

path = r"C:\Users\User\Documents\drawio_sum_loop_flowchart.drawio"
expected_nodes = {
    "Start": "oval",
    "S=0": "rectangle",
    "k=1": "rectangle",
    "S=S+k": "rectangle",
    "k=k+3": "rectangle",
    "k<10": "diamond",
    "Output S": "parallelogram",
    "End": "oval",
}
expected_edges = {
    ("Start", "S=0"): "",
    ("S=0", "k=1"): "",
    ("k=1", "S=S+k"): "",
    ("S=S+k", "k=k+3"): "",
    ("k=k+3", "k<10"): "",
    ("k<10", "S=S+k"): "yes",
    ("k<10", "Output S"): "no",
    ("Output S", "End"): "",
}

def emit(result, message):
    print(f"EVAL_RESULT:{result} {message}")
    sys.exit(0)

def clean_text(raw):
    if raw is None:
        return ""
    text = html.unescape(str(raw))
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())

def parse_style(style):
    parsed = {}
    for chunk in str(style or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parsed[key] = value
        else:
            parsed[chunk] = True
    return parsed

def parse_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)

def normalize_color(value):
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text == "none":
        return "none"
    if not text.startswith("#"):
        text = "#" + text
    return text

def load_graph_model(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()

    if root.tag == "mxGraphModel":
        return root

    diagram = root.find("./diagram")
    if diagram is None:
        emit("FAIL", "diagram element not found")

    graph = diagram.find("./mxGraphModel")
    if graph is not None:
        return graph

    embedded = (diagram.text or "").strip()
    if embedded.startswith("<mxGraphModel"):
        return ET.fromstring(embedded)

    if embedded:
        try:
            xml_text = zlib.decompress(base64.b64decode(embedded), -15).decode("utf-8")
            xml_text = urllib.parse.unquote(xml_text)
            return ET.fromstring(xml_text)
        except Exception:
            pass

    emit("FAIL", "mxGraphModel not found")

def geometry(cell):
    geom = cell.find("mxGeometry")
    if geom is None:
        return None
    x = parse_float(geom.attrib.get("x", 0))
    y = parse_float(geom.attrib.get("y", 0))
    w = parse_float(geom.attrib.get("width", 0))
    h = parse_float(geom.attrib.get("height", 0))
    return x, y, w, h

def classify_shape(cell):
    style_text = str(cell.attrib.get("style", ""))
    style = parse_style(style_text)
    style_blob = style_text.lower()
    shape_name = str(style.get("shape", "")).lower()

    if "text" in style:
        return "text"
    if "ellipse" in style_blob or shape_name == "ellipse":
        return "oval"
    if "parallelogram" in style_blob or "parallelogram" in shape_name:
        return "parallelogram"
    if "rhombus" in style_blob or "rhombus" in shape_name:
        return "diamond"
    return "rectangle"

if not os.path.exists(path):
    emit("FAIL", "diagram file not found after save")

graph = load_graph_model(path)
cells = list(graph.iter("mxCell"))

edge_cells = {}
for cell in cells:
    if cell.attrib.get("edge") == "1":
        cell_id = str(cell.attrib.get("id", "")).strip()
        if cell_id:
            edge_cells[cell_id] = cell

shape_cells = []
edge_label_cells = []
for cell in cells:
    cell_id = str(cell.attrib.get("id", "")).strip()
    if cell.attrib.get("vertex") != "1" or cell_id in {"0", "1"}:
        continue
    parent_id = str(cell.attrib.get("parent", "")).strip()
    if parent_id in edge_cells:
        edge_label_cells.append(cell)
    else:
        shape_cells.append(cell)

if len(shape_cells) != len(expected_nodes):
    emit("FAIL", f"expected {len(expected_nodes)} flowchart nodes, found {len(shape_cells)}")

node_map = {}
node_id_to_text = {}
for cell in shape_cells:
    text = clean_text(cell.attrib.get("value"))
    if text not in expected_nodes:
        emit("FAIL", f"unexpected node text: {text or '<empty>'}")
    if text in node_map:
        emit("FAIL", f"duplicate node text: {text}")

    geom = geometry(cell)
    if geom is None:
        emit("FAIL", f"node has no geometry: {text}")
    _, _, width, height = geom
    if width < 30 or height < 30:
        emit("FAIL", f"node is too small: {text}")

    actual_shape = classify_shape(cell)
    expected_shape = expected_nodes[text]
    if actual_shape != expected_shape:
        emit("FAIL", f"node '{text}' should be {expected_shape}, found {actual_shape}")

    style = parse_style(cell.attrib.get("style", ""))
    fill = normalize_color(style.get("fillColor"))
    if text == "k<10" and fill != "#dae8fc":
        emit("FAIL", f"decision node should have fill #DAE8FC, found {fill or '<empty>'}")
    if text == "Output S" and fill != "#d5e8d4":
        emit("FAIL", f"output node should have fill #D5E8D4, found {fill or '<empty>'}")

    cell_id = str(cell.attrib.get("id", "")).strip()
    node_map[text] = cell
    node_id_to_text[cell_id] = text

edge_label_values = {}
for cell in edge_label_cells:
    parent_id = str(cell.attrib.get("parent", "")).strip()
    text = clean_text(cell.attrib.get("value"))
    if not text:
        continue
    edge_label_values.setdefault(parent_id, []).append(text)

if len(edge_cells) != len(expected_edges):
    emit("FAIL", f"expected {len(expected_edges)} flow lines, found {len(edge_cells)}")

observed_edges = {}
for edge_id, edge_cell in edge_cells.items():
    source_id = str(edge_cell.attrib.get("source", "")).strip()
    target_id = str(edge_cell.attrib.get("target", "")).strip()
    if source_id not in node_id_to_text or target_id not in node_id_to_text:
        emit("FAIL", "every flow line must connect two task nodes")

    source_text = node_id_to_text[source_id]
    target_text = node_id_to_text[target_id]
    key = (source_text, target_text)
    if key in observed_edges:
        emit("FAIL", f"duplicate flow line: {source_text} -> {target_text}")

    style = parse_style(edge_cell.attrib.get("style", ""))
    if str(style.get("endArrow", "")).lower() == "none":
        emit("FAIL", f"flow line {source_text} -> {target_text} is missing an arrow")
    if key == ("k<10", "S=S+k") and str(style.get("dashed", "")).strip().lower() not in {"1", "true"}:
        emit("FAIL", "Yes loop-back arrow should be dashed")

    label_candidates = []
    edge_value = clean_text(edge_cell.attrib.get("value"))
    if edge_value:
        label_candidates.append(edge_value)
    label_candidates.extend(edge_label_values.get(edge_id, []))
    label_candidates = [item for item in label_candidates if item]
    unique_labels = list(dict.fromkeys(label_candidates))
    if len(unique_labels) > 1:
        emit("FAIL", f"flow line {source_text} -> {target_text} has conflicting labels")

    observed_edges[key] = unique_labels[0].strip().lower() if unique_labels else ""

for key, expected_label in expected_edges.items():
    if key not in observed_edges:
        emit("FAIL", f"missing flow line: {key[0]} -> {key[1]}")
    actual_label = observed_edges[key]
    if actual_label != expected_label:
        wanted = expected_label if expected_label else "<empty>"
        found = actual_label if actual_label else "<empty>"
        emit("FAIL", f"flow line {key[0]} -> {key[1]} should have label {wanted}, found {found}")

emit("PASS", "flowchart nodes, shapes, flow lines, and Yes/No branches all match")
'@

$pyEval | py -3 -
