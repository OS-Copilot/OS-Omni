from __future__ import annotations

import ast
import base64
import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relpath: str) -> dict[str, Any]:
    path = ROOT / relpath
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{relpath} is not a YAML mapping")
    return data


def dump_yaml(relpath: str, data: dict[str, Any]) -> None:
    (ROOT / relpath).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


def decode_blender_payload(check_relpath: str) -> tuple[str, dict[str, Any]]:
    text = (ROOT / check_relpath).read_text(encoding="utf-8")
    match = re.search(r'FromBase64String\("([^"]+)"\)', text)
    if not match:
        raise RuntimeError(f"Missing Blender payload in {check_relpath}")
    return match.group(1), json.loads(base64.b64decode(match.group(1)).decode("utf-8"))


def write_blender_payload(check_relpath: str, old_b64: str, payload: dict[str, Any]) -> None:
    text = (ROOT / check_relpath).read_text(encoding="utf-8")
    new_b64 = base64.b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).decode("ascii")
    (ROOT / check_relpath).write_text(text.replace(old_b64, new_b64, 1), encoding="utf-8")


def render(x: int, y: int, percent: int, fps: int, start: int, end: int, filepath: str) -> dict[str, Any]:
    return {
        "resolution_x": x,
        "resolution_y": y,
        "resolution_percentage": percent,
        "fps": fps,
        "frame_start": start,
        "frame_end": end,
        "filepath": filepath,
    }


SOCIAL_EXTREME_ADDITIONAL = [
    {
        "label": "colorway_variant",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_colorway_variant.blend",
        "render": render(1400, 1400, 100, 30, 12, 96, "//renders/social_colorway_variant.png"),
        "objects": [
            {"name": "Camera", "location": [5.4, -5.6, 4.2], "rotation_degrees": [61, 0, 39]},
            {"name": "FeatureCube", "material_diffuse_color": [0.18, 0.72, 0.94]},
            {"name": "CTAChip", "location": [2.45, 2.55, 0.34], "material_diffuse_color": [0.98, 0.28, 0.18]},
        ],
    },
    {
        "label": "shadow_pass",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_shadow_pass.blend",
        "render": render(1600, 1000, 100, 30, 30, 150, "//renders/social_shadow_pass.png"),
        "objects": [
            {"name": "Camera", "location": [8.0, -6.8, 5.4], "rotation_degrees": [59, 0, 49]},
            {"name": "ProductShadow", "location": [1.25, -0.7, 0.015], "scale": [1.9, 0.92, 1.0]},
            {"name": "BackdropPlane", "scale": [7.0, 5.15, 1.0]},
        ],
    },
    {
        "label": "annotation_pass",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_annotation_pass.blend",
        "render": render(1920, 1080, 100, 30, 80, 200, "//renders/social_annotation_pass.png"),
        "objects": [
            {"name": "FrameGuide", "location": [-1.15, 2.85, 0.04], "scale": [2.2, 0.42, 1.0]},
            {"name": "ReviewTab", "location": [-2.15, -3.1, 0.32], "scale": [0.95, 0.22, 0.38]},
            {"name": "TopRule", "location": [0.0, 3.65, 0.08], "scale": [3.25, 0.12, 1.0]},
        ],
    },
    {
        "label": "cta_detail",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_cta_detail.blend",
        "render": render(900, 900, 100, 30, 96, 132, "//renders/social_cta_detail.png"),
        "objects": [
            {"name": "Camera", "location": [3.8, -3.5, 3.3], "rotation_degrees": [58, 0, 34]},
            {"name": "CTAChip", "location": [3.0, 2.45, 0.42], "scale": [0.44, 0.44, 0.18]},
            {"name": "HeroPin", "location": [2.65, 0.5, 0.86], "scale": [0.24, 0.24, 0.24]},
        ],
    },
    {
        "label": "composite_board",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_composite_board.blend",
        "render": render(2400, 1350, 100, 30, 1, 240, "//renders/social_composite_board.png"),
        "objects": [
            {"name": "Camera", "location": [9.6, -8.0, 6.0], "rotation_degrees": [56, 0, 51]},
            {"name": "FeatureCube", "location": [0.45, -0.35, 1.62], "scale": [1.42, 1.02, 1.66]},
            {"name": "CaptionBar", "location": [0.7, -3.02, 0.1], "scale": [2.15, 0.2, 1.0]},
            {"name": "EdgeFrame", "scale": [2.1, 0.14, 0.44]},
        ],
    },
    {
        "label": "final_audit_stack",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_final_audit_stack.blend",
        "render": render(2560, 1440, 100, 30, 120, 240, "//renders/social_final_audit_stack.png"),
        "objects": [
            {"name": "Camera", "location": [7.2, -6.4, 5.7], "rotation_degrees": [62, 0, 44]},
            {"name": "FillLight", "location": [2.25, -3.55, 7.4], "scale": [1.45, 1.45, 1.45]},
            {"name": "ProofDot", "location": [3.15, 0.72, 0.7], "scale": [0.27, 0.27, 0.27]},
            {"name": "LowerGuide", "location": [0.18, -3.52, 0.07], "scale": [2.9, 0.1, 1.0]},
        ],
    },
]


RESTAGE_EXTREME_ADDITIONAL = [
    {
        "label": "colorway_variant",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_colorway_variant.blend",
        "render": render(1500, 1000, 100, 24, 20, 110, "//renders/restage_colorway_variant.png"),
        "objects": [
            {"name": "Camera", "location": [6.2, -5.9, 4.9], "rotation_degrees": [60, 0, 43]},
            {"name": "FeatureCube", "material_diffuse_color": [0.18, 0.56, 0.96]},
            {"name": "HeroSphere", "material_diffuse_color": [0.98, 0.38, 0.18]},
        ],
    },
    {
        "label": "shadow_pass",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_shadow_pass.blend",
        "render": render(1680, 1050, 100, 24, 35, 150, "//renders/restage_shadow_pass.png"),
        "objects": [
            {"name": "Camera", "location": [8.2, -7.2, 6.0], "rotation_degrees": [58, 0, 50]},
            {"name": "BackdropPlane", "scale": [7.1, 5.25, 1.0]},
            {"name": "ShelfPlane", "location": [-2.45, 3.1, 0.08], "scale": [1.95, 0.24, 1.0]},
        ],
    },
    {
        "label": "label_closeup",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_label_closeup.blend",
        "render": render(1100, 1100, 100, 24, 70, 132, "//renders/restage_label_closeup.png"),
        "objects": [
            {"name": "Camera", "location": [4.0, -4.3, 3.8], "rotation_degrees": [60, 0, 37]},
            {"name": "LabelCube", "location": [-0.15, -3.2, 0.32], "scale": [0.7, 0.22, 0.36]},
            {"name": "ReviewFlag", "location": [2.1, -3.45, 0.1], "scale": [1.45, 0.2, 1.0]},
        ],
    },
    {
        "label": "depth_review",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_depth_review.blend",
        "render": render(1800, 1200, 100, 24, 90, 165, "//renders/restage_depth_review.png"),
        "objects": [
            {"name": "DepthRail", "location": [1.45, 2.95, 0.36], "scale": [2.9, 0.22, 0.34]},
            {"name": "OrbitMarker", "location": [3.4, 0.75, 0.9], "scale": [0.3, 0.3, 0.95]},
            {"name": "AnchorCube", "location": [-3.45, 1.0, 0.42], "scale": [0.52, 0.52, 0.46]},
        ],
    },
    {
        "label": "composite_board",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_composite_board.blend",
        "render": render(2400, 1350, 100, 24, 1, 180, "//renders/restage_composite_board.png"),
        "objects": [
            {"name": "Camera", "location": [9.3, -8.4, 6.5], "rotation_degrees": [57, 0, 51]},
            {"name": "FeatureCube", "location": [1.65, -0.8, 1.82], "scale": [1.62, 0.95, 2.1]},
            {"name": "BaselineRail", "location": [1.1, 3.72, 0.26], "scale": [2.65, 0.14, 0.32]},
            {"name": "TensionSphere", "location": [0.52, 2.52, 0.72], "scale": [0.34, 0.34, 0.34]},
        ],
    },
    {
        "label": "final_audit_stack",
        "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_final_audit_stack.blend",
        "render": render(2560, 1440, 100, 24, 120, 180, "//renders/restage_final_audit_stack.png"),
        "objects": [
            {"name": "Camera", "location": [7.0, -6.9, 5.9], "rotation_degrees": [60, 0, 46]},
            {"name": "FillLight", "location": [1.9, -4.0, 7.4], "scale": [1.48, 1.48, 1.48]},
            {"name": "ReviewPost", "location": [2.55, -2.85, 1.22], "scale": [0.22, 0.22, 1.62]},
            {"name": "FocusDot", "location": [-0.78, 2.85, 0.66], "scale": [0.28, 0.28, 0.28]},
        ],
    },
]


def social_text_artifacts() -> list[dict[str, str]]:
    crosswalk = (
        "file\trole\tresolution\tlinked_object\n"
        "product_stage.blend\tprimary\t1800x1000\tFeatureCube\n"
        "social_review_closeup.blend\tcloseup\t1200x1200\tProofDot\n"
        "social_archive_wide.blend\tarchive\t2200x1200\tTopRule\n"
        "social_story_crop.blend\tstory\t1080x1920\tCaptionBar\n"
        "social_dependency_audit.blend\tdependency\t1600x900\tHeroPin\n"
        "social_colorway_variant.blend\tcolorway\t1400x1400\tCTAChip\n"
        "social_shadow_pass.blend\tshadow\t1600x1000\tProductShadow\n"
        "social_annotation_pass.blend\tannotation\t1920x1080\tFrameGuide\n"
        "social_cta_detail.blend\tdetail\t900x900\tCTAChip\n"
        "social_composite_board.blend\tcomposite\t2400x1350\tEdgeFrame\n"
        "social_final_audit_stack.blend\tfinal-audit\t2560x1440\tProofDot"
    )
    derivatives = (
        "social_review_closeup.blend|social_archive_wide.blend|social_story_crop.blend|"
        "social_dependency_audit.blend|social_colorway_variant.blend|social_shadow_pass.blend|"
        "social_annotation_pass.blend|social_cta_detail.blend|social_composite_board.blend|"
        "social_final_audit_stack.blend"
    )
    graph = (
        "blend\tdepends_on\tpurpose\n"
        "social_review_closeup.blend\tproduct_stage.blend\tcloseup-proof\n"
        "social_archive_wide.blend\tproduct_stage.blend\tarchive-context\n"
        "social_story_crop.blend\tproduct_stage.blend\tvertical-story\n"
        "social_dependency_audit.blend\tsocial_review_closeup.blend|social_story_crop.blend\tcross-file-audit\n"
        "social_colorway_variant.blend\tsocial_review_closeup.blend|social_archive_wide.blend\tpalette-reconcile\n"
        "social_shadow_pass.blend\tproduct_stage.blend|social_archive_wide.blend\tshadow-reconcile\n"
        "social_annotation_pass.blend\tsocial_story_crop.blend|social_colorway_variant.blend\tannotation-reconcile\n"
        "social_cta_detail.blend\tsocial_colorway_variant.blend|social_annotation_pass.blend\tcta-closeup\n"
        "social_composite_board.blend\tsocial_shadow_pass.blend|social_annotation_pass.blend|social_cta_detail.blend\tcomposite-board\n"
        "social_final_audit_stack.blend\tsocial_composite_board.blend|social_dependency_audit.blend\tfinal-audit"
    )
    return [
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_delivery_crosswalk.tsv",
            "content": crosswalk,
        },
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_render_bundle_index.txt",
            "content": (
                "primary=product_stage.blend\n"
                f"derivatives={derivatives}\n"
                "shared_workspace=blender_social_render\n"
                "blend_file_count=11\n"
                "multi_blend_dependency=social_composite_board.blend->social_final_audit_stack.blend\n"
                "handoff_status=extreme-ready"
            ),
        },
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_blend_dependency_graph.tsv",
            "content": graph,
        },
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_blend_orchestration_index.txt",
            "content": (
                "primary=product_stage.blend\n"
                "blend_file_count=11\n"
                "stage_1=social_review_closeup.blend|social_archive_wide.blend|social_story_crop.blend\n"
                "stage_2=social_dependency_audit.blend|social_colorway_variant.blend|social_shadow_pass.blend|social_annotation_pass.blend|social_cta_detail.blend\n"
                "stage_3=social_composite_board.blend|social_final_audit_stack.blend\n"
                "required_dependency=social_final_audit_stack.blend\n"
                "handoff_status=extreme-hard-plus-ready"
            ),
        },
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_extreme_review_matrix.csv",
            "content": (
                "check,source_blends,status\n"
                "palette,social_review_closeup.blend|social_archive_wide.blend,ready\n"
                "shadow,social_archive_wide.blend|social_shadow_pass.blend,ready\n"
                "annotation,social_story_crop.blend|social_annotation_pass.blend,ready\n"
                "final,social_composite_board.blend|social_final_audit_stack.blend,locked"
            ),
        },
    ]


def restage_text_artifacts() -> list[dict[str, str]]:
    crosswalk = (
        "file\trole\tresolution\tlinked_object\n"
        "product_stage.blend\tprimary\t1536x1080\tFeatureCube\n"
        "restage_review_closeup.blend\tcloseup\t1280x960\tVariancePin\n"
        "restage_archive_wide.blend\tarchive\t2048x1152\tBaselineRail\n"
        "restage_qa_isolation.blend\tqa\t1440x1440\tReviewPost\n"
        "restage_dependency_audit.blend\tdependency\t1920x1080\tTensionSphere\n"
        "restage_colorway_variant.blend\tcolorway\t1500x1000\tHeroSphere\n"
        "restage_shadow_pass.blend\tshadow\t1680x1050\tShelfPlane\n"
        "restage_label_closeup.blend\tlabel\t1100x1100\tLabelCube\n"
        "restage_depth_review.blend\tdepth\t1800x1200\tDepthRail\n"
        "restage_composite_board.blend\tcomposite\t2400x1350\tBaselineRail\n"
        "restage_final_audit_stack.blend\tfinal-audit\t2560x1440\tReviewPost"
    )
    derivatives = (
        "restage_review_closeup.blend|restage_archive_wide.blend|restage_qa_isolation.blend|"
        "restage_dependency_audit.blend|restage_colorway_variant.blend|restage_shadow_pass.blend|"
        "restage_label_closeup.blend|restage_depth_review.blend|restage_composite_board.blend|"
        "restage_final_audit_stack.blend"
    )
    graph = (
        "blend\tdepends_on\tpurpose\n"
        "restage_review_closeup.blend\tproduct_stage.blend\tcloseup-proof\n"
        "restage_archive_wide.blend\tproduct_stage.blend\tarchive-context\n"
        "restage_qa_isolation.blend\tproduct_stage.blend\tqa-isolation\n"
        "restage_dependency_audit.blend\trestage_review_closeup.blend|restage_qa_isolation.blend\tcross-file-audit\n"
        "restage_colorway_variant.blend\trestage_review_closeup.blend|restage_archive_wide.blend\tpalette-reconcile\n"
        "restage_shadow_pass.blend\tproduct_stage.blend|restage_archive_wide.blend\tshadow-reconcile\n"
        "restage_label_closeup.blend\trestage_qa_isolation.blend|restage_colorway_variant.blend\tlabel-proof\n"
        "restage_depth_review.blend\trestage_archive_wide.blend|restage_shadow_pass.blend\tdepth-proof\n"
        "restage_composite_board.blend\trestage_label_closeup.blend|restage_depth_review.blend|restage_dependency_audit.blend\tcomposite-board\n"
        "restage_final_audit_stack.blend\trestage_composite_board.blend|restage_dependency_audit.blend\tfinal-audit"
    )
    return [
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_delivery_crosswalk.tsv",
            "content": crosswalk,
        },
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_render_bundle_index.txt",
            "content": (
                "primary=product_stage.blend\n"
                f"derivatives={derivatives}\n"
                "shared_workspace=blender_restage_product\n"
                "blend_file_count=11\n"
                "multi_blend_dependency=restage_composite_board.blend->restage_final_audit_stack.blend\n"
                "handoff_status=extreme-ready"
            ),
        },
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_blend_dependency_graph.tsv",
            "content": graph,
        },
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_blend_orchestration_index.txt",
            "content": (
                "primary=product_stage.blend\n"
                "blend_file_count=11\n"
                "stage_1=restage_review_closeup.blend|restage_archive_wide.blend|restage_qa_isolation.blend\n"
                "stage_2=restage_dependency_audit.blend|restage_colorway_variant.blend|restage_shadow_pass.blend|restage_label_closeup.blend|restage_depth_review.blend\n"
                "stage_3=restage_composite_board.blend|restage_final_audit_stack.blend\n"
                "required_dependency=restage_final_audit_stack.blend\n"
                "handoff_status=extreme-hard-plus-ready"
            ),
        },
        {
            "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_extreme_review_matrix.csv",
            "content": (
                "check,source_blends,status\n"
                "palette,restage_review_closeup.blend|restage_archive_wide.blend,ready\n"
                "label,restage_qa_isolation.blend|restage_label_closeup.blend,ready\n"
                "depth,restage_archive_wide.blend|restage_depth_review.blend,ready\n"
                "final,restage_composite_board.blend|restage_final_audit_stack.blend,locked"
            ),
        },
    ]


def update_blender(
    task_relpath: str,
    check_relpath: str,
    extra_additional: list[dict[str, Any]],
    text_artifacts: list[dict[str, str]],
    workspace_name: str,
) -> None:
    task = load_yaml(task_relpath)
    old_b64, payload = decode_blender_payload(check_relpath)

    by_path = {item["path"]: item for item in payload.get("additional", [])}
    for item in extra_additional:
        by_path[item["path"]] = item
    payload["additional"] = list(by_path.values())

    text_by_path = {item["path"]: item for item in payload.get("text_artifacts", [])}
    for item in text_artifacts:
        text_by_path[item["path"]] = item
    payload["text_artifacts"] = list(text_by_path.values())
    write_blender_payload(check_relpath, old_b64, payload)

    task["instruction"] = build_linux_style_blender_instruction(task, payload, workspace_name)

    metadata = task.setdefault("metadata", {})
    tags = list(metadata.get("tags") or [])
    for tag in ["extreme-hard", "multi_blend_network", "eleven_blend_files"]:
        if tag not in tags:
            tags.append(tag)
    metadata["tags"] = tags
    metadata["hard_plus_blender_requirement"] = (
        "primary scene plus ten derivative/composite/audit blend files; dependency graph and orchestration files "
        "must link second-stage and final audit blend files back to earlier blend files"
    )
    metadata["difficulty_alignment"] = "exceeds Linux Blender hard task by requiring an eleven-file multi-blend dependency network"
    metadata["human_steps"] = max(int(metadata.get("human_steps") or 0), 320)
    metadata["estimated_min_steps"] = max(int(metadata.get("estimated_min_steps") or 0), 290)
    limits = task.setdefault("limits", {})
    limits["max_steps"] = max(int(limits.get("max_steps") or 0), 220)
    dump_yaml(task_relpath, task)


def fmt_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return f"{value:.1f}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def fmt_xyz(values: list[Any] | tuple[Any, ...]) -> str:
    return f"X {fmt_number(values[0])}, Y {fmt_number(values[1])}, Z {fmt_number(values[2])}"


def render_sentence(render_spec: dict[str, Any], subject: str) -> str:
    pieces = [
        f"set {subject} render resolution to {render_spec['resolution_x']} by {render_spec['resolution_y']} at {render_spec['resolution_percentage']} percent scale",
        f"set the frame range to start at {render_spec['frame_start']} and end at {render_spec['frame_end']}",
        f"set the output path to {render_spec['filepath']}",
    ]
    if "fps" in render_spec:
        pieces.insert(1, f"set FPS to {render_spec['fps']}")
    return ", ".join(pieces)


def object_sentence(spec: dict[str, Any], *, prefix: str = "Set or create") -> str:
    name = spec["name"]
    clauses = [f"{prefix} {name}"]
    if "location" in spec:
        clauses.append(f"move {name} to {fmt_xyz(spec['location'])}")
    if "rotation_degrees" in spec:
        clauses.append(f"rotate {name} to {fmt_xyz(spec['rotation_degrees'])} degrees")
    if "scale" in spec:
        clauses.append(f"scale {name} to {fmt_xyz(spec['scale'])}")
    color = spec.get("material_diffuse_color")
    if color is not None:
        rgb = ", ".join(fmt_number(v) for v in color)
        clauses.append(f"set {name} diffuse material RGB to {rgb}")
    return ", ".join(clauses) + "."


def build_linux_style_blender_instruction(
    task: dict[str, Any],
    payload: dict[str, Any],
    workspace_name: str,
) -> str:
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    task_id = str(task.get("task_id") or "")
    if task_id.endswith("robot_tower_layout_scene"):
        task_label = "social render delivery"
    elif task_id.endswith("warehouse_blockout_scene"):
        task_label = "restage product delivery"
    else:
        task_label = "Blender delivery"

    primary_path = r"%s\product_stage.blend" % workspace_name
    lines = [
        f"In Blender, product_stage.blend is already open. Build the Linux-style {task_label}, but make the Windows version harder by producing an eleven-file multi-blend dependency network.",
        f"First update and save the primary scene as {primary_path}: {render_sentence(payload['primary_render'], 'product_stage.blend')}.",
        "Apply the primary scene object changes one by one using explicit X, Y, and Z values:",
    ]
    for spec in payload.get("objects", []):
        lines.append(object_sentence(spec))

    additional = list(payload.get("additional") or [])
    lines.append(
        "After saving the primary scene, create ten separate Blender delivery files from that scene. Each file must be saved as its own .blend file, and each one has its own render setup and object adjustments:"
    )
    for index, item in enumerate(additional, start=1):
        r = item["render"]
        lines.append(
            f"Delivery file {index}: save {item['path']}; {render_sentence(r, item['label'])}."
        )
        for spec in item.get("objects", []):
            lines.append(object_sentence(spec, prefix=f"In {item['label']}, adjust"))

    lines.append(
        "The final two blend files are composite/audit files. Treat them as downstream products that depend on earlier blend files, and make sure the dependency graph and orchestration files below record those links exactly."
    )
    lines.append("Create or overwrite these exact dependency and handoff text artifacts:")
    for artifact in payload.get("text_artifacts", []):
        lines.append(f"{artifact['path']} with exactly this content: {artifact['content']!r}.")

    supplemental_files = (
        ((task.get("evaluation") or {}).get("params") or {}).get("supplemental_checks") or {}
    ).get("files") or []
    if supplemental_files:
        lines.append("Also create these hard-plus verification files exactly:")
        for item in supplemental_files:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            exact = item.get("exact_text")
            if path and exact:
                lines.append(f"{path} with exactly this content: {exact!r}.")

    linux_peer = str(metadata.get("linux_peer") or "the matching Linux Blender hard task")
    lines.append(
        f"Do not finish until all eleven .blend files, all dependency text artifacts, and all hard-plus verification files exist. This Windows task intentionally exceeds {linux_peer} while using the same explicit X/Y/Z coordinate style."
    )
    return " ".join(lines)


REFERENCE_EXTRA = {
    "simple_count": 12,
    "collections": [
        "Distributed Systems Audit",
        "Benchmark Appendix",
        "Telemetry Deep Dive",
        "Threat Model Shelf",
        "Governance Archive",
        "Reliability Drill",
        "Networking Evidence",
        "Architecture Dispute",
        "Data Lineage Queue",
        "Locking Protocols",
        "Testing Artifacts",
        "Human Review Board",
    ],
    "titles": [
        "Spanner Design Notes",
        "Benchmark Evidence Ledger",
        "Telemetry Control Loops",
        "Threat Modeling Playbook",
        "Dataset Lineage Review",
        "Incident Command Drill",
        "QUIC Transport Notes",
        "Architecture Decision Records",
        "Data Provenance Audit",
        "Distributed Lock Review",
        "Regression Harness Appendix",
        "Operator Cognitive Load Study",
    ],
    "tags": [
        "spanner",
        "benchmark-evidence",
        "telemetry-control",
        "threat-modeling",
        "dataset-lineage",
        "incident-command",
        "quic",
        "architecture-record",
        "data-provenance",
        "distributed-lock-review",
        "regression-harness",
        "human-factors-review",
    ],
    "notes": [
        "Cross-check against Chubby lock service notes",
        "Tie evidence ledger to benchmark appendix",
        "Confirm telemetry loop ownership",
        "Escalate STRIDE coverage gaps",
        "Attach lineage notes to governance archive",
        "Use drill notes for reliability tabletop",
        "Compare transport behavior with networking shelf",
        "Record disputed tradeoff before final review",
        "Audit provenance before export lock",
        "Review lease timing against Queue Triage",
        "Pin regression harness evidence",
        "Use for operator load review",
    ],
    "files": {
        r"C:\Users\User\Documents\zotero_reference_extreme_batch_manifest.tsv": (
            "batch\tcollections\titems\tdepends_on\tstatus\n"
            "linux-core\t21\t21\tzotero_reference_handoff.tsv\tready\n"
            "extreme-audit\t12\t12\tzotero_reference_tag_audit.csv\tready\n"
            "dependency-lock\t33\t33\tzotero_reference_bundle_crosswalk.tsv\tlocked"
        ),
        r"C:\Users\User\Documents\zotero_reference_cross_export_map.csv": (
            "export,source,depends_on,status\n"
            "architecture-review,Architecture Shelf,zotero_reference_review_queue.txt,ready\n"
            "governance-review,Data Governance,zotero_reference_tag_audit.csv,ready\n"
            "distributed-lock-review,Queue Triage,zotero_reference_bundle_crosswalk.tsv,ready\n"
            "extreme-review,Distributed Systems Audit,zotero_reference_extreme_batch_manifest.tsv,locked"
        ),
        r"C:\Users\User\Documents\zotero_reference_dependency_ladder.tsv": (
            "level\tartifact\tparent\tstatus\n"
            "1\tzotero_reference_handoff.tsv\tzotero.sqlite\tchecked\n"
            "2\tzotero_reference_counts.txt\tzotero_reference_handoff.tsv\tchecked\n"
            "3\tzotero_reference_bundle_crosswalk.tsv\tzotero_reference_counts.txt\tchecked\n"
            "4\tzotero_reference_extreme_batch_manifest.tsv\tzotero_reference_bundle_crosswalk.tsv\tchecked\n"
            "5\tzotero_reference_final_extreme_lock.txt\tzotero_reference_extreme_batch_manifest.tsv\tlocked"
        ),
        r"C:\Users\User\Documents\zotero_reference_quality_gates.txt": (
            "gate_1=collections_33_visible\n"
            "gate_2=items_33_tagged\n"
            "gate_3=notes_31_reviewed\n"
            "gate_4=dependency_ladder_locked\n"
            "gate_5=final_export_ready"
        ),
        r"C:\Users\User\Documents\zotero_reference_final_extreme_lock.txt": (
            "database=zotero.sqlite\n"
            "core_collections=21\n"
            "extra_collections=12\n"
            "total_required_collections=33\n"
            "dependency_ladder=zotero_reference_dependency_ladder.tsv\n"
            "status=extreme-hard-plus-ready"
        ),
    },
}


RESEARCH_EXTRA = {
    "simple_count": 12,
    "collections": [
        "Transformer Audit",
        "Data Curation Lab",
        "Retrieval Evidence",
        "Safety Red Team",
        "Scaling Appendix",
        "Compression Audit",
        "Agent Tool Logs",
        "Long Context Evidence",
        "Optimizer Backtest",
        "Robustness Lab",
        "Interpretability Review Board",
        "Benchmark Lockbox",
    ],
    "titles": [
        "Transformer Mechanism Audit",
        "Dataset Curation Failure Modes",
        "RAG Evidence Ledger",
        "Red Teaming Language Models",
        "Scaling Law Caveats",
        "Distillation Compression Ledger",
        "Tool Use Trace Review",
        "Sparse Attention Evidence Pack",
        "Optimizer Backtest Memo",
        "Adversarial Robustness Ledger",
        "Circuit Review Minutes",
        "Benchmark Lockbox Manifest",
    ],
    "tags": [
        "transformer-audit",
        "data-curation",
        "rag-evidence",
        "safety-red-team",
        "scaling-caveat",
        "compression-audit",
        "tool-trace",
        "sparse-attention",
        "optimizer-backtest",
        "adversarial-ledger",
        "circuit-review",
        "benchmark-lockbox",
    ],
    "notes": [
        "Map attention heads to audit rows",
        "Check data curation assumptions",
        "Link retrieval evidence to RAG baseline",
        "Escalate red-team findings",
        "Separate compute scaling caveats",
        "Compare compression losses with baseline",
        "Review tool-use traces before final lock",
        "Attach sparse attention evidence",
        "Backtest optimizer defaults",
        "Tie robustness ledger to adversarial queue",
        "Review circuit minutes before export",
        "Lock benchmark package after audit",
    ],
    "files": {
        r"C:\Users\User\Documents\zotero_research_extreme_batch_manifest.tsv": (
            "batch\tcollections\titems\tdepends_on\tstatus\n"
            "linux-core\t22\t22\tzotero_research_handoff.tsv\tready\n"
            "extreme-audit\t12\t12\tzotero_research_tag_audit.csv\tready\n"
            "dependency-lock\t34\t34\tzotero_research_bundle_crosswalk.tsv\tlocked"
        ),
        r"C:\Users\User\Documents\zotero_research_cross_export_map.csv": (
            "export,source,depends_on,status\n"
            "compression-review,Compression Queue,zotero_research_review_queue.txt,ready\n"
            "agent-review,Agent Systems,zotero_research_tag_audit.csv,ready\n"
            "context-review,Long Context Queue,zotero_research_bundle_crosswalk.tsv,ready\n"
            "extreme-review,Transformer Audit,zotero_research_extreme_batch_manifest.tsv,locked"
        ),
        r"C:\Users\User\Documents\zotero_research_dependency_ladder.tsv": (
            "level\tartifact\tparent\tstatus\n"
            "1\tzotero_research_handoff.tsv\tzotero.sqlite\tchecked\n"
            "2\tzotero_research_counts.txt\tzotero_research_handoff.tsv\tchecked\n"
            "3\tzotero_research_bundle_crosswalk.tsv\tzotero_research_counts.txt\tchecked\n"
            "4\tzotero_research_extreme_batch_manifest.tsv\tzotero_research_bundle_crosswalk.tsv\tchecked\n"
            "5\tzotero_research_final_extreme_lock.txt\tzotero_research_extreme_batch_manifest.tsv\tlocked"
        ),
        r"C:\Users\User\Documents\zotero_research_quality_gates.txt": (
            "gate_1=collections_34_visible\n"
            "gate_2=items_34_tagged\n"
            "gate_3=notes_34_reviewed\n"
            "gate_4=dependency_ladder_locked\n"
            "gate_5=final_export_ready"
        ),
        r"C:\Users\User\Documents\zotero_research_final_extreme_lock.txt": (
            "database=zotero.sqlite\n"
            "core_collections=22\n"
            "extra_collections=12\n"
            "total_required_collections=34\n"
            "dependency_ladder=zotero_research_dependency_ladder.tsv\n"
            "status=extreme-hard-plus-ready"
        ),
    },
}


REFERENCE_LABYRINTH = [
    (
        ["Reference Shelf", "Reference Audit Spine", "Spanner Evidence Lock"],
        "Reference Audit Spine Index",
        "Spanner Evidence Lockfile",
        "path-reference-spine",
        "path-spanner-lock",
        "Index the reference audit branch before opening the Spanner lockfile",
        "Tie Spanner evidence back to Reference Shelf and Queue Triage before final export",
    ),
    (
        ["Queue Triage", "Lock Queue Spine", "Lease Timing Exceptions"],
        "Lock Queue Spine Index",
        "Lease Timing Exception Ledger",
        "path-lock-spine",
        "path-lease-exception",
        "Index lock queue dependencies before checking Chubby leases",
        "Compare lease timing against Queue Triage and Locking Protocols",
    ),
    (
        ["Architecture Shelf", "Architecture Conflict Spine", "ADR Conflict Matrix"],
        "Architecture Conflict Spine Index",
        "ADR Conflict Matrix",
        "path-architecture-spine",
        "path-adr-conflict",
        "Index architecture conflicts before final ADR review",
        "Resolve ADR conflicts against Software Architecture: The Hard Parts",
    ),
    (
        ["Data Governance", "Governance Evidence Spine", "Lineage Provenance Pack"],
        "Governance Evidence Spine Index",
        "Lineage Provenance Pack",
        "path-governance-spine",
        "path-lineage-pack",
        "Index governance evidence before lineage review",
        "Attach provenance evidence to Dataset Documentation Plan",
    ),
    (
        ["Evidence Queue", "Benchmark Evidence Spine", "Evidence Ledger Crosscheck"],
        "Benchmark Evidence Spine Index",
        "Evidence Ledger Crosscheck",
        "path-benchmark-spine",
        "path-evidence-crosscheck",
        "Index benchmark evidence before ledger crosscheck",
        "Cross-check latency evidence against Benchmark Appendix",
    ),
    (
        ["Observability Shelf", "Telemetry Control Spine", "Control Loop Ownership"],
        "Telemetry Control Spine Index",
        "Control Loop Ownership Ledger",
        "path-telemetry-spine",
        "path-control-loop",
        "Index telemetry control loops before assigning ownership",
        "Confirm owner for every telemetry loop before export lock",
    ),
    (
        ["Security Review", "Threat Review Spine", "STRIDE Gap Register"],
        "Threat Review Spine Index",
        "STRIDE Gap Register",
        "path-threat-spine",
        "path-stride-gap",
        "Index threat review branches before STRIDE gap triage",
        "Escalate STRIDE gaps against Security Engineering",
    ),
    (
        ["Operations Reading", "Reliability Tabletop Spine", "Incident Tabletop Pack"],
        "Reliability Tabletop Spine Index",
        "Incident Tabletop Pack",
        "path-reliability-spine",
        "path-tabletop-pack",
        "Index reliability tabletop steps before incident drill",
        "Bind tabletop notes to Site Reliability Engineering",
    ),
    (
        ["Networking Queue", "Transport Evidence Spine", "QUIC Transport Appendix"],
        "Transport Evidence Spine Index",
        "QUIC Transport Appendix",
        "path-transport-spine",
        "path-quic-appendix",
        "Index transport evidence before QUIC appendix review",
        "Compare QUIC appendix with networking shelf evidence",
    ),
    (
        ["Testing Queue", "Harness Evidence Spine", "Harness Regression Lock"],
        "Harness Evidence Spine Index",
        "Harness Regression Lock",
        "path-harness-spine",
        "path-regression-lock",
        "Index harness evidence before regression lock",
        "Pin regression lock to Evaluation Harness Notes",
    ),
    (
        ["Human Factors", "Review Board Spine", "Cognitive Load Review"],
        "Review Board Spine Index",
        "Cognitive Load Review Dossier",
        "path-human-spine",
        "path-cognitive-review",
        "Index review board evidence before load review",
        "Cross-check cognitive load review with Operator Playbook",
    ),
    (
        ["Storage Queue", "Storage Provenance Spine", "Storage Provenance Exceptions"],
        "Storage Provenance Spine Index",
        "Storage Provenance Exceptions",
        "path-storage-spine",
        "path-storage-provenance",
        "Index storage provenance before exception review",
        "Attach storage exceptions to Database Internals evidence",
    ),
]


RESEARCH_LABYRINTH = [
    (
        ["Research", "Transformer Mechanism Spine", "Attention Head Ledger"],
        "Transformer Mechanism Spine Index",
        "Attention Head Ledger",
        "path-transformer-spine",
        "path-attention-ledger",
        "Index transformer mechanism evidence before attention audit",
        "Map attention heads back to Attention Is All You Need",
    ),
    (
        ["Data Queue", "Curation Failure Spine", "Deduplication Failure Ledger"],
        "Curation Failure Spine Index",
        "Deduplication Failure Ledger",
        "path-curation-spine",
        "path-dedup-ledger",
        "Index curation failure modes before dedup review",
        "Check deduplication failures against data validation notes",
    ),
    (
        ["Retrieval Queue", "Retrieval Failure Spine", "RAG Failure Case Ledger"],
        "Retrieval Failure Spine Index",
        "RAG Failure Case Ledger",
        "path-retrieval-spine",
        "path-rag-failure",
        "Index retrieval failures before RAG ledger review",
        "Link RAG failures back to retrieval baseline evidence",
    ),
    (
        ["Safety Queue", "Red Team Spine", "Red Team Escalation Lock"],
        "Red Team Spine Index",
        "Red Team Escalation Lock",
        "path-red-team-spine",
        "path-escalation-lock",
        "Index safety red-team evidence before escalation",
        "Escalate red-team lock against safety queue evidence",
    ),
    (
        ["Scaling Queue", "Scaling Caveat Spine", "Compute Frontier Caveats"],
        "Scaling Caveat Spine Index",
        "Compute Frontier Caveats",
        "path-scaling-spine",
        "path-compute-frontier",
        "Index scaling caveats before compute frontier review",
        "Separate compute frontier caveats from Scaling Laws",
    ),
    (
        ["Compression Queue", "Compression Delta Spine", "Distillation Delta Ledger"],
        "Compression Delta Spine Index",
        "Distillation Delta Ledger",
        "path-compression-spine",
        "path-distillation-delta",
        "Index compression deltas before distillation review",
        "Compare distillation deltas with compression baseline",
    ),
    (
        ["Agent Systems", "Tool Trace Spine", "Tool Trace Exception Board"],
        "Tool Trace Spine Index",
        "Tool Trace Exception Board",
        "path-tool-trace-spine",
        "path-tool-exception",
        "Index tool traces before exception review",
        "Review tool trace exceptions before benchmark lock",
    ),
    (
        ["Long Context Queue", "Context Window Spine", "Window Regression Ledger"],
        "Context Window Spine Index",
        "Window Regression Ledger",
        "path-context-spine",
        "path-window-regression",
        "Index context-window evidence before regression review",
        "Bind regression ledger to Longformer sparse attention evidence",
    ),
    (
        ["Optimization Queue", "Optimizer Evidence Spine", "AdamW Baseline Delta"],
        "Optimizer Evidence Spine Index",
        "AdamW Baseline Delta",
        "path-optimizer-spine",
        "path-adamw-delta",
        "Index optimizer evidence before AdamW comparison",
        "Backtest AdamW delta against optimizer defaults",
    ),
    (
        ["Robustness Queue", "Attack Surface Spine", "Attack Surface Register"],
        "Attack Surface Spine Index",
        "Attack Surface Register",
        "path-attack-spine",
        "path-attack-register",
        "Index robustness evidence before attack register review",
        "Tie attack surface register to adversarial examples",
    ),
    (
        ["Interpretability Queue", "Circuit Dispute Spine", "Circuit Dispute Ledger"],
        "Circuit Dispute Spine Index",
        "Circuit Dispute Ledger",
        "path-circuit-spine",
        "path-circuit-dispute",
        "Index interpretability disputes before circuit review",
        "Review circuit dispute ledger before export lock",
    ),
    (
        ["Benchmark Queue", "Benchmark Release Spine", "Release Gate Lock"],
        "Benchmark Release Spine Index",
        "Release Gate Lock",
        "path-release-spine",
        "path-release-lock",
        "Index benchmark release evidence before final gate",
        "Lock release gate after benchmark evidence review",
    ),
]


def expand_zotero_labyrinth(
    extra: dict[str, Any],
    entries: list[tuple[list[str], str, str, str, str, str, str]],
    *,
    prefix: str,
    core_collections: int,
    core_notes: int,
) -> int:
    collection_values = list(extra["collections"])
    title_values = list(extra["titles"])
    tag_values = list(extra["tags"])
    note_values = list(extra["notes"])
    collection_paths = list(extra.get("collection_paths") or [])

    matrix_lines = ["path\tintermediate_item\tleaf_item\tstatus"]
    graph_lines = ["source_path\tdepends_on_file\tlock"]
    for path, mid_title, leaf_title, mid_tag, leaf_tag, mid_note, leaf_note in entries:
        for collection in path[1:]:
            if collection not in collection_values:
                collection_values.append(collection)
        for title in [mid_title, leaf_title]:
            if title not in title_values:
                title_values.append(title)
        for tag in [mid_tag, leaf_tag]:
            if tag not in tag_values:
                tag_values.append(tag)
        for note in [mid_note, leaf_note]:
            if note not in note_values:
                note_values.append(note)
        path_text = " > ".join(path)
        if path_text not in collection_paths:
            collection_paths.append(path_text)
        matrix_lines.append(f"{path_text}\t{mid_title}\t{leaf_title}\tlocked")
        graph_lines.append(f"{path_text}\t{prefix}_hierarchy_path_matrix.tsv\tlocked")

    extra["collections"] = collection_values
    extra["titles"] = title_values
    extra["tags"] = tag_values
    extra["notes"] = note_values
    extra["collection_paths"] = collection_paths
    extra["labyrinth_entries"] = entries

    total_collections = core_collections + len(collection_values)
    total_items = core_collections + len(title_values)
    total_notes = core_notes + len(note_values)
    extra_count = len(collection_values)
    extra["files"].update(
        {
            rf"C:\Users\User\Documents\{prefix}_hierarchy_path_matrix.tsv": "\n".join(matrix_lines),
            rf"C:\Users\User\Documents\{prefix}_cross_collection_dependency_graph.tsv": "\n".join(graph_lines),
            rf"C:\Users\User\Documents\{prefix}_final_labyrinth_lock.txt": (
                "database=zotero.sqlite\n"
                f"core_collections={core_collections}\n"
                f"extra_collections={extra_count}\n"
                f"total_required_collections={total_collections}\n"
                f"total_required_items={total_items}\n"
                f"hierarchy_paths={len(collection_paths)}\n"
                f"path_matrix={prefix}_hierarchy_path_matrix.tsv\n"
                "status=labyrinth-hard-plus-ready"
            ),
        }
    )
    extra["files"][rf"C:\Users\User\Documents\{prefix}_extreme_batch_manifest.tsv"] = (
        "batch\tcollections\titems\tdepends_on\tstatus\n"
        f"linux-core\t{core_collections}\t{core_collections}\t{prefix}_handoff.tsv\tready\n"
        f"flat-extreme\t12\t12\t{prefix}_tag_audit.csv\tready\n"
        f"nested-labyrinth\t{extra_count - 12}\t{len(title_values) - 12}\t{prefix}_hierarchy_path_matrix.tsv\tlocked\n"
        f"dependency-lock\t{total_collections}\t{total_items}\t{prefix}_bundle_crosswalk.tsv\tlocked"
    )
    extra["files"][rf"C:\Users\User\Documents\{prefix}_dependency_ladder.tsv"] = (
        "level\tartifact\tparent\tstatus\n"
        f"1\t{prefix}_handoff.tsv\tzotero.sqlite\tchecked\n"
        f"2\t{prefix}_counts.txt\t{prefix}_handoff.tsv\tchecked\n"
        f"3\t{prefix}_bundle_crosswalk.tsv\t{prefix}_counts.txt\tchecked\n"
        f"4\t{prefix}_hierarchy_path_matrix.tsv\t{prefix}_bundle_crosswalk.tsv\tchecked\n"
        f"5\t{prefix}_cross_collection_dependency_graph.tsv\t{prefix}_hierarchy_path_matrix.tsv\tchecked\n"
        f"6\t{prefix}_final_labyrinth_lock.txt\t{prefix}_cross_collection_dependency_graph.tsv\tlocked"
    )
    extra["files"][rf"C:\Users\User\Documents\{prefix}_quality_gates.txt"] = (
        f"gate_1=collections_{total_collections}_visible\n"
        f"gate_2=items_{total_items}_tagged\n"
        f"gate_3=notes_{total_notes}_reviewed\n"
        f"gate_4=hierarchy_paths_{len(collection_paths)}_locked\n"
        "gate_5=final_export_ready"
    )
    extra["files"][rf"C:\Users\User\Documents\{prefix}_final_extreme_lock.txt"] = (
        "database=zotero.sqlite\n"
        f"core_collections={core_collections}\n"
        f"extra_collections={extra_count}\n"
        f"total_required_collections={total_collections}\n"
        f"total_required_items={total_items}\n"
        f"dependency_ladder={prefix}_dependency_ladder.tsv\n"
        "status=labyrinth-hard-plus-ready"
    )
    return total_collections


REFERENCE_TOTAL_COLLECTIONS = expand_zotero_labyrinth(
    REFERENCE_EXTRA,
    REFERENCE_LABYRINTH,
    prefix="zotero_reference",
    core_collections=21,
    core_notes=19,
)
RESEARCH_TOTAL_COLLECTIONS = expand_zotero_labyrinth(
    RESEARCH_EXTRA,
    RESEARCH_LABYRINTH,
    prefix="zotero_research",
    core_collections=22,
    core_notes=22,
)


def decode_zotero_expected(check_relpath: str) -> tuple[str, dict[str, Any]]:
    text = (ROOT / check_relpath).read_text(encoding="utf-8")
    match = re.search(r"expected = json\.loads\((?P<literal>'(?:\\.|[^'])*')\)", text)
    if not match:
        raise RuntimeError(f"Missing Zotero expected payload in {check_relpath}")
    return match.group("literal"), json.loads(ast.literal_eval(match.group("literal")))


def write_zotero_expected(check_relpath: str, old_literal: str, payload: dict[str, Any]) -> None:
    text = (ROOT / check_relpath).read_text(encoding="utf-8")
    json_text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    new_literal = repr(json_text)
    (ROOT / check_relpath).write_text(text.replace(old_literal, new_literal, 1), encoding="utf-8")


def update_zotero(task_relpath: str, check_relpath: str, extra: dict[str, Any], total_collections: int) -> None:
    task = load_yaml(task_relpath)
    old_literal, payload = decode_zotero_expected(check_relpath)
    for key in ["collections", "titles", "tags", "notes"]:
        values = list(payload.get(key) or [])
        for value in extra[key]:
            if value not in values:
                values.append(value)
        payload[key] = values
    path_values = list(payload.get("collection_paths") or [])
    for value in extra.get("collection_paths") or []:
        if value not in path_values:
            path_values.append(value)
    if path_values:
        payload["collection_paths"] = path_values
    files = dict(payload.get("files") or {})
    files.update(extra["files"])
    payload["files"] = files
    write_zotero_expected(check_relpath, old_literal, payload)

    params = task.setdefault("evaluation", {}).setdefault("params", {})
    supplemental = params.setdefault("supplemental_checks", {})
    supplemental_files = list(supplemental.get("files") or [])
    by_path = {item.get("path"): item for item in supplemental_files if isinstance(item, dict)}
    for path, content in extra["files"].items():
        by_path[path] = {"path": path, "exact_text": content}
    supplemental["files"] = list(by_path.values())

    marker = "EXTREME ZOTERO ADDENDUM:"
    base_instruction = str(task.get("instruction") or "").split(marker)[0].rstrip()
    simple_count = int(extra.get("simple_count") or len(extra["titles"]))
    total_items = len(payload.get("titles") or [])
    addendum = [
        marker,
        (
            f"Before finishing, expand the Zotero library to {total_collections} required collections "
            f"and {total_items} required item titles."
        ),
    ]
    for collection, title, tag, note in zip(
        extra["collections"][:simple_count],
        extra["titles"][:simple_count],
        extra["tags"][:simple_count],
        extra["notes"][:simple_count],
    ):
        addendum.append(
            f'Create collection "{collection}", add a manual item titled "{title}", tag it "{tag}", '
            f'and add a child note containing "{note}".'
        )
    labyrinth_entries = list(extra.get("labyrinth_entries") or [])
    if labyrinth_entries:
        addendum.append(
            "Now add the nested hierarchy layer. These must be real child collections, not flat collections under My Library. "
            "For every path, create the middle collection under the named root collection, then create the leaf collection "
            "under that middle collection."
        )
        for path, mid_title, leaf_title, mid_tag, leaf_tag, mid_note, leaf_note in labyrinth_entries:
            path_text = " > ".join(path)
            addendum.append(
                f'Create nested collection path "{path_text}". In the middle collection "{path[1]}", add a manual Report '
                f'titled "{mid_title}", tag it "{mid_tag}", and add a child note containing "{mid_note}". In the leaf '
                f'collection "{path[2]}", add a manual Report titled "{leaf_title}", tag it "{leaf_tag}", and add a child '
                f'note containing "{leaf_note}".'
            )
    addendum.append("Then create these exact extra dependency/export files:")
    for path, content in extra["files"].items():
        addendum.append(f"{path} with exactly this content: {content!r}.")
    task["instruction"] = base_instruction + " " + " ".join(addendum)

    metadata = task.setdefault("metadata", {})
    tags = list(metadata.get("tags") or [])
    for tag in ["extreme-hard", "multi_batch_zotero", "dependency_export_network", "nested_collection_hierarchy"]:
        if tag not in tags:
            tags.append(tag)
    metadata["tags"] = tags
    metadata["description"] = (
        f"Extreme Zotero hard task with {total_collections} collections, {total_items} item titles, nested collection paths, and exact dependency/export files."
    )
    metadata["difficulty_alignment"] = (
        "exceeds Linux Zotero hard task by adding a second batch of collections/items, real nested collection paths, and a multi-file export dependency network"
    )
    metadata["human_steps"] = max(int(metadata.get("human_steps") or 0), 650)
    metadata["estimated_min_steps"] = max(int(metadata.get("estimated_min_steps") or 0), 560)
    limits = task.setdefault("limits", {})
    limits["max_steps"] = max(int(limits.get("max_steps") or 0), 360)
    dump_yaml(task_relpath, task)


def main() -> None:
    update_blender(
        "tasks/windows/blender_robot_tower_layout_scene.yaml",
        "evaluators/windows/checks/blender_robot_tower_layout_scene.ps1",
        SOCIAL_EXTREME_ADDITIONAL,
        social_text_artifacts(),
        r"C:\Users\User\Documents\blender_tasks\blender_social_render",
    )
    update_blender(
        "tasks/windows/blender_warehouse_blockout_scene.yaml",
        "evaluators/windows/checks/blender_warehouse_blockout_scene.ps1",
        RESTAGE_EXTREME_ADDITIONAL,
        restage_text_artifacts(),
        r"C:\Users\User\Documents\blender_tasks\blender_restage_product",
    )
    update_zotero(
        "tasks/windows/zotero_organize_library.yaml",
        "evaluators/windows/checks/zotero_organize_library.ps1",
        REFERENCE_EXTRA,
        REFERENCE_TOTAL_COLLECTIONS,
    )
    update_zotero(
        "tasks/windows/zotero_create_collection_with_notes.yaml",
        "evaluators/windows/checks/zotero_create_collection_with_notes.ps1",
        RESEARCH_EXTRA,
        RESEARCH_TOTAL_COLLECTIONS,
    )
    print("extreme-hardened Windows Blender and Zotero tasks")


if __name__ == "__main__":
    main()
