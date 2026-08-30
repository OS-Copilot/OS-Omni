"""Bookmark-backed evaluator for Marble desktop tasks on Linux."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class MarbleBookmarkEvaluator(BaseEvaluator):
    """Validate Marble tasks through Marble config and bookmarks KML artifacts."""

    DEFAULT_TIMEOUT = 30
    DEFAULT_BOOKMARKS_PATH = "/home/user/.local/share/marble/bookmarks/bookmarks.kml"
    DEFAULT_CONFIG_PATH = "/home/user/.config/marblerc"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)
        bookmarks_path = str(params.get("bookmarks_path") or self.DEFAULT_BOOKMARKS_PATH)
        config_path = str(params.get("config_path") or self.DEFAULT_CONFIG_PATH)
        required_folders = params.get("required_folders") or []
        required_bookmarks = params.get("required_bookmarks") or []
        required_map_theme = params.get("map_theme")

        script = f"""python3 - <<'PY'
import configparser
import json
import pathlib
import xml.etree.ElementTree as ET

bookmarks_path = pathlib.Path({json.dumps(bookmarks_path)})
config_path = pathlib.Path({json.dumps(config_path)})

payload = {{
    "bookmarks_exists": bookmarks_path.exists(),
    "config_exists": config_path.exists(),
    "folders": [],
    "placemarks": [],
    "map_theme": None,
}}

if config_path.exists():
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(config_path, encoding="utf-8")
    if parser.has_section("MarbleWidget") and parser.has_option("MarbleWidget", "mapTheme"):
        payload["map_theme"] = parser.get("MarbleWidget", "mapTheme")

def local_name(tag: str) -> str:
    return tag.rsplit("}}", 1)[-1]

def child_text(node, wanted: str):
    for child in list(node):
        if local_name(child.tag) == wanted:
            return (child.text or "").strip()
    return ""

def walk(node, path):
    kind = local_name(node.tag)
    if kind == "Folder":
        folder_name = child_text(node, "name")
        path = path + [folder_name] if folder_name else path
        payload["folders"].append(path)
    elif kind == "Placemark":
        payload["placemarks"].append({{"name": child_text(node, "name"), "folder_path": path}})
        return

    for child in list(node):
        child_kind = local_name(child.tag)
        if child_kind in {{"Folder", "Placemark", "Document"}}:
            walk(child, path)

if bookmarks_path.exists():
    root = ET.parse(bookmarks_path).getroot()
    walk(root, [])

print(json.dumps(payload, ensure_ascii=False))
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
                message=f"Marble evaluator returned invalid JSON: {exc}: {output}",
            )

        folders = [list(item) for item in payload.get("folders") or [] if isinstance(item, list)]
        placemarks = [dict(item) for item in payload.get("placemarks") or [] if isinstance(item, Mapping)]

        try:
            if required_map_theme is not None:
                actual_theme = str(payload.get("map_theme") or "")
                assert actual_theme == str(required_map_theme), (
                    f"expected Marble map theme {required_map_theme!r}, got {actual_theme!r}"
                )

            for expected_folder in required_folders:
                if isinstance(expected_folder, str):
                    expected_path = [expected_folder]
                elif isinstance(expected_folder, list):
                    expected_path = [str(part) for part in expected_folder]
                else:
                    raise AssertionError(f"invalid required_folders entry: {expected_folder!r}")
                assert expected_path in folders, f"expected folder path {expected_path!r} in bookmarks"

            for expected_bookmark in required_bookmarks:
                if not isinstance(expected_bookmark, Mapping):
                    raise AssertionError(f"invalid required_bookmarks entry: {expected_bookmark!r}")
                wanted_name = str(expected_bookmark.get("name") or "").strip()
                assert wanted_name, "required bookmark name cannot be empty"
                wanted_folder = expected_bookmark.get("folder")
                matches = [item for item in placemarks if str(item.get("name") or "") == wanted_name]
                assert matches, f"expected bookmark {wanted_name!r} in Marble bookmarks"
                if wanted_folder is not None:
                    if isinstance(wanted_folder, str):
                        wanted_path = [wanted_folder]
                    elif isinstance(wanted_folder, list):
                        wanted_path = [str(part) for part in wanted_folder]
                    else:
                        raise AssertionError(f"invalid folder constraint for bookmark {wanted_name!r}")
                    matches = [item for item in matches if list(item.get("folder_path") or []) == wanted_path]
                    assert matches, f"expected bookmark {wanted_name!r} under folder path {wanted_path!r}"
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=payload)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Marble evaluator failed: {exc}", metadata=payload)

        return EvalResult(status=EvalStatus.PASS, message="Marble bookmark evaluation passed", metadata=payload)
