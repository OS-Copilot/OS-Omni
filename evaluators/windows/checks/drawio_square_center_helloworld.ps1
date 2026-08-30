$ErrorActionPreference = "Stop"

$documentPath = "C:\Users\User\Documents\drawio_square_center_helloworld.drawio"
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

path = r"C:\Users\User\Documents\drawio_square_center_helloworld.drawio"
target_text = "Helloworld"

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

if not os.path.exists(path):
    emit("FAIL", "diagram file not found after save")

graph = load_graph_model(path)
cells = list(graph.iter("mxCell"))

user_vertices = []
edge_count = 0
for cell in cells:
    cell_id = str(cell.attrib.get("id", ""))
    if cell.attrib.get("edge") == "1":
        edge_count += 1
    if cell.attrib.get("vertex") == "1" and cell_id not in {"0", "1"}:
        geom = geometry(cell)
        if geom is not None:
            user_vertices.append((cell, geom))

if edge_count != 0:
    emit("FAIL", f"expected no connectors, found {edge_count}")

if len(user_vertices) not in {1, 2}:
    emit("FAIL", f"expected 1 or 2 drawable objects, found {len(user_vertices)}")

square_candidates = []
for cell, geom in user_vertices:
    x, y, w, h = geom
    if w < 40 or h < 40:
        continue
    style = parse_style(cell.attrib.get("style", ""))
    style_blob = str(cell.attrib.get("style", "")).lower()
    shape_name = str(style.get("shape", "")).lower()
    if "text" in style:
        continue
    if str(style.get("rounded", "0")).lower() in {"1", "true"}:
        continue
    if any(
        token in shape_name or token in style_blob
        for token in [
            "ellipse",
            "circle",
            "triangle",
            "rhombus",
            "hexagon",
            "cloud",
            "cylinder",
            "parallelogram",
            "actor",
            "document",
            "trapezoid",
            "arrow",
            "callout",
            "note",
            "step",
        ]
    ):
        continue
    ratio = abs(w - h) / max(w, h)
    if ratio <= 0.18:
        square_candidates.append((cell, geom, style))

if len(square_candidates) != 1:
    emit("FAIL", f"expected exactly one square, found {len(square_candidates)}")

square_cell, square_geom, square_style = square_candidates[0]
square_x, square_y, square_w, square_h = square_geom
square_center_x = square_x + square_w / 2.0
square_center_y = square_y + square_h / 2.0

square_text = clean_text(square_cell.attrib.get("value"))
horizontal_align = str(square_style.get("align", "center")).lower()
vertical_align = str(square_style.get("verticalAlign", "middle")).lower()

if (
    square_text == target_text
    and horizontal_align == "center"
    and vertical_align in {"middle", "center"}
):
    emit(
        "PASS",
        f"one square found with centered text on the shape center=({square_center_x:.1f},{square_center_y:.1f})",
    )

label_candidates = []
for cell, geom in user_vertices:
    if cell is square_cell:
        continue
    label_text = clean_text(cell.attrib.get("value"))
    if label_text == target_text:
        label_candidates.append((cell, geom, parse_style(cell.attrib.get("style", ""))))

if len(label_candidates) != 1:
    emit("FAIL", "did not find exactly one separate Helloworld text object")

_, label_geom, label_style = label_candidates[0]
label_x, label_y, label_w, label_h = label_geom
label_center_x = label_x + label_w / 2.0
label_center_y = label_y + label_h / 2.0

tolerance_x = max(12.0, square_w * 0.12)
tolerance_y = max(12.0, square_h * 0.12)
inside_square = (
    square_x <= label_center_x <= square_x + square_w
    and square_y <= label_center_y <= square_y + square_h
)
close_to_center = (
    abs(label_center_x - square_center_x) <= tolerance_x
    and abs(label_center_y - square_center_y) <= tolerance_y
)
label_horizontal_align = str(label_style.get("align", "center")).lower()
label_vertical_align = str(label_style.get("verticalAlign", "middle")).lower()

if (
    inside_square
    and close_to_center
    and label_horizontal_align == "center"
    and label_vertical_align in {"middle", "center"}
):
    emit(
        "PASS",
        "one square found with a separate centered Helloworld label",
    )

emit(
    "FAIL",
    (
        "Helloworld is not centered inside the square "
        f"(label_center=({label_center_x:.1f},{label_center_y:.1f}) "
        f"square_center=({square_center_x:.1f},{square_center_y:.1f}) "
        f"tolerance=({tolerance_x:.1f},{tolerance_y:.1f}))"
    ),
)
'@

$pyEval | py -3 -
