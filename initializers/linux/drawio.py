"""Initializer utilities for draw.io desktop tasks on Linux."""

from __future__ import annotations

import json
import shlex
import time
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


def _build_diagram_xml(page_name: str, cells: list[dict[str, Any]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<mxfile host="Electron" modified="2026-04-18T00:00:00.000Z" agent="HelloWorld" version="29.6.6" type="device">',
        f'  <diagram id="page-1" name="{page_name}">',
        '    <mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1600" pageHeight="900" math="0" shadow="0">',
        "      <root>",
        '        <mxCell id="0"/>',
        '        <mxCell id="1" parent="0"/>',
    ]
    for cell in cells:
        geometry = cell["geometry"]
        lines.extend(
            [
                (
                    f'        <mxCell id="{cell["id"]}" value="{cell["value"]}" style="{cell["style"]}" '
                    f'vertex="1" parent="1">'
                ),
                (
                    f'          <mxGeometry x="{geometry["x"]}" y="{geometry["y"]}" '
                    f'width="{geometry["width"]}" height="{geometry["height"]}" as="geometry"/>'
                ),
                "        </mxCell>",
            ]
        )
    lines.extend(
        [
            "      </root>",
            "    </mxGraphModel>",
            "  </diagram>",
            "</mxfile>",
            "",
        ]
    )
    return "\n".join(lines)


DRAWIO_TEMPLATES: dict[str, str] = {
    "launch_badge": _build_diagram_xml(
        "Launch Badge",
        [
            {
                "id": "title_box",
                "value": "Launch Badge",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=18;fontStyle=1;",
                "geometry": {"x": 80, "y": 40, "width": 260, "height": 70},
            },
            {
                "id": "status_box",
                "value": "Draft Label",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=20;fontStyle=1;",
                "geometry": {"x": 80, "y": 170, "width": 260, "height": 110},
            },
            {
                "id": "footer_box",
                "value": "Review before ship",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=14;",
                "geometry": {"x": 80, "y": 330, "width": 260, "height": 90},
            },
        ],
    ),
    "release_flow_board": _build_diagram_xml(
        "Release Flow Board",
        [
            {
                "id": "header_box",
                "value": "Release Flow Board",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;fontSize=20;fontStyle=1;",
                "geometry": {"x": 60, "y": 40, "width": 300, "height": 70},
            },
            {
                "id": "queue_box",
                "value": "Intake Queue",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=16;",
                "geometry": {"x": 60, "y": 160, "width": 220, "height": 90},
            },
            {
                "id": "draft_box",
                "value": "Draft Plan",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=16;",
                "geometry": {"x": 340, "y": 160, "width": 220, "height": 90},
            },
            {
                "id": "review_box",
                "value": "Review Notes",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=16;",
                "geometry": {"x": 620, "y": 160, "width": 220, "height": 90},
            },
            {
                "id": "approval_box",
                "value": "Team Hold",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=16;",
                "geometry": {"x": 60, "y": 320, "width": 220, "height": 90},
            },
            {
                "id": "ship_box",
                "value": "Ship Window",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;fontSize=16;",
                "geometry": {"x": 340, "y": 320, "width": 220, "height": 90},
            },
            {
                "id": "follow_box",
                "value": "Retro Notes",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=16;",
                "geometry": {"x": 620, "y": 320, "width": 220, "height": 90},
            },
        ],
    ),
    "incident_sync_map": _build_diagram_xml(
        "Incident Sync Map",
        [
            {
                "id": "header_box",
                "value": "Incident Sync Map",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;fontSize=20;fontStyle=1;",
                "geometry": {"x": 50, "y": 30, "width": 320, "height": 70},
            },
            {
                "id": "pager_box",
                "value": "Pager Alert",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=16;",
                "geometry": {"x": 60, "y": 150, "width": 210, "height": 90},
            },
            {
                "id": "triage_box",
                "value": "Service Triage",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=16;",
                "geometry": {"x": 320, "y": 150, "width": 210, "height": 90},
            },
            {
                "id": "status_box",
                "value": "Status Draft",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=16;",
                "geometry": {"x": 580, "y": 150, "width": 210, "height": 90},
            },
            {
                "id": "mitigation_box",
                "value": "Hotfix Queue",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=16;",
                "geometry": {"x": 60, "y": 320, "width": 210, "height": 90},
            },
            {
                "id": "verification_box",
                "value": "QA Sweep",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;fontSize=16;",
                "geometry": {"x": 320, "y": 320, "width": 210, "height": 90},
            },
            {
                "id": "ops_box",
                "value": "Ops Hand-off",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=16;",
                "geometry": {"x": 580, "y": 320, "width": 210, "height": 90},
            },
            {
                "id": "closing_box",
                "value": "Postmortem",
                "style": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;fontSize=16;",
                "geometry": {"x": 320, "y": 490, "width": 210, "height": 90},
            },
        ],
    ),
}


class DrawIOInitializer(BaseInitializer):
    """Prepare a deterministic draw.io diagram and launch it in a fresh window."""

    DEFAULT_APP_COMMAND = "drawio"
    DEFAULT_WORKSPACE_ROOT = "/tmp/helloworld_drawio_workspace"
    DEFAULT_FINAL_WAIT_MS = 4500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        workspace_name = str(params.get("workspace_name") or "bench").strip() or "bench"
        workspace_root = str(params.get("workspace_root") or self.DEFAULT_WORKSPACE_ROOT).strip()
        diagram_name = str(params.get("diagram_name") or "diagram.drawio").strip() or "diagram.drawio"
        diagram_template = str(params.get("diagram_template") or "").strip()
        diagram_xml = params.get("diagram_xml")
        cell_overrides = params.get("cell_overrides")
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        workspace_path = f"{workspace_root.rstrip('/')}/{workspace_name}"
        diagram_path = f"{workspace_path}/{diagram_name}"

        try:
            self._run(controller, f"command -v {shlex.quote(app_command)} >/dev/null 2>&1", timeout=10)
            self._stop_app(controller)
            resolved_xml = self._resolve_diagram_xml(
                diagram_template=diagram_template,
                diagram_xml=diagram_xml,
                cell_overrides=cell_overrides,
            )
            self._prepare_workspace(
                controller,
                workspace_path=workspace_path,
                diagram_path=diagram_path,
                diagram_xml=resolved_xml,
            )
            self._launch_app(controller, app_command=app_command, diagram_path=diagram_path)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare draw.io workspace: {exc}",
                metadata={"workspace_path": workspace_path, "diagram_path": diagram_path},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared draw.io workspace",
            metadata={"workspace_path": workspace_path, "diagram_path": diagram_path},
        )

    @staticmethod
    def _resolve_diagram_xml(*, diagram_template: str, diagram_xml: Any, cell_overrides: Any) -> str:
        resolved_xml = ""
        if isinstance(diagram_xml, str) and diagram_xml.strip():
            resolved_xml = diagram_xml
        elif diagram_template:
            resolved = DRAWIO_TEMPLATES.get(diagram_template)
            if resolved is None:
                raise RuntimeError(f"unknown draw.io diagram template: {diagram_template}")
            resolved_xml = resolved
        else:
            raise RuntimeError("initializer.params.diagram_template or initializer.params.diagram_xml is required")

        if isinstance(cell_overrides, list) and cell_overrides:
            resolved_xml = DrawIOInitializer._apply_cell_overrides(resolved_xml, cell_overrides)
        return resolved_xml

    @staticmethod
    def _apply_cell_overrides(diagram_xml: str, cell_overrides: list[Any]) -> str:
        tree = ET.ElementTree(ET.fromstring(diagram_xml))
        root = tree.getroot()
        by_id = {
            str(node.attrib.get("id") or ""): node
            for node in root.iter("mxCell")
            if str(node.attrib.get("id") or "").strip()
        }
        for item in cell_overrides:
            if not isinstance(item, Mapping):
                continue
            cell_id = str(item.get("id") or "").strip()
            if not cell_id:
                continue
            node = by_id.get(cell_id)
            if node is None:
                raise RuntimeError(f"unknown draw.io cell override id: {cell_id}")
            if "equals" in item:
                node.set("value", str(item.get("equals") or ""))
            elif "contains" in item:
                node.set("value", str(item.get("contains") or ""))
        return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

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
                    "pkill -TERM -f '/usr/bin/drawio|/opt/draw.io/drawio|drawio' || true",
                    "sleep 1",
                    "pkill -KILL -f '/usr/bin/drawio|/opt/draw.io/drawio|drawio' || true",
                    "sleep 1",
                ]
            ),
            timeout=20,
        )

    def _prepare_workspace(
        self,
        controller: Any,
        *,
        workspace_path: str,
        diagram_path: str,
        diagram_xml: str,
    ) -> None:
        payload = json.dumps(
            {
                "workspace_path": workspace_path,
                "diagram_path": diagram_path,
                "diagram_xml": diagram_xml,
            },
            ensure_ascii=False,
        )
        script = f"""python3 - <<'PY'
import json
import pathlib
import shutil

payload = json.loads({json.dumps(payload, ensure_ascii=False)})
workspace = pathlib.Path(payload["workspace_path"])
diagram_path = pathlib.Path(payload["diagram_path"])

if workspace.exists():
    shutil.rmtree(workspace)
workspace.mkdir(parents=True, exist_ok=True)
diagram_path.parent.mkdir(parents=True, exist_ok=True)
diagram_path.write_text(payload["diagram_xml"], encoding="utf-8")

print(json.dumps({{"status": "ok", "diagram_path": str(diagram_path)}}, ensure_ascii=False))
PY"""
        self._run(controller, script, timeout=30)

    def _launch_app(self, controller: Any, *, app_command: str, diagram_path: str) -> None:
        command = " ".join([shlex.quote(app_command), shlex.quote(diagram_path)])
        launch_script = "\n".join(
            [
                "export DISPLAY=${DISPLAY:-:0}",
                "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
                'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
                'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
                f"setsid -f bash -lc {shlex.quote(command)} >/dev/null 2>&1",
            ]
        )
        self._run(controller, launch_script, timeout=15)
