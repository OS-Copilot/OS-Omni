"""Initializer utilities for Marble desktop tasks on Linux."""

from __future__ import annotations

import json
import shlex
import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class MarbleInitializer(BaseInitializer):
    """Reset local Marble state and launch a clean Marble session."""

    DEFAULT_APP_COMMAND = "marble"
    DEFAULT_FINAL_WAIT_MS = 5000

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        preseed_map_theme = str(params.get("preseed_map_theme") or "").strip()
        preseed_folders = params.get("preseed_folders")
        preseed_bookmarks = params.get("preseed_bookmarks")
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)

        try:
            self._run(controller, f"command -v {shlex.quote(app_command)} >/dev/null 2>&1", timeout=10)
            self._stop_app(controller)
            self._reset_profile(controller)
            if preseed_map_theme or preseed_folders or preseed_bookmarks:
                self._preseed_profile(
                    controller,
                    map_theme=preseed_map_theme,
                    folders=preseed_folders,
                    bookmarks=preseed_bookmarks,
                )
            self._launch_app(controller, app_command=app_command)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(status=InitStatus.ERROR, message=f"Failed to prepare Marble session: {exc}")

        return InitResult(status=InitStatus.PASS, message="Prepared Marble session")

    @staticmethod
    def _run(controller: Any, script: str, *, timeout: int) -> Mapping[str, Any]:
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        if returncode != 0:
            output = str(result.get("output", "")).strip()
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        return result

    def _stop_app(self, controller: Any) -> None:
        self._run(
            controller,
            "\n".join(
                [
                    "pkill -TERM -f '(^|/)marble($| )' || true",
                    "sleep 1",
                    "pkill -KILL -f '(^|/)marble($| )' || true",
                    "sleep 1",
                ]
            ),
            timeout=15,
        )

    def _reset_profile(self, controller: Any) -> None:
        payload = json.dumps(
            {
                "paths": [
                    "/home/user/.config/marblerc",
                    "/home/user/.config/kde.org/marble.conf",
                    "/home/user/.local/share/marble",
                ]
            },
            ensure_ascii=False,
        )
        script = f"""python3 - <<'PY'
import json
import pathlib
import shutil

payload = json.loads({json.dumps(payload, ensure_ascii=False)})
for raw_path in payload["paths"]:
    path = pathlib.Path(raw_path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()

pathlib.Path("/home/user/.config/kde.org").mkdir(parents=True, exist_ok=True)
pathlib.Path("/home/user/.local/share").mkdir(parents=True, exist_ok=True)
print(json.dumps({{"status": "ok"}}, ensure_ascii=False))
PY"""
        self._run(controller, script, timeout=25)

    def _preseed_profile(
        self,
        controller: Any,
        *,
        map_theme: str,
        folders: Any,
        bookmarks: Any,
    ) -> None:
        normalized_folders: list[list[str]] = []
        if isinstance(folders, list):
            for item in folders:
                if isinstance(item, str) and item.strip():
                    normalized_folders.append([item.strip()])
                elif isinstance(item, list):
                    parts = [str(part).strip() for part in item if str(part).strip()]
                    if parts:
                        normalized_folders.append(parts)

        normalized_bookmarks: list[dict[str, Any]] = []
        if isinstance(bookmarks, list):
            for item in bookmarks:
                if not isinstance(item, Mapping):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                folder = item.get("folder")
                if isinstance(folder, str) and folder.strip():
                    folder_path = [folder.strip()]
                elif isinstance(folder, list):
                    folder_path = [str(part).strip() for part in folder if str(part).strip()]
                else:
                    folder_path = ["Default"]
                normalized_bookmarks.append({"name": name, "folder_path": folder_path})

        payload = json.dumps(
            {
                "map_theme": map_theme,
                "folders": normalized_folders,
                "bookmarks": normalized_bookmarks,
            },
            ensure_ascii=False,
        )
        script = f"""python3 - <<'PY'
import configparser
import json
import pathlib
import xml.etree.ElementTree as ET

payload = json.loads({json.dumps(payload, ensure_ascii=False)})
config_path = pathlib.Path("/home/user/.config/marblerc")
bookmarks_path = pathlib.Path("/home/user/.local/share/marble/bookmarks/bookmarks.kml")
config_path.parent.mkdir(parents=True, exist_ok=True)
bookmarks_path.parent.mkdir(parents=True, exist_ok=True)

if payload["map_theme"]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser["MarbleWidget"] = {{"mapTheme": payload["map_theme"]}}
    with config_path.open("w", encoding="utf-8") as fh:
        parser.write(fh)

ns = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", ns)
kml = ET.Element(f"{{{ns}}}kml")
document = ET.SubElement(kml, f"{{{ns}}}Document")
default_folder = ET.SubElement(document, f"{{{ns}}}Folder")
ET.SubElement(default_folder, f"{{{ns}}}name").text = "Default"
folder_nodes = {{("Default",): default_folder}}

for path in payload["folders"]:
    parent = document
    built = []
    for part in path:
        built.append(part)
        key = tuple(built)
        if key in folder_nodes:
            parent = folder_nodes[key]
            continue
        node = ET.SubElement(parent, f"{{{ns}}}Folder")
        ET.SubElement(node, f"{{{ns}}}name").text = part
        folder_nodes[key] = node
        parent = node

for item in payload["bookmarks"]:
    path = tuple(item["folder_path"])
    parent = folder_nodes.get(path)
    if parent is None:
        parent = document
        built = []
        for part in path:
            built.append(part)
            key = tuple(built)
            node = folder_nodes.get(key)
            if node is None:
                node = ET.SubElement(parent, f"{{{ns}}}Folder")
                ET.SubElement(node, f"{{{ns}}}name").text = part
                folder_nodes[key] = node
            parent = node
    placemark = ET.SubElement(parent, f"{{{ns}}}Placemark")
    ET.SubElement(placemark, f"{{{ns}}}name").text = item["name"]

ET.ElementTree(kml).write(bookmarks_path, encoding="utf-8", xml_declaration=True)
print(json.dumps({{"status": "ok"}}, ensure_ascii=False))
PY"""
        self._run(controller, script, timeout=30)

    def _launch_app(self, controller: Any, *, app_command: str) -> None:
        launch_script = "\n".join(
            [
                "export DISPLAY=${DISPLAY:-:0}",
                "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
                'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
                'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
                f"setsid -f bash -lc {shlex.quote(app_command)} >/dev/null 2>&1",
            ]
        )
        self._run(controller, launch_script, timeout=15)
