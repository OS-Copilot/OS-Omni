"""Blend-file evaluator for Blender desktop tasks on macOS."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class BlenderSceneEvaluator(BaseEvaluator):
    """Validate Blender task outcomes by inspecting scene state in the saved .blend file."""

    DEFAULT_TIMEOUT = 60
    DEFAULT_TOLERANCE = 0.02
    DEFAULT_APP_COMMAND = "blender"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        blend_path = str(params.get("blend_path") or "").strip()
        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip() or self.DEFAULT_APP_COMMAND
        tolerance = float(params.get("tolerance", self.DEFAULT_TOLERANCE) or self.DEFAULT_TOLERANCE)
        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)
        render_expectations = dict(params.get("render") or {})
        object_expectations = params.get("objects") or []

        if not blend_path:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.blend_path is required")

        script = self._build_inspection_script(blend_path=blend_path, app_command=app_command, timeout=timeout)
        result = controller.run_bash_script(script, timeout=timeout + 10)
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
            return EvalResult(status=EvalStatus.ERROR, message=f"Blender evaluator returned invalid JSON: {exc}: {output}")

        if payload.get("error"):
            return EvalResult(status=EvalStatus.ERROR, message=f"Blender evaluator error: {payload.get('error')}", metadata=payload)

        try:
            self._validate_render(render_expectations, dict(payload.get("render") or {}))
            self._validate_objects(object_expectations, dict(payload.get("objects") or {}), tolerance=tolerance)
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=payload)
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Blender evaluator failed: {exc}", metadata=payload)

        return EvalResult(status=EvalStatus.PASS, message="Blender scene evaluation passed", metadata=payload)

    @staticmethod
    def _build_inspection_script(*, blend_path: str, app_command: str, timeout: int) -> str:
        inspect_script = """
import bpy
import json
import math

scene = bpy.context.scene
payload = {
    "render": {
        "engine": scene.render.engine,
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "resolution_percentage": scene.render.resolution_percentage,
        "fps": scene.render.fps,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "filepath": scene.render.filepath,
        "file_format": scene.render.image_settings.file_format,
        "color_mode": scene.render.image_settings.color_mode,
        "film_transparent": bool(scene.render.film_transparent),
    },
    "objects": {},
}

for obj in bpy.data.objects:
    material = obj.active_material
    payload["objects"][obj.name] = {
        "location": [round(float(v), 4) for v in obj.location],
        "rotation_degrees": [round(math.degrees(float(v)), 4) for v in obj.rotation_euler],
        "scale": [round(float(v), 4) for v in obj.scale],
        "type": obj.type,
        "material_diffuse_color": (
            [round(float(v), 4) for v in material.diffuse_color]
            if material is not None
            else None
        ),
    }

print(json.dumps(payload, ensure_ascii=False))
"""
        return f"""python3 - <<'PY'
import json
import pathlib
import shutil
import subprocess
import textwrap

blend_path = {json.dumps(blend_path, ensure_ascii=False)}
requested = {json.dumps(app_command, ensure_ascii=False)}
timeout = {int(timeout)}

candidates = [
    requested,
    "blender",
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/Applications/Blender.app/Contents/MacOS/blender",
]
app = None
for candidate in candidates:
    candidate = str(candidate or "").strip()
    if not candidate:
        continue
    if candidate.startswith("/"):
        if pathlib.Path(candidate).exists():
            app = candidate
            break
    else:
        resolved = shutil.which(candidate)
        if resolved:
            app = resolved
            break
if app is None:
    print(json.dumps({{"error": "blender_not_found", "candidates": candidates}}, ensure_ascii=False))
    raise SystemExit(0)

result = subprocess.run(
    [app, "--background", "--factory-startup", blend_path, "--python-expr", textwrap.dedent({json.dumps(inspect_script, ensure_ascii=False)})],
    check=False,
    capture_output=True,
    text=True,
    timeout=timeout,
)

if result.returncode != 0:
    print(json.dumps({{"error": "blender_failed", "stderr": result.stderr}}, ensure_ascii=False))
else:
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    json_lines = [line for line in lines if line.startswith("{{") and line.endswith("}}")]
    if json_lines:
        print(json_lines[-1])
    else:
        stdout = result.stdout
        start = stdout.find("{{")
        end = stdout.rfind("}}")
        if start != -1 and end != -1 and end > start:
            print(stdout[start : end + 1])
        else:
            print(json.dumps({{"error": "missing_output", "stdout": result.stdout}}, ensure_ascii=False))
PY"""

    @staticmethod
    def _validate_render(expectations: Mapping[str, Any], actual: Mapping[str, Any]) -> None:
        for key, expected in expectations.items():
            assert key in actual, f"missing render field: {key}"
            assert actual[key] == expected, f"expected render {key}={expected!r}, got {actual[key]!r}"

    @staticmethod
    def _assert_close_vector(label: str, expected: list[float], actual: list[float], *, tolerance: float) -> None:
        assert len(expected) == len(actual), f"{label} length mismatch"
        for index, (exp, got) in enumerate(zip(expected, actual)):
            assert abs(float(exp) - float(got)) <= tolerance, (
                f"{label}[{index}] expected {float(exp):.4f}, got {float(got):.4f}"
            )

    def _validate_objects(self, expectations: list[Any], actual: Mapping[str, Any], *, tolerance: float) -> None:
        for item in expectations:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "").strip()
            assert name, "object expectation missing name"
            actual_obj = dict(actual.get(name) or {})
            assert actual_obj, f"missing object in blend file: {name}"
            if "type" in item:
                expected_type = str(item.get("type") or "").strip()
                actual_type = str(actual_obj.get("type") or "").strip()
                assert actual_type == expected_type, f"{name}.type expected {expected_type!r}, got {actual_type!r}"
            if "location" in item:
                self._assert_close_vector(
                    f"{name}.location",
                    list(item.get("location") or []),
                    list(actual_obj.get("location") or []),
                    tolerance=tolerance,
                )
            if "rotation_degrees" in item:
                self._assert_close_vector(
                    f"{name}.rotation_degrees",
                    list(item.get("rotation_degrees") or []),
                    list(actual_obj.get("rotation_degrees") or []),
                    tolerance=tolerance,
                )
            if "scale" in item:
                self._assert_close_vector(
                    f"{name}.scale",
                    list(item.get("scale") or []),
                    list(actual_obj.get("scale") or []),
                    tolerance=tolerance,
                )
            if "material_diffuse_color" in item:
                self._assert_close_vector(
                    f"{name}.material_diffuse_color",
                    list(item.get("material_diffuse_color") or []),
                    list(actual_obj.get("material_diffuse_color") or []),
                    tolerance=tolerance,
                )
