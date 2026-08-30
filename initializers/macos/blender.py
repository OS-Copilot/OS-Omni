"""Initializer utilities for Blender desktop tasks on macOS."""

from __future__ import annotations

import json
import shlex
import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


SCENE_SPECS: dict[str, dict[str, Any]] = {
    "product_stage": {
        "render": {
            "resolution_x": 1920,
            "resolution_y": 1080,
            "fps": 24,
            "frame_start": 1,
            "frame_end": 120,
            "engine": "BLENDER_WORKBENCH",
            "film_transparent": False,
            "file_format": "PNG",
            "color_mode": "RGBA",
        },
        "objects": [
            {
                "type": "CAMERA",
                "name": "Camera",
                "location": [6.8, -6.6, 5.4],
                "rotation_degrees": [63.0, 0.0, 43.0],
            },
            {
                "type": "LIGHT",
                "light_type": "SUN",
                "name": "FillLight",
                "location": [2.5, -2.5, 6.0],
                "rotation_degrees": [55.0, 0.0, 20.0],
            },
            {
                "type": "MESH_PLANE",
                "name": "BackdropPlane",
                "location": [0.0, 0.0, 0.0],
                "rotation_degrees": [0.0, 0.0, 0.0],
                "scale": [5.5, 5.5, 1.0],
            },
            {
                "type": "MESH_CUBE",
                "name": "FeatureCube",
                "location": [0.0, 0.0, 1.0],
                "rotation_degrees": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
            {
                "type": "MESH_CYLINDER",
                "name": "AccentCylinder",
                "location": [-2.0, 1.6, 1.0],
                "rotation_degrees": [0.0, 0.0, 0.0],
                "scale": [0.6, 0.6, 1.2],
            },
            {
                "type": "MESH_UV_SPHERE",
                "name": "HeroSphere",
                "location": [2.2, 1.5, 1.0],
                "rotation_degrees": [0.0, 0.0, 0.0],
                "scale": [0.8, 0.8, 0.8],
            },
        ],
    }
}


class BlenderInitializer(BaseInitializer):
    """Prepare a deterministic Blender scene and launch it in a fresh macOS window."""

    DEFAULT_APP_COMMAND = "blender"
    DEFAULT_WORKSPACE_ROOT = "/Users/bench/Downloads/helloworld_blender_workspace"
    DEFAULT_FINAL_WAIT_MS = 7000
    DEFAULT_WINDOW_BOUNDS = {"x": 40, "y": 60, "width": 1800, "height": 1000}
    DEFAULT_LAUNCH_ARGS = ["--debug-gpu-force-workarounds"]

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        requested_app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        workspace_name = str(params.get("workspace_name") or "bench").strip() or "bench"
        workspace_root = str(params.get("workspace_root") or self.DEFAULT_WORKSPACE_ROOT).strip()
        scene_name = str(params.get("scene_name") or "scene.blend").strip() or "scene.blend"
        scene_template = str(params.get("scene_template") or "product_stage").strip() or "product_stage"
        raw_scene_spec = params.get("scene_spec")
        launch_args = self._resolve_launch_args(params.get("launch_args"))
        launch_gui = bool(params.get("launch_gui", True))
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        arrange_window = bool(params.get("arrange_window", True))
        window_bounds = dict(self.DEFAULT_WINDOW_BOUNDS)
        window_bounds.update(dict(params.get("window_bounds") or {}))
        workspace_path = f"{workspace_root.rstrip('/')}/{workspace_name}"
        blend_path = f"{workspace_path}/{scene_name}"
        app_command = requested_app_command
        arrange_warning: str | None = None

        try:
            app_command = self._resolve_app_command(controller, requested_app_command)
            self._run(controller, f"{shlex.quote(app_command)} --background --version >/dev/null 2>&1", timeout=30)
            scene_spec = self._resolve_scene_spec(scene_template, raw_scene_spec)
            self._stop_app(controller)
            self._prepare_workspace(
                controller,
                app_command=app_command,
                workspace_path=workspace_path,
                blend_path=blend_path,
                scene_spec=scene_spec,
            )
            if launch_gui:
                self._launch_app(
                    controller,
                    app_command=app_command,
                    blend_path=blend_path,
                    launch_args=launch_args,
                )
                if final_wait_ms > 0:
                    time.sleep(final_wait_ms / 1000.0)
                self._dismiss_splash(controller)
            if launch_gui and arrange_window:
                try:
                    arrange_result = controller.run_bash_script(
                        self._build_arrange_script(window_bounds=window_bounds),
                        timeout=12,
                    )
                    self._raise_for_result(arrange_result, "Blender arrange script failed")
                except Exception as exc:
                    arrange_warning = str(exc)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Blender workspace: {exc}",
                metadata={
                    "app_command": app_command,
                    "requested_app_command": requested_app_command,
                    "workspace_path": workspace_path,
                    "blend_path": blend_path,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Blender workspace",
            metadata={
                "app_command": app_command,
                "requested_app_command": requested_app_command,
                "workspace_path": workspace_path,
                "blend_path": blend_path,
                "launch_gui": launch_gui,
                "arrange_window": arrange_window,
                "window_bounds": window_bounds,
                "launch_args": launch_args,
                "arrange_warning": arrange_warning,
            },
        )

    @staticmethod
    def _run(controller: Any, script: str, *, timeout: int) -> Mapping[str, Any]:
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        if returncode != 0:
            output = str(result.get("output", "")).strip()
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        return result

    @staticmethod
    def _raise_for_result(result: Mapping[str, Any], prefix: str) -> None:
        returncode = int(result.get("returncode", -1))
        if returncode != 0:
            output = str(result.get("output") or "").strip()
            raise RuntimeError(f"{prefix}: {output or f'exit code {returncode}'}")

    def _resolve_app_command(self, controller: Any, requested_app_command: str) -> str:
        candidates = [
            requested_app_command,
            self.DEFAULT_APP_COMMAND,
            "/Applications/Blender.app/Contents/MacOS/Blender",
            "/Applications/Blender.app/Contents/MacOS/blender",
        ]
        seen: list[str] = []
        for candidate in candidates:
            command = str(candidate or "").strip()
            if not command or command in seen:
                continue
            seen.append(command)
            if command.startswith("/"):
                probe = f"test -x {shlex.quote(command)}"
            else:
                probe = f"command -v {shlex.quote(command)} >/dev/null 2>&1"
            result = controller.run_bash_script(probe, timeout=10)
            if int(result.get("returncode", -1)) == 0:
                if command.startswith("/"):
                    return command
                resolved = controller.run_bash_script(f"command -v {shlex.quote(command)}", timeout=10)
                if int(resolved.get("returncode", -1)) == 0:
                    output = str(resolved.get("output") or "").strip().splitlines()
                    if output:
                        return output[-1].strip()
                return command
        raise RuntimeError(f"could not find Blender executable; checked: {', '.join(seen)}")

    @staticmethod
    def _resolve_scene_spec(scene_template: str, raw_scene_spec: Any) -> dict[str, Any]:
        if isinstance(raw_scene_spec, Mapping) and raw_scene_spec:
            render = dict(raw_scene_spec.get("render") or {})
            objects = raw_scene_spec.get("objects") or []
            if not isinstance(objects, list):
                raise RuntimeError("scene_spec.objects must be a list when scene_spec is provided")
            return {
                "render": render,
                "objects": [dict(item) for item in objects if isinstance(item, Mapping)],
            }
        resolved = SCENE_SPECS.get(scene_template)
        if resolved is None:
            raise RuntimeError(f"unknown Blender scene template: {scene_template}")
        return resolved

    def _resolve_launch_args(self, raw_launch_args: Any) -> list[str]:
        if raw_launch_args is None:
            return list(self.DEFAULT_LAUNCH_ARGS)
        if not isinstance(raw_launch_args, list):
            raise RuntimeError("launch_args must be a list when provided")
        return [str(item).strip() for item in raw_launch_args if str(item).strip()]

    def _stop_app(self, controller: Any) -> None:
        self._run(
            controller,
            "\n".join(
                [
                    "pkill -TERM -f '[B]lender' || true",
                    "pkill -TERM -f '[b]lender' || true",
                    "sleep 1",
                    "pkill -KILL -f '[B]lender' || true",
                    "pkill -KILL -f '[b]lender' || true",
                    "sleep 1",
                ]
            ),
            timeout=20,
        )

    def _prepare_workspace(
        self,
        controller: Any,
        *,
        app_command: str,
        workspace_path: str,
        blend_path: str,
        scene_spec: Mapping[str, Any],
    ) -> None:
        payload_path = f"{workspace_path}/scene_payload.json"
        scene_script = """
import bpy
import math
import json
import pathlib

payload = json.loads(pathlib.Path(__PAYLOAD_PATH__).read_text(encoding="utf-8"))
scene_spec = payload["scene_spec"]
blend_path = payload["blend_path"]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
render = scene.render
render_spec = scene_spec["render"]
engine = render_spec.get("engine", "BLENDER_EEVEE_NEXT")
try:
    render.engine = engine
except Exception:
    render.engine = "BLENDER_EEVEE" if engine == "BLENDER_EEVEE_NEXT" else engine
render.resolution_x = int(render_spec["resolution_x"])
render.resolution_y = int(render_spec["resolution_y"])
render.resolution_percentage = int(render_spec.get("resolution_percentage", 100))
render.fps = int(render_spec["fps"])
scene.frame_start = int(render_spec["frame_start"])
scene.frame_end = int(render_spec["frame_end"])
render.image_settings.file_format = render_spec["file_format"]
render.image_settings.color_mode = render_spec["color_mode"]
render.film_transparent = bool(render_spec["film_transparent"])
render.filepath = render_spec.get("filepath", "")

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

for obj_spec in scene_spec["objects"]:
    obj_type = obj_spec["type"]
    if obj_type == "CAMERA":
        camera_data = bpy.data.cameras.new(obj_spec["name"])
        obj = bpy.data.objects.new(obj_spec["name"], camera_data)
        bpy.context.collection.objects.link(obj)
        scene.camera = obj
    elif obj_type == "LIGHT":
        light_data = bpy.data.lights.new(name=obj_spec["name"], type=obj_spec.get("light_type", "SUN"))
        obj = bpy.data.objects.new(obj_spec["name"], light_data)
        bpy.context.collection.objects.link(obj)
    elif obj_type == "MESH_CUBE":
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        obj.name = obj_spec["name"]
    elif obj_type == "MESH_CYLINDER":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32)
        obj = bpy.context.active_object
        obj.name = obj_spec["name"]
    elif obj_type == "MESH_UV_SPHERE":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
        obj = bpy.context.active_object
        obj.name = obj_spec["name"]
    elif obj_type == "MESH_PLANE":
        bpy.ops.mesh.primitive_plane_add()
        obj = bpy.context.active_object
        obj.name = obj_spec["name"]
    else:
        raise RuntimeError(f"Unsupported object type: {obj_type}")

    obj.location = obj_spec.get("location", [0.0, 0.0, 0.0])
    obj.rotation_euler = [math.radians(v) for v in obj_spec.get("rotation_degrees", [0.0, 0.0, 0.0])]
    obj.scale = obj_spec.get("scale", [1.0, 1.0, 1.0])
    if "material_diffuse_color" in obj_spec:
        material = bpy.data.materials.new(name=f"{obj.name}_Material")
        material.diffuse_color = obj_spec["material_diffuse_color"]
        if hasattr(obj.data, "materials"):
            obj.data.materials.append(material)

bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=False)
""".replace("__PAYLOAD_PATH__", json.dumps(payload_path, ensure_ascii=False))

        payload = json.dumps(
            {
                "workspace_path": workspace_path,
                "blend_path": blend_path,
                "scene_spec": scene_spec,
            },
            ensure_ascii=False,
        )
        script = f"""python3 - <<'PY'
import json
import pathlib
import shutil
import subprocess
import textwrap

payload = json.loads({json.dumps(payload, ensure_ascii=False)})
workspace = pathlib.Path(payload["workspace_path"])
blend_path = pathlib.Path(payload["blend_path"])
scene_spec = payload["scene_spec"]
payload_path = pathlib.Path({json.dumps(payload_path, ensure_ascii=False)})

if workspace.exists():
    shutil.rmtree(workspace)
workspace.mkdir(parents=True, exist_ok=True)
blend_path.parent.mkdir(parents=True, exist_ok=True)
payload_path.write_text(
    json.dumps({{"blend_path": str(blend_path), "scene_spec": scene_spec}}, ensure_ascii=False),
    encoding="utf-8",
)

subprocess.run(
    [
        {json.dumps(app_command)},
        "--background",
        "--factory-startup",
        "--python-expr",
        textwrap.dedent({json.dumps(scene_script, ensure_ascii=False)}),
    ],
    check=True,
    capture_output=True,
    text=True,
)
print(json.dumps({{"status": "ok", "blend_path": str(blend_path)}}, ensure_ascii=False))
PY"""
        self._run(controller, script, timeout=180)

    def _launch_app(self, controller: Any, *, app_command: str, blend_path: str, launch_args: list[str]) -> None:
        command_parts = [shlex.quote(app_command), *[shlex.quote(arg) for arg in launch_args], "--factory-startup", shlex.quote(blend_path)]
        command = " ".join(command_parts)
        launch_script = "\n".join(
            [
                f"nohup bash -lc {shlex.quote(command)} >/tmp/helloworld-blender-launch.log 2>&1 &",
                "sleep 1",
            ]
        )
        self._run(controller, launch_script, timeout=15)

    def _dismiss_splash(self, controller: Any) -> None:
        if not hasattr(controller, "execute_action"):
            return
        try:
            ui_nodes = []
            if hasattr(controller, "observe"):
                observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
                ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
            controller.execute_action({"type": "keyboard", "action": "escape", "count": 1}, ui_nodes)
            time.sleep(0.5)
        except Exception:
            return

    @staticmethod
    def _build_arrange_script(*, window_bounds: Mapping[str, Any]) -> str:
        x = int(window_bounds.get("x", 40))
        y = int(window_bounds.get("y", 60))
        width = int(window_bounds.get("width", 1800))
        height = int(window_bounds.get("height", 1000))
        return f"""osascript <<'APPLESCRIPT'
tell application "Blender" to activate
delay 0.5
tell application "System Events"
  tell process "Blender"
    if (count of windows) > 0 then
      set position of front window to {{{x}, {y}}}
      set size of front window to {{{width}, {height}}}
    end if
  end tell
end tell
APPLESCRIPT"""
