"""Initializer utilities for Blender desktop tasks on Linux."""

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
            "engine": "BLENDER_EEVEE",
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
    """Prepare a deterministic Blender scene and launch it in a fresh window."""

    DEFAULT_APP_COMMAND = "blender"
    DEFAULT_WORKSPACE_ROOT = "/tmp/helloworld_blender_workspace"
    DEFAULT_FINAL_WAIT_MS = 5500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        workspace_name = str(params.get("workspace_name") or "bench").strip() or "bench"
        workspace_root = str(params.get("workspace_root") or self.DEFAULT_WORKSPACE_ROOT).strip()
        scene_name = str(params.get("scene_name") or "scene.blend").strip() or "scene.blend"
        scene_template = str(params.get("scene_template") or "product_stage").strip() or "product_stage"
        raw_scene_spec = params.get("scene_spec")
        raw_extra_scene_specs = params.get("extra_scene_specs") or []
        raw_text_artifacts = params.get("text_artifacts") or []
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        workspace_path = f"{workspace_root.rstrip('/')}/{workspace_name}"
        blend_path = f"{workspace_path}/{scene_name}"

        try:
            self._run(controller, f"command -v {shlex.quote(app_command)} >/dev/null 2>&1", timeout=10)
            self._run(controller, f"{shlex.quote(app_command)} --background --version >/dev/null 2>&1", timeout=20)
            scene_spec = self._resolve_scene_spec(scene_template, raw_scene_spec)
            extra_scene_specs = self._resolve_extra_scene_specs(raw_extra_scene_specs)
            text_artifacts = self._resolve_text_artifacts(raw_text_artifacts)
            self._stop_app(controller)
            self._prepare_workspace(
                controller,
                app_command=app_command,
                workspace_path=workspace_path,
                blend_path=blend_path,
                scene_spec=scene_spec,
                extra_scene_specs=extra_scene_specs,
                text_artifacts=text_artifacts,
            )
            self._launch_app(controller, app_command=app_command, blend_path=blend_path)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Blender workspace: {exc}",
                metadata={"workspace_path": workspace_path, "blend_path": blend_path},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Blender workspace",
            metadata={"workspace_path": workspace_path, "blend_path": blend_path},
        )

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

    @staticmethod
    def _resolve_extra_scene_specs(raw_extra_scene_specs: Any) -> list[dict[str, Any]]:
        if raw_extra_scene_specs is None:
            return []
        if not isinstance(raw_extra_scene_specs, list):
            raise RuntimeError("extra_scene_specs must be a list when provided")
        resolved: list[dict[str, Any]] = []
        for item in raw_extra_scene_specs:
            if not isinstance(item, Mapping):
                continue
            scene_name = str(item.get("scene_name") or "").strip()
            if not scene_name:
                raise RuntimeError("extra_scene_specs entries require scene_name")
            spec = item.get("scene_spec")
            if not isinstance(spec, Mapping):
                raise RuntimeError("extra_scene_specs entries require scene_spec")
            render = dict(spec.get("render") or {})
            objects = spec.get("objects") or []
            if not isinstance(objects, list):
                raise RuntimeError("extra_scene_specs scene_spec.objects must be a list")
            resolved.append(
                {
                    "scene_name": scene_name,
                    "scene_spec": {
                        "render": render,
                        "objects": [dict(obj) for obj in objects if isinstance(obj, Mapping)],
                    },
                }
            )
        return resolved

    @staticmethod
    def _resolve_text_artifacts(raw_text_artifacts: Any) -> list[dict[str, str]]:
        if raw_text_artifacts is None:
            return []
        if not isinstance(raw_text_artifacts, list):
            raise RuntimeError("text_artifacts must be a list when provided")
        resolved: list[dict[str, str]] = []
        for item in raw_text_artifacts:
            if not isinstance(item, Mapping):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                raise RuntimeError("text_artifacts entries require path")
            content = str(item.get("content") or item.get("equals") or "")
            resolved.append({"path": path, "content": content})
        return resolved

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
                    "pkill -TERM -f 'blender' || true",
                    "sleep 1",
                    "pkill -KILL -f 'blender' || true",
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
        extra_scene_specs: list[dict[str, Any]],
        text_artifacts: list[dict[str, str]],
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

def build_scene(spec, target_path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    render = scene.render
    render.engine = spec["render"]["engine"]
    render.resolution_x = int(spec["render"]["resolution_x"])
    render.resolution_y = int(spec["render"]["resolution_y"])
    render.resolution_percentage = int(spec["render"].get("resolution_percentage", 100))
    render.fps = int(spec["render"]["fps"])
    scene.frame_start = int(spec["render"]["frame_start"])
    scene.frame_end = int(spec["render"]["frame_end"])
    render.image_settings.file_format = spec["render"]["file_format"]
    render.image_settings.color_mode = spec["render"]["color_mode"]
    render.film_transparent = bool(spec["render"]["film_transparent"])
    render.filepath = spec["render"].get("filepath", "")
    if "eevee_taa_render_samples" in spec["render"]:
        scene.eevee.taa_render_samples = int(spec["render"]["eevee_taa_render_samples"])

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    for obj_spec in spec["objects"]:
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
            mat = bpy.data.materials.new(name=f"{obj.name}_Material")
            mat.diffuse_color = obj_spec["material_diffuse_color"]
            obj.data.materials.append(mat)

    bpy.ops.wm.save_as_mainfile(filepath=target_path, copy=False)

build_scene(scene_spec, blend_path)
for extra in payload.get("extra_scene_specs", []):
    build_scene(extra["scene_spec"], extra["blend_path"])
""".replace("__PAYLOAD_PATH__", json.dumps(payload_path, ensure_ascii=False))

        payload = json.dumps(
            {
                "workspace_path": workspace_path,
                "blend_path": blend_path,
                "scene_spec": scene_spec,
                "extra_scene_specs": [
                    {
                        "blend_path": f"{workspace_path}/{item['scene_name']}",
                        "scene_spec": item["scene_spec"],
                    }
                    for item in extra_scene_specs
                ],
                "text_artifacts": text_artifacts,
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
for artifact in payload.get("text_artifacts", []):
    artifact_path = pathlib.Path(str(artifact["path"]))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(str(artifact.get("content") or ""), encoding="utf-8")
payload_path.write_text(
    json.dumps(
        {{
            "blend_path": str(blend_path),
            "scene_spec": scene_spec,
            "extra_scene_specs": payload.get("extra_scene_specs", []),
        }},
        ensure_ascii=False,
    ),
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

    def _launch_app(self, controller: Any, *, app_command: str, blend_path: str) -> None:
        command = " ".join([shlex.quote(app_command), "--factory-startup", shlex.quote(blend_path)])
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
