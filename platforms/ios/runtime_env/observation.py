"""
Observation model and UI perception logic.
"""

import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Observation:
    timestamp: str
    width: int
    height: int
    viewport_rect: Dict[str, int]
    device_info: Dict[str, Any]
    ui_nodes: List[Dict[str, Any]]
    foreground_bundle_id: str
    is_keyboard_shown: bool

    def to_json(self, *, compact: bool = True) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":") if compact else None,
            indent=None if compact else 2,
        )


def summarize_ui_tree(ui_xml: str, width: int, height: int, limit: int) -> List[Dict[str, Any]]:
    """Filter iOS UI XML and keep AI-relevant nodes."""
    max_items = int(limit)
    if not ui_xml or not ui_xml.strip():
        return []

    try:
        root = ET.fromstring(ui_xml)
    except Exception:
        return []

    w = float(width)
    h = float(height)
    if w <= 0 or h <= 0:
        return []

    viewport = (-w * 0.1, -h * 0.15, w * 1.1, h * 1.15)

    interactive_types = {
        "XCUIElementTypeButton", "XCUIElementTypeSwitch", "XCUIElementTypeTextField",
        "XCUIElementTypeSecureTextField", "XCUIElementTypeTextView", "XCUIElementTypeSearchField",
        "XCUIElementTypeSlider", "XCUIElementTypeStepper", "XCUIElementTypePicker",
        "XCUIElementTypeDatePicker", "XCUIElementTypePickerWheel", "XCUIElementTypeSegmentedControl",
        "XCUIElementTypeLink", "XCUIElementTypePageIndicator", "XCUIElementTypeCheckBox",
        "XCUIElementTypeRadioButton", "XCUIElementTypeToggle", "XCUIElementTypeComboBox",
        "XCUIElementTypeMenuItem", "XCUIElementTypeKey",
    }

    semantic_types = {
        "XCUIElementTypeNavigationBar", "XCUIElementTypeTabBar", "XCUIElementTypeToolbar",
        "XCUIElementTypeCell", "XCUIElementTypeTable", "XCUIElementTypeCollectionView",
        "XCUIElementTypeScrollView", "XCUIElementTypeWebView", "XCUIElementTypeAlert",
        "XCUIElementTypeSheet", "XCUIElementTypeMenu", "XCUIElementTypeHeader",
    }

    layout_types = {"XCUIElementTypeOther", "XCUIElementTypeApplication", "XCUIElementTypeWindow"}
    decorative_types = {"XCUIElementTypeImage", "XCUIElementTypeIcon"}

    results: List[Dict[str, Any]] = []
    node_idx = 0
    stack = [root]

    while stack and len(results) < max_items:
        node = stack.pop()
        for child in reversed(list(node)):
            stack.append(child)

        node_type = (node.attrib.get("type") or node.tag or "").strip()
        visible = node.attrib.get("visible", "").lower()
        if visible == "false":
            continue

        rect = None
        x = node.attrib.get("x")
        y = node.attrib.get("y")
        node_w = node.attrib.get("width")
        node_h = node.attrib.get("height")
        if all(v is not None for v in [x, y, node_w, node_h]):
            try:
                rect = {"x": float(x), "y": float(y), "w": float(node_w), "h": float(node_h)}
            except ValueError:
                pass

        if rect and (rect["w"] <= 0 or rect["h"] <= 0):
            continue

        if rect:
            x1 = rect["x"]
            y1 = rect["y"]
            x2 = rect["x"] + rect["w"]
            y2 = rect["y"] + rect["h"]
            if x2 <= viewport[0] or x1 >= viewport[2] or y2 <= viewport[1] or y1 >= viewport[3]:
                continue

        text = ""
        for key in ("label", "name", "value"):
            val = (node.attrib.get(key) or "").strip()
            if val:
                text = val
                break

        accessible = node.attrib.get("accessible", "").lower() == "true"
        enabled = node.attrib.get("enabled", "").lower() != "false"

        should_keep = (
            node_type in interactive_types or
            node_type in semantic_types or
            accessible or
            text or
            node_type == "XCUIElementTypeStaticText"
        )

        if node_type in decorative_types:
            name = node.attrib.get("name", "")
            if name and name not in {"chevron.forward", "chevron.backward", "checkmark"}:
                should_keep = True

        if node_type in layout_types:
            if node.attrib.get("name") or node.attrib.get("bundleId"):
                should_keep = True
            else:
                should_keep = False

        if not should_keep:
            continue

        selector = (node.attrib.get("name") or node.attrib.get("label") or "").strip()
        tap_point = None
        tap_norm = None
        if rect:
            tx = int(rect["x"] + rect["w"] / 2)
            ty = int(rect["y"] + rect["h"] / 2)
            tap_point = [tx, ty]
            tap_norm = [round(tx / w, 4), round(ty / h, 4)]

        short_type = node_type.replace("XCUIElementType", "") if node_type.startswith("XCUIElementType") else node_type

        item = {"id": f"n{node_idx}", "type": short_type}
        if text:
            item["text"] = text
        if selector:
            item["selector"] = selector
        if rect:
            item["rect"] = rect
        if tap_point:
            item["tap"] = tap_point
        if tap_norm:
            item["tap_norm"] = tap_norm
        if enabled is not None:
            item["enabled"] = enabled
        if accessible:
            item["accessible"] = accessible

        results.append(item)
        node_idx += 1

    return results


class iOSObservationEngine:
    """High-level observation/perception layer."""

    def __init__(self, runtime):
        self.runtime = runtime

    def summarize_ui_tree(self, ui_xml: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        size = self.runtime.get_window_size()
        max_items = int(self.runtime.ui_summary_limit if limit is None else limit)
        return summarize_ui_tree(ui_xml, width=size["width"], height=size["height"], limit=max_items)

    def observe(self, include_ui_tree: bool = True) -> Observation:
        ts = self.runtime.timestamp()
        size = self.runtime.get_window_size()
        viewport_rect = self.runtime.get_viewport_rect()
        device_info = self.runtime.get_device_info()
        info = self.runtime.active_app_info()
        foreground_bundle_id = info.get("bundleId", "")
        is_keyboard_shown = self.runtime.is_keyboard_shown()

        ui_nodes = []
        if include_ui_tree:
            page_source = self.runtime.get_page_source()
            ui_nodes = self.summarize_ui_tree(page_source)

        return Observation(
            timestamp=ts,
            width=size["width"],
            height=size["height"],
            viewport_rect=viewport_rect,
            device_info=device_info,
            ui_nodes=ui_nodes,
            foreground_bundle_id=foreground_bundle_id,
            is_keyboard_shown=is_keyboard_shown,
        )
