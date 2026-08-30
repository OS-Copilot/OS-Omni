"""Blend-file evaluator for Blender desktop tasks on Linux."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class BlenderSceneEvaluator(BaseEvaluator):
    """Validate Blender task outcomes by inspecting scene state in the saved .blend file."""

    DEFAULT_TIMEOUT = 60
    DEFAULT_TOLERANCE = 0.02

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        blend_path = str(params.get("blend_path") or "").strip()
        tolerance = float(params.get("tolerance", self.DEFAULT_TOLERANCE) or self.DEFAULT_TOLERANCE)
        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)
        render_expectations = dict(params.get("render") or {})
        object_expectations = params.get("objects") or []
        additional_blends = params.get("additional_blends") or []
        if additional_blends and not isinstance(additional_blends, list):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.additional_blends must be a list")
        text_artifacts = params.get("text_artifacts") or []
        if text_artifacts and not isinstance(text_artifacts, list):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.text_artifacts must be a list")

        if not blend_path:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.blend_path is required")

        checks = [
            {
                "label": "primary",
                "blend_path": blend_path,
                "render": render_expectations,
                "objects": object_expectations,
            }
        ]
        for index, item in enumerate(additional_blends, start=1):
            if not isinstance(item, Mapping):
                continue
            extra_path = str(item.get("blend_path") or "").strip()
            if not extra_path:
                return EvalResult(status=EvalStatus.ERROR, message=f"additional_blends[{index}] missing blend_path")
            checks.append(
                {
                    "label": str(item.get("label") or f"additional_{index}"),
                    "blend_path": extra_path,
                    "render": dict(item.get("render") or {}),
                    "objects": item.get("objects") or [],
                }
            )

        payloads: dict[str, Any] = {}
        for check in checks:
            label = str(check["label"])
            try:
                payload = self._inspect_blend(
                    controller,
                    blend_path=str(check["blend_path"]),
                    timeout=timeout,
                )
                self._validate_render(dict(check.get("render") or {}), dict(payload.get("render") or {}))
                self._validate_objects(list(check.get("objects") or []), dict(payload.get("objects") or {}), tolerance=tolerance)
            except AssertionError as exc:
                failure_payloads = dict(payloads)
                failure_payloads[label] = locals().get("payload", {})
                return EvalResult(status=EvalStatus.FAIL, message=f"{label}: {exc}", metadata=failure_payloads)
            except Exception as exc:
                return EvalResult(status=EvalStatus.ERROR, message=f"{label}: Blender evaluator failed: {exc}", metadata=payloads)
            payloads[label] = payload

        if text_artifacts:
            try:
                payloads["text_artifacts"] = self._validate_text_artifacts(controller, text_artifacts)
            except AssertionError as exc:
                payloads["text_artifacts"] = getattr(exc, "metadata", None)
                return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=payloads)
            except Exception as exc:
                return EvalResult(status=EvalStatus.ERROR, message=f"text artifact validation failed: {exc}", metadata=payloads)

        return EvalResult(status=EvalStatus.PASS, message="Blender scene evaluation passed", metadata=payloads)

    @staticmethod
    def _inspect_blend(controller: Any, *, blend_path: str, timeout: int) -> dict[str, Any]:
        if not blend_path:
            raise RuntimeError("blend_path is required")

        script = f"""python3 - <<'PY'
import json
import subprocess
import textwrap

blend_path = {json.dumps(blend_path, ensure_ascii=False)}
inspect_script = '''
import bpy
import json
import math

scene = bpy.context.scene
payload = {{
    "render": {{
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
        "eevee_taa_render_samples": int(getattr(scene.eevee, "taa_render_samples", 0)),
    }},
    "objects": {{}},
}}

for obj in bpy.data.objects:
    material = obj.active_material
    payload["objects"][obj.name] = {{
        "location": [round(float(v), 4) for v in obj.location],
        "rotation_degrees": [round(math.degrees(float(v)), 4) for v in obj.rotation_euler],
        "scale": [round(float(v), 4) for v in obj.scale],
        "type": obj.type,
        "material_diffuse_color": (
            [round(float(v), 4) for v in material.diffuse_color]
            if material is not None
            else None
        ),
    }}

print(json.dumps(payload, ensure_ascii=False))
'''

result = subprocess.run(
    ["blender", "--background", "--factory-startup", blend_path, "--python-expr", textwrap.dedent(inspect_script)],
    check=False,
    capture_output=True,
    text=True,
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
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")

        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Blender evaluator returned invalid JSON: {exc}: {output}")

        if payload.get("error"):
            raise RuntimeError(f"Blender evaluator error: {payload.get('error')}")
        return payload

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

    @staticmethod
    def _validate_text_artifacts(controller: Any, artifacts: list[Any]) -> dict[str, Any]:
        script = f"""python3 - <<'PY'
import json
from pathlib import Path

artifacts = json.loads({json.dumps(json.dumps(artifacts, ensure_ascii=False), ensure_ascii=False)})
results = []
for item in artifacts:
    path = Path(str(item.get("path") or ""))
    entry = {{"path": str(path), "exists": path.exists()}}
    if path.exists():
        entry["content"] = path.read_text(encoding="utf-8")
    results.append(entry)
print(json.dumps({{"results": results}}, ensure_ascii=False))
PY"""
        result = controller.run_bash_script(script, timeout=30)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        payload = json.loads(output)
        by_path = {str(item.get("path") or ""): dict(item) for item in payload.get("results") or []}
        for item in artifacts:
            if not isinstance(item, Mapping):
                continue
            path = str(item.get("path") or "")
            actual = by_path.get(path)
            assert actual is not None, f"missing text artifact payload for {path}"
            assert bool(actual.get("exists")), f"expected text artifact to exist: {path}"
            content = str(actual.get("content") or "")
            if "equals" in item:
                expected = str(item.get("equals") or "")
                assert content == expected, f"text artifact mismatch for {path}"
            if "contains" in item:
                needle = str(item.get("contains") or "")
                assert needle in content, f"expected text artifact {path} to contain {needle!r}"
        return payload
