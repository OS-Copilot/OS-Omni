$ErrorActionPreference = "Stop"

$documentPath = "C:\Users\User\Documents\drawio_ellipse_vertical_divider_styled.drawio"
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

path = r"C:\Users\User\Documents\drawio_ellipse_vertical_divider_styled.drawio"

def emit(result, message):
    print(f"EVAL_RESULT:{result} {message}")
    sys.exit(0)

def clean_text(raw):
    if raw is None:
        return ""
    text = html.unescape(str(raw))
    text = re.sub(r"<br\\s*/?>", " ", text, flags=re.IGNORECASE)
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
    if re.fullmatch(r"#[0-9a-f]{6}", text):
        return text
    return text

def approx(value, expected, tolerance):
    return abs(float(value) - float(expected)) <= float(tolerance)

def normalized_rotation(value):
    angle = parse_float(value, 0.0)
    angle = angle % 360.0
    if angle < 0:
        angle += 360.0
    return angle

def opacity_matches(style):
    overall = style.get("opacity")
    if overall not in (None, "") and approx(parse_float(overall, 0), 65.0, 0.6):
        return True

    fill = style.get("fillOpacity")
    stroke = style.get("strokeOpacity")
    return (
        fill not in (None, "")
        and stroke not in (None, "")
        and approx(parse_float(fill, 0), 65.0, 0.6)
        and approx(parse_float(stroke, 0), 65.0, 0.6)
    )

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

edge_cells = {}
for cell in cells:
    if cell.attrib.get("edge") == "1":
        cell_id = str(cell.attrib.get("id", "")).strip()
        if cell_id:
            edge_cells[cell_id] = cell

user_vertices = []
for cell in cells:
    cell_id = str(cell.attrib.get("id", "")).strip()
    if cell.attrib.get("vertex") != "1" or cell_id in {"0", "1"}:
        continue
    parent_id = str(cell.attrib.get("parent", "")).strip()
    if parent_id in edge_cells:
        emit("FAIL", "no edge labels or extra text objects are allowed")
    user_vertices.append(cell)

if edge_cells:
    emit("FAIL", f"expected 0 connectors, found {len(edge_cells)}")

if len(user_vertices) != 1:
    emit("FAIL", f"expected exactly one shape, found {len(user_vertices)}")

cell = user_vertices[0]
text = clean_text(cell.attrib.get("value"))
if text:
    emit("FAIL", "the diagram should not contain text")

geom = geometry(cell)
if geom is None:
    emit("FAIL", "shape geometry is missing")

_, _, width, height = geom
if not approx(width, 300.0, 2.0) or not approx(height, 200.0, 2.0):
    emit("FAIL", f"shape size should be 300 by 200 pt, found {width:.1f} by {height:.1f}")

style = parse_style(cell.attrib.get("style", ""))
if str(style.get("shape", "")).strip() != "lineEllipse":
    emit("FAIL", f"shape should be lineEllipse, found {style.get('shape', '')}")

if str(style.get("line", "")).strip().lower() != "vertical":
    emit("FAIL", "shape must be the vertical-divider ellipse variant")

if str(style.get("perimeter", "")).strip() != "ellipsePerimeter":
    emit("FAIL", "ellipse perimeter is missing or incorrect")

if str(style.get("backgroundOutline", "")).strip() not in {"1", "true"}:
    emit("FAIL", "backgroundOutline should be enabled for the divider ellipse")

rotation = normalized_rotation(style.get("rotation", 0))
if not (approx(rotation, 90.0, 0.6) or approx(rotation, 270.0, 0.6)):
    emit("FAIL", f"shape should be rotated by a quarter turn, found rotation={rotation:.1f}")

fill_color = normalize_color(style.get("fillColor"))
if fill_color != "#fa3232":
    emit("FAIL", f"fill color should be #FA3232, found {fill_color or '<empty>'}")

stroke_color = normalize_color(style.get("strokeColor"))
if stroke_color != "#00ffff":
    emit("FAIL", f"line color should be #00FFFF, found {stroke_color or '<empty>'}")

stroke_width = parse_float(style.get("strokeWidth", 1), 1)
if not approx(stroke_width, 5.0, 0.2):
    emit("FAIL", f"line width should be 5 pt, found {stroke_width:.2f}")

if not opacity_matches(style):
    emit("FAIL", "overall opacity should be 65%")

if str(style.get("shadow", "")).strip().lower() not in {"1", "true"}:
    emit("FAIL", "shadow should be enabled")

gradient = str(style.get("gradientDirection", "")).strip().lower()
if "gradientColor" not in style:
    emit("FAIL", "vertical fill gradient is missing")
if gradient not in {"south", "north", "vertical"}:
    emit("FAIL", f"fill gradient should be vertical, found {gradient or '<empty>'}")

emit("PASS", "one correctly styled rotated vertical-divider ellipse found")
'@

$pyEval | py -3 -
