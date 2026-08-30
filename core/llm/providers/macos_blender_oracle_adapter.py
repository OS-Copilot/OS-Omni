"""Task-specific oracle provider for macOS Blender benchmark runs.

The Tart macOS runtime used by this benchmark cannot reliably show Blender's
Metal-backed GUI, but Blender can still open and save .blend files in
background mode. This adapter emits bounded `run_bash_script` actions that use
Blender's own background executable to perform the same saved-scene edits the
GUI task asks for, while preserving multi-step task pacing for hard cases.
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List, Mapping

from ..types import Message, TextPart, ToolCall
from .base import ProviderAdapter, ProviderRequest, ProviderResult


class MacOSBlenderOracleAdapter(ProviderAdapter):
    """Emit deterministic Blender background actions for macOS Blender tasks."""

    provider_name = "macos_blender_oracle"
    supported_response_modes = {"tool_calling", "json_text"}

    PREVIEW_BLEND = "/Users/bench/Downloads/helloworld_blender_workspace/blender_preview_resolution/product_stage.blend"
    SOCIAL_BLEND = "/Users/bench/Downloads/helloworld_blender_workspace/blender_social_render/product_stage.blend"
    RESTAGE_BLEND = "/Users/bench/Downloads/helloworld_blender_workspace/blender_restage_product/product_stage.blend"

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        task_key = self._resolve_task_key(request.messages, request.metadata)
        actions = self._actions_for_task(task_key)
        step_index = self._step_index(request.messages, request.metadata)

        action = dict(actions[step_index]) if step_index < len(actions) else {
            "type": "success",
            "message": "Blender oracle plan completed.",
            "assistant_text": "The saved Blender scene should now satisfy the evaluator.",
        }

        action_type = str(action.get("type") or "").strip()
        if not action_type:
            raise ValueError("Blender oracle action requires non-empty type")
        assistant_text = str(action.get("assistant_text") or f"Blender oracle step {step_index + 1}: {action_type}")
        tool_payload = {k: v for k, v in action.items() if k not in {"type", "assistant_text"}}

        if request.response_mode == "tool_calling":
            return ProviderResult(
                text=assistant_text,
                tool_calls=[
                    ToolCall(
                        name=action_type,
                        arguments_json=json.dumps(tool_payload, ensure_ascii=False),
                        call_id=f"macos-blender-oracle-{step_index + 1}",
                    )
                ],
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": 0},
                raw_response={
                    "provider": self.provider_name,
                    "task_key": task_key,
                    "step_index": step_index,
                    "action": action,
                },
                assistant_message=Message(role="assistant", parts=[TextPart(text=assistant_text)]),
            )

        json_action = dict(action)
        json_action.pop("assistant_text", None)
        return ProviderResult(
            text=json.dumps(json_action, ensure_ascii=False),
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response={
                "provider": self.provider_name,
                "task_key": task_key,
                "step_index": step_index,
                "action": action,
            },
        )

    @staticmethod
    def _step_index(messages: List[Message], metadata: Mapping[str, Any] | None = None) -> int:
        if isinstance(metadata, Mapping):
            completed_step_count = metadata.get("completed_step_count")
            if isinstance(completed_step_count, int) and completed_step_count >= 0:
                return completed_step_count
        return sum(1 for message in messages if getattr(message, "role", "") == "assistant")

    @classmethod
    def _resolve_task_key(cls, messages: List[Message], metadata: Mapping[str, Any] | None = None) -> str:
        if isinstance(metadata, Mapping):
            task_id = str(metadata.get("task_id") or "").strip()
            if task_id:
                task_map = {
                    "macos.blender.set_preview_resolution": "preview_resolution",
                    "macos.blender.prepare_social_render": "social_render",
                    "macos.blender.restage_product_objects": "restage_product",
                    "macos.oracle.blender.set_preview_resolution": "preview_resolution",
                    "macos.oracle.blender.prepare_social_render": "social_render",
                    "macos.oracle.blender.restage_product_objects": "restage_product",
                }
                matched = task_map.get(task_id)
                if matched:
                    return matched
        text = "\n".join(message.text_content() for message in messages).lower()
        if "macos.blender.set_preview_resolution" in text or "blender_preview_resolution" in text or "1280" in text and "720" in text:
            return "preview_resolution"
        if "macos.blender.prepare_social_render" in text or "blender_social_render" in text or "social preview" in text or "transparent film" in text:
            return "social_render"
        if "macos.blender.restage_product_objects" in text or "blender_restage_product" in text or "restage" in text or ("featurecube" in text and "accentcylinder" in text):
            return "restage_product"
        raise ValueError("macOS Blender oracle could not match the current task instruction.")

    @classmethod
    def _actions_for_task(cls, task_key: str) -> List[Dict[str, Any]]:
        if task_key == "preview_resolution":
            return [
                cls._run_action(
                    cls.PREVIEW_BLEND,
                    "scene.render.resolution_x = 1280",
                    "Set preview resolution width to 1280.",
                ),
                cls._run_action(
                    cls.PREVIEW_BLEND,
                    "scene.render.resolution_y = 720",
                    "Set preview resolution height to 720 and save.",
                ),
                {"type": "success", "message": "Preview resolution saved at 1280x720."},
            ]
        if task_key == "social_render":
            return cls._social_render_actions()
        if task_key == "restage_product":
            return cls._restage_product_actions()
        raise ValueError(f"Unsupported macOS Blender oracle task: {task_key!r}")

    @classmethod
    def _social_render_actions(cls) -> List[Dict[str, Any]]:
        blend = cls.SOCIAL_BLEND
        sequence: List[Dict[str, Any]] = [
            cls._run_action(blend, 'scene.render.engine = "CYCLES"', "Set render engine to Cycles."),
            cls._wait_action("Let Blender settle after the render-engine update."),
            cls._run_action(blend, "scene.render.resolution_x = 1600", "Set output resolution X to 1600."),
            cls._wait_action("Review the updated width before continuing."),
            cls._run_action(blend, "scene.render.resolution_y = 900", "Set output resolution Y to 900."),
            cls._wait_action("Review the updated height before continuing."),
            cls._run_action(blend, "scene.render.fps = 30", "Set FPS to 30."),
            cls._wait_action("Review the FPS update before continuing."),
            cls._run_action(blend, "scene.frame_start = 10", "Set frame start to 10."),
            cls._wait_action("Review the frame-start update before continuing."),
            cls._run_action(blend, "scene.frame_end = 210", "Set frame end to 210."),
            cls._wait_action("Review the frame-end update before continuing."),
            cls._run_action(blend, 'scene.render.image_settings.file_format = "PNG"', "Confirm PNG output format."),
            cls._wait_action("Review the PNG format before continuing."),
            cls._run_action(blend, 'scene.render.image_settings.color_mode = "RGBA"', "Set color mode to RGBA."),
            cls._wait_action("Review the RGBA color mode before continuing."),
            cls._run_action(blend, 'scene["helloworld_social_checklist"] = "render-fields-reviewed"', "Record the render checklist review marker."),
            cls._wait_action("Pause after recording the first checklist marker."),
            cls._run_action(blend, 'scene["helloworld_social_final_review"] = "ready-for-transparent-film"', "Record the final social-render review marker."),
            cls._wait_action("Pause before the final transparent-film toggle."),
            cls._wait_action("Confirm all prior social-render fields are staged."),
            cls._run_action(blend, "scene.render.film_transparent = True", "Enable transparent film and save the final social render setup."),
            {"type": "success", "message": "Social render setup saved."},
        ]
        return sequence

    @classmethod
    def _restage_product_actions(cls) -> List[Dict[str, Any]]:
        blend = cls.RESTAGE_BLEND
        sequence: List[Dict[str, Any]] = [
            cls._run_action(blend, 'bpy.data.objects["FeatureCube"].location.x = 2.0', "Set FeatureCube location X to 2.0."),
            cls._wait_action("Review FeatureCube location X."),
            cls._run_action(blend, 'bpy.data.objects["FeatureCube"].location.y = -1.0', "Set FeatureCube location Y to -1.0."),
            cls._wait_action("Review FeatureCube location Y."),
            cls._run_action(blend, 'bpy.data.objects["FeatureCube"].location.z = 1.5', "Set FeatureCube location Z to 1.5."),
            cls._wait_action("Review FeatureCube location Z."),
            cls._run_action(blend, 'bpy.data.objects["FeatureCube"].scale.x = 1.4', "Set FeatureCube scale X to 1.4."),
            cls._wait_action("Review FeatureCube scale X."),
            cls._run_action(blend, 'bpy.data.objects["FeatureCube"].scale.y = 0.8', "Set FeatureCube scale Y to 0.8."),
            cls._wait_action("Review FeatureCube scale Y."),
            cls._run_action(blend, 'bpy.data.objects["FeatureCube"].scale.z = 1.9', "Set FeatureCube scale Z to 1.9."),
            cls._wait_action("Review FeatureCube scale Z."),
            cls._run_action(blend, 'bpy.data.objects["AccentCylinder"].location.x = -2.3', "Set AccentCylinder location X to -2.3."),
            cls._wait_action("Review AccentCylinder location X."),
            cls._run_action(blend, 'bpy.data.objects["AccentCylinder"].location.y = 1.2', "Set AccentCylinder location Y to 1.2."),
            cls._wait_action("Review AccentCylinder location Y."),
            cls._run_action(blend, 'bpy.data.objects["AccentCylinder"].location.z = 0.9', "Set AccentCylinder location Z to 0.9."),
            cls._wait_action("Review AccentCylinder location Z."),
            cls._run_action(blend, 'bpy.data.objects["AccentCylinder"].scale.x = 0.6', "Set AccentCylinder scale X to 0.6."),
            cls._wait_action("Review AccentCylinder scale X."),
            cls._run_action(blend, 'bpy.data.objects["AccentCylinder"].scale.y = 0.6', "Set AccentCylinder scale Y to 0.6."),
            cls._wait_action("Review AccentCylinder scale Y."),
            cls._run_action(blend, 'bpy.data.objects["AccentCylinder"].scale.z = 2.2', "Set AccentCylinder scale Z to 2.2."),
            cls._wait_action("Review AccentCylinder scale Z."),
            cls._run_action(blend, 'bpy.data.objects["FillLight"].rotation_euler.x = math.radians(50.0)', "Set FillLight rotation X to 50 degrees."),
            cls._wait_action("Review FillLight rotation X."),
            cls._run_action(blend, 'bpy.data.objects["FillLight"].rotation_euler.y = math.radians(0.0)', "Set FillLight rotation Y to 0 degrees."),
            cls._wait_action("Review FillLight rotation Y."),
            cls._run_action(blend, 'bpy.data.objects["FillLight"].rotation_euler.z = math.radians(35.0)', "Set FillLight rotation Z to 35 degrees and save."),
            {"type": "success", "message": "Product object restaging saved."},
        ]
        return sequence

    @staticmethod
    def _wait_action(text: str) -> Dict[str, Any]:
        return {"type": "wait", "ms": 250, "assistant_text": text}

    @classmethod
    def _run_action(cls, blend_path: str, body: str, assistant_text: str) -> Dict[str, Any]:
        return {
            "type": "run_bash_script",
            "script": cls._build_blender_script(blend_path=blend_path, body=body),
            "timeout": 90,
            "assistant_text": assistant_text,
        }

    @staticmethod
    def _build_blender_script(*, blend_path: str, body: str) -> str:
        python_code = f"""
import bpy
import math

blend_path = {json.dumps(blend_path, ensure_ascii=False)}
scene = bpy.context.scene
{body}
bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=False)
print("saved", blend_path)
"""
        return f"""python3 - <<'PY'
import json
import pathlib
import shutil
import subprocess
import textwrap

blend_path = {json.dumps(blend_path, ensure_ascii=False)}
code = textwrap.dedent({json.dumps(python_code, ensure_ascii=False)})
candidates = [
    shutil.which("blender"),
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/Applications/Blender.app/Contents/MacOS/blender",
]
app = next((candidate for candidate in candidates if candidate and pathlib.Path(candidate).exists()), None)
if app is None:
    print(json.dumps({{"error": "blender_not_found"}}, ensure_ascii=False))
    raise SystemExit(127)
proc = subprocess.run(
    [app, "--background", "--factory-startup", blend_path, "--python-expr", code],
    check=False,
    capture_output=True,
    text=True,
    timeout=75,
)
if proc.returncode != 0:
    print(proc.stdout)
    print(proc.stderr)
    raise SystemExit(proc.returncode)
print(proc.stdout[-2000:])
PY"""
