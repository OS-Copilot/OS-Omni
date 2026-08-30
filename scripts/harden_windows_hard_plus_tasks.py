from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


TARGET_TASKS = [
    "tasks/windows/blender_robot_tower_layout_scene.yaml",
    "tasks/windows/blender_warehouse_blockout_scene.yaml",
    "tasks/windows/deltachat_create_launch_debrief_from_existing_chats.yaml",
    "tasks/windows/deltachat_share_sync_time_with_avery_and_project_updates.yaml",
    "tasks/windows/drawio_ellipse_vertical_divider_styled.yaml",
    "tasks/windows/drawio_sum_loop_flowchart.yaml",
    "tasks/windows/gimp_apple_and_orange_focus_blur_bw_upside_down.yaml",
    "tasks/windows/gimp_cartoon_girl_bottom_left_blend_flip_opacity.yaml",
    "tasks/windows/impress_animation_transition.yaml",
    "tasks/windows/impress_slide_shape_bold.yaml",
    "tasks/windows/notepad_append_text.yaml",
    "tasks/windows/notepad_edit_config.yaml",
    "tasks/windows/openshop_add_headphones_to_cart.yaml",
    "tasks/windows/openshop_checkout_two_items.yaml",
    "tasks/windows/spotube_album_queue_light_english_playlist_repeat.yaml",
    "tasks/windows/spotube_one_ok_rock_queue_single_repeat_pause.yaml",
    "tasks/windows/thunderbird_collect_st_club_progress.yaml",
    "tasks/windows/thunderbird_send_email_exact_body.yaml",
    "tasks/windows/vscode_ops_handoff_workspace.yaml",
    "tasks/windows/vscode_release_cleanup_workspace.yaml",
    "tasks/windows/wireshark_advanced_filter_export.yaml",
    "tasks/windows/wireshark_statistics_report.yaml",
    "tasks/windows/writer_headings_list_pagebreak.yaml",
    "tasks/windows/writer_toc_image_footnote.yaml",
    "tasks/windows/zotero_create_collection_with_notes.yaml",
    "tasks/windows/zotero_organize_library.yaml",
    "tasks/windows/cross_app_openshop_calendar_checkout_coffee_followup_hard.yaml",
    "tasks/windows/cross_app_openshop_calendar_dual_item_checkout_two_events_hard.yaml",
    "tasks/windows/cross_app_writer_thunderbird_attach_source_and_pdf_send_hard.yaml",
    "tasks/windows/cross_app_writer_thunderbird_save_copy_export_attach_send_hard.yaml",
]


BLENDER_EXTRAS = {
    "windows.blender.robot_tower_layout_scene": {
        "check": "evaluators/windows/checks/blender_robot_tower_layout_scene.ps1",
        "insert_before": "Create these exact text deliverables:",
        "artifact_replacements": [
            {
                "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_delivery_crosswalk.tsv",
                "old": (
                    "file\trole\tresolution\tlinked_object\n"
                    "product_stage.blend\tprimary\t1800x1000\tFeatureCube\n"
                    "social_review_closeup.blend\tcloseup\t1200x1200\tProofDot\n"
                    "social_archive_wide.blend\tarchive\t2200x1200\tTopRule\n"
                    "social_story_crop.blend\tstory\t1080x1920\tCaptionBar"
                ),
                "new": (
                    "file\trole\tresolution\tlinked_object\n"
                    "product_stage.blend\tprimary\t1800x1000\tFeatureCube\n"
                    "social_review_closeup.blend\tcloseup\t1200x1200\tProofDot\n"
                    "social_archive_wide.blend\tarchive\t2200x1200\tTopRule\n"
                    "social_story_crop.blend\tstory\t1080x1920\tCaptionBar\n"
                    "social_dependency_audit.blend\tdependency\t1600x900\tHeroPin"
                ),
            },
            {
                "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_render_bundle_index.txt",
                "old": (
                    "primary=product_stage.blend\n"
                    "derivatives=social_review_closeup.blend|social_archive_wide.blend|social_story_crop.blend\n"
                    "shared_workspace=blender_social_render\n"
                    "handoff_status=ready"
                ),
                "new": (
                    "primary=product_stage.blend\n"
                    "derivatives=social_review_closeup.blend|social_archive_wide.blend|social_story_crop.blend|social_dependency_audit.blend\n"
                    "shared_workspace=blender_social_render\n"
                    "multi_blend_dependency=social_review_closeup.blend|social_story_crop.blend->social_dependency_audit.blend\n"
                    "handoff_status=ready"
                ),
            },
        ],
        "blend": {
            "label": "dependency",
            "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_dependency_audit.blend",
            "render": {
                "resolution_x": 1600,
                "resolution_y": 900,
                "resolution_percentage": 100,
                "frame_start": 96,
                "frame_end": 144,
                "filepath": "//renders/social_dependency_audit.png",
            },
            "objects": [
                {"name": "Camera", "location": [6.1, -6.0, 5.2], "rotation_degrees": [63, 0, 43]},
                {"name": "HeroPin", "location": [2.45, 0.35, 0.72]},
                {"name": "LowerGuide", "scale": [2.65, 0.09, 1.0]},
            ],
        },
        "instruction": (
            r"Also create C:\Users\User\Documents\blender_tasks\blender_social_render\social_dependency_audit.blend "
            "from the saved primary scene: render 1600 by 900 at 100 percent, frame range 96 to 144, "
            "output path //renders/social_dependency_audit.png; object adjustments: "
            '{"name": "Camera", "location": [6.1, -6.0, 5.2], "rotation_degrees": [63, 0, 43]} '
            '{"name": "HeroPin", "location": [2.45, 0.35, 0.72]} '
            '{"name": "LowerGuide", "scale": [2.65, 0.09, 1.0]}. '
        ),
        "text_artifacts": [
            {
                "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_blend_dependency_graph.tsv",
                "content": (
                    "blend\tdepends_on\tpurpose\n"
                    "social_review_closeup.blend\tproduct_stage.blend\tcloseup-proof\n"
                    "social_archive_wide.blend\tproduct_stage.blend\tarchive-context\n"
                    "social_story_crop.blend\tproduct_stage.blend\tvertical-story\n"
                    "social_dependency_audit.blend\tsocial_review_closeup.blend|social_story_crop.blend\tcross-file-audit"
                ),
            },
            {
                "path": r"C:\Users\User\Documents\blender_tasks\blender_social_render\social_blend_orchestration_index.txt",
                "content": (
                    "primary=product_stage.blend\n"
                    "blend_file_count=5\n"
                    "required_dependency=social_dependency_audit.blend\n"
                    "audit_chain=social_review_closeup.blend|social_story_crop.blend|social_dependency_audit.blend\n"
                    "handoff_status=hard-plus-ready"
                ),
            },
        ],
    },
    "windows.blender.warehouse_blockout_scene": {
        "check": "evaluators/windows/checks/blender_warehouse_blockout_scene.ps1",
        "insert_before": "Create these exact text deliverables:",
        "artifact_replacements": [
            {
                "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_delivery_crosswalk.tsv",
                "old": (
                    "file\trole\tresolution\tlinked_object\n"
                    "product_stage.blend\tprimary\t1536x1080\tFeatureCube\n"
                    "restage_review_closeup.blend\tcloseup\t1280x960\tVariancePin\n"
                    "restage_archive_wide.blend\tarchive\t2048x1152\tBaselineRail\n"
                    "restage_qa_isolation.blend\tqa\t1440x1440\tReviewPost"
                ),
                "new": (
                    "file\trole\tresolution\tlinked_object\n"
                    "product_stage.blend\tprimary\t1536x1080\tFeatureCube\n"
                    "restage_review_closeup.blend\tcloseup\t1280x960\tVariancePin\n"
                    "restage_archive_wide.blend\tarchive\t2048x1152\tBaselineRail\n"
                    "restage_qa_isolation.blend\tqa\t1440x1440\tReviewPost\n"
                    "restage_dependency_audit.blend\tdependency\t1920x1080\tTensionSphere"
                ),
            },
            {
                "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_render_bundle_index.txt",
                "old": (
                    "primary=product_stage.blend\n"
                    "derivatives=restage_review_closeup.blend|restage_archive_wide.blend|restage_qa_isolation.blend\n"
                    "shared_workspace=blender_restage_product\n"
                    "handoff_status=ready"
                ),
                "new": (
                    "primary=product_stage.blend\n"
                    "derivatives=restage_review_closeup.blend|restage_archive_wide.blend|restage_qa_isolation.blend|restage_dependency_audit.blend\n"
                    "shared_workspace=blender_restage_product\n"
                    "multi_blend_dependency=restage_review_closeup.blend|restage_qa_isolation.blend->restage_dependency_audit.blend\n"
                    "handoff_status=ready"
                ),
            },
        ],
        "blend": {
            "label": "dependency",
            "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_dependency_audit.blend",
            "render": {
                "resolution_x": 1920,
                "resolution_y": 1080,
                "resolution_percentage": 100,
                "frame_start": 45,
                "frame_end": 135,
                "filepath": "//renders/restage_dependency_audit.png",
            },
            "objects": [
                {"name": "Camera", "location": [6.4, -6.6, 5.6], "rotation_degrees": [60, 0, 45]},
                {"name": "TensionSphere", "location": [0.35, 2.35, 0.62]},
                {"name": "BaselineRail", "scale": [2.45, 0.12, 0.28]},
            ],
        },
        "instruction": (
            r"Also create C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_dependency_audit.blend "
            "from the saved primary scene: render 1920 by 1080 at 100 percent, frame range 45 to 135, "
            "output path //renders/restage_dependency_audit.png; object adjustments: "
            '{"name": "Camera", "location": [6.4, -6.6, 5.6], "rotation_degrees": [60, 0, 45]} '
            '{"name": "TensionSphere", "location": [0.35, 2.35, 0.62]} '
            '{"name": "BaselineRail", "scale": [2.45, 0.12, 0.28]}. '
        ),
        "text_artifacts": [
            {
                "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_blend_dependency_graph.tsv",
                "content": (
                    "blend\tdepends_on\tpurpose\n"
                    "restage_review_closeup.blend\tproduct_stage.blend\tcloseup-proof\n"
                    "restage_archive_wide.blend\tproduct_stage.blend\tarchive-context\n"
                    "restage_qa_isolation.blend\tproduct_stage.blend\tqa-isolation\n"
                    "restage_dependency_audit.blend\trestage_review_closeup.blend|restage_qa_isolation.blend\tcross-file-audit"
                ),
            },
            {
                "path": r"C:\Users\User\Documents\blender_tasks\blender_restage_product\restage_blend_orchestration_index.txt",
                "content": (
                    "primary=product_stage.blend\n"
                    "blend_file_count=5\n"
                    "required_dependency=restage_dependency_audit.blend\n"
                    "audit_chain=restage_review_closeup.blend|restage_qa_isolation.blend|restage_dependency_audit.blend\n"
                    "handoff_status=hard-plus-ready"
                ),
            },
        ],
    },
}


ZOTERO_MULTI_FILE_AUDITS = {
    "windows.zotero.organize_library": {
        "path": r"C:\Users\User\Documents\zotero_reference_multifile_dependency_audit.tsv",
        "exact_text": (
            "file\tuses\tstatus\n"
            "zotero_reference_counts.txt\tzotero_reference_handoff.tsv\tchecked\n"
            "zotero_reference_review_queue.txt\tzotero_reference_counts.txt\tchecked\n"
            "zotero_reference_tag_audit.csv\tzotero_reference_review_queue.txt\tchecked\n"
            "zotero_reference_final_index.txt\tzotero_reference_bundle_crosswalk.tsv\tchecked"
        ),
    },
    "windows.zotero.create_collection_with_notes": {
        "path": r"C:\Users\User\Documents\zotero_research_multifile_dependency_audit.tsv",
        "exact_text": (
            "file\tuses\tstatus\n"
            "zotero_research_counts.txt\tzotero_research_handoff.tsv\tchecked\n"
            "zotero_research_review_queue.txt\tzotero_research_counts.txt\tchecked\n"
            "zotero_research_tag_audit.csv\tzotero_research_review_queue.txt\tchecked\n"
            "zotero_research_final_index.txt\tzotero_research_bundle_crosswalk.tsv\tchecked"
        ),
    },
}


def load_yaml(relpath: str) -> dict[str, Any]:
    with (ROOT / relpath).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{relpath} is not a YAML mapping")
    return data


def dump_yaml(relpath: str, data: dict[str, Any]) -> None:
    (ROOT / relpath).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


def safe_task_label(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id).replace(".", "_").strip("_")


def supplemental_files(task: dict[str, Any]) -> list[dict[str, str]]:
    task_id = str(task.get("task_id") or "").strip()
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    linux_peer = str(metadata.get("linux_peer") or metadata.get("linux_peer_file") or "linux_peer_unset")
    app = str(metadata.get("app_name") or metadata.get("app") or "unknown")
    label = safe_task_label(task_id)
    root = rf"C:\Users\User\Documents\helloworld_hard_plus\{label}"
    files = [
        {
            "path": rf"{root}\hard_plus_handoff.tsv",
            "exact_text": (
                "task_id\tlinux_peer\tstatus\n"
                f"{task_id}\t{linux_peer}\thard-plus-ready\n"
                f"app\t{app}\tevaluator-checked"
            ),
        },
        {
            "path": rf"{root}\hard_plus_dependency_index.txt",
            "exact_text": (
                f"primary_task={task_id}\n"
                f"linux_peer={linux_peer}\n"
                "difficulty=hard-plus\n"
                "requires_multi_artifact_handoff=true\n"
                "oracle_receipt=hard_plus_oracle_receipt.txt"
            ),
        },
        {
            "path": rf"{root}\hard_plus_review_matrix.csv",
            "exact_text": (
                "check,owner,status\n"
                "linux_alignment,benchmark-ops,ready\n"
                "extra_artifacts,benchmark-ops,ready\n"
                "oracle_recheck,benchmark-ops,required"
            ),
        },
    ]
    audit = ZOTERO_MULTI_FILE_AUDITS.get(task_id)
    if audit:
        files.append(audit)
    return files


def append_hard_plus_instruction(task: dict[str, Any], files: list[dict[str, str]]) -> None:
    text = str(task.get("instruction") or "").strip()
    missing = [item for item in files if item["path"] not in text]
    if not missing:
        return
    file_parts = []
    for item in missing:
        file_parts.append(f'{item["path"]} with exactly this content: {item["exact_text"]!r}')
    if "hard-plus verification files" in text:
        label = " Also create these additional hard-plus verification files: "
    else:
        label = " Also create these hard-plus verification files so the final state is a multi-artifact handoff bundle: "
    addition = (
        label
        + "; ".join(file_parts)
        + "."
    )
    task["instruction"] = text + addition


def update_metadata(task: dict[str, Any]) -> None:
    metadata = task.setdefault("metadata", {})
    tags = list(metadata.get("tags") or [])
    already_hard_plus = "hard-plus" in tags
    for tag in ["hard-plus", "multi_artifact_handoff", "linux_plus"]:
        if tag not in tags:
            tags.append(tag)
    metadata["tags"] = tags
    metadata["hard_plus_alignment"] = "linux_peer_plus_extra_evaluator_checked_artifacts"
    metadata["hard_plus_note"] = (
        "The Linux-aligned core task remains required; extra handoff/audit artifacts are also evaluator checked."
    )
    metadata["oracle_model"] = "windows_oracle"
    human_steps = int(metadata.get("human_steps") or metadata.get("estimated_min_steps") or 0)
    if human_steps and not already_hard_plus:
        metadata["human_steps"] = max(human_steps + 18, human_steps)
    estimated = int(metadata.get("estimated_min_steps") or 0)
    if estimated and not already_hard_plus:
        metadata["estimated_min_steps"] = max(estimated + 15, estimated)
    limits = task.setdefault("limits", {})
    limits["max_steps"] = max(int(limits.get("max_steps") or 100), 120)


def add_supplemental_checks(task: dict[str, Any], files: list[dict[str, str]]) -> None:
    params = task.setdefault("evaluation", {}).setdefault("params", {})
    supplemental = params.setdefault("supplemental_checks", {})
    supplemental["files"] = files


def decode_blender_expected(check_relpath: str) -> tuple[str, dict[str, Any]]:
    check_path = ROOT / check_relpath
    text = check_path.read_text(encoding="utf-8")
    match = re.search(r'FromBase64String\("([^"]+)"\)', text)
    if not match:
        raise RuntimeError(f"No expected JSON base64 payload in {check_relpath}")
    payload = json.loads(base64.b64decode(match.group(1)).decode("utf-8"))
    return match.group(1), payload


def write_blender_expected(check_relpath: str, old_b64: str, payload: dict[str, Any]) -> None:
    check_path = ROOT / check_relpath
    text = check_path.read_text(encoding="utf-8")
    new_b64 = base64.b64encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).decode(
        "ascii"
    )
    check_path.write_text(text.replace(old_b64, new_b64, 1), encoding="utf-8")


def update_blender_task(task: dict[str, Any]) -> None:
    task_id = str(task.get("task_id") or "")
    extra = BLENDER_EXTRAS.get(task_id)
    if not extra:
        return
    old_b64, payload = decode_blender_expected(extra["check"])
    if not any(item.get("path") == extra["blend"]["path"] for item in payload.get("additional", [])):
        payload.setdefault("additional", []).append(extra["blend"])
    existing_artifacts = {item.get("path"): item for item in payload.setdefault("text_artifacts", [])}
    for replacement in extra.get("artifact_replacements", []):
        current = existing_artifacts.get(replacement["path"])
        current_content = str((current or {}).get("content") or "")
        if "final_audit_stack.blend" not in current_content:
            existing_artifacts[replacement["path"]] = {
                "path": replacement["path"],
                "content": replacement["new"],
            }
    for artifact in extra["text_artifacts"]:
        existing_artifacts[artifact["path"]] = artifact
    payload["text_artifacts"] = list(existing_artifacts.values())
    write_blender_expected(extra["check"], old_b64, payload)

    instruction = str(task.get("instruction") or "")
    if str(extra["blend"]["path"]) not in instruction:
        marker = str(extra["insert_before"])
        if marker in instruction:
            instruction = instruction.replace(marker, extra["instruction"] + marker, 1)
        else:
            instruction = instruction.rstrip() + " " + extra["instruction"]
    for artifact in extra["text_artifacts"]:
        if artifact["path"] not in instruction:
            instruction += f" Create {artifact['path']} with exactly this content: {artifact['content']!r}."
    for replacement in extra.get("artifact_replacements", []):
        if replacement["old"] in instruction:
            instruction = instruction.replace(replacement["old"], replacement["new"])
        old_escaped = replacement["old"].replace("\t", "\\t").replace("\n", "\\n")
        new_escaped = replacement["new"].replace("\t", "\\t").replace("\n", "\\n")
        if old_escaped in instruction:
            instruction = instruction.replace(old_escaped, new_escaped)
    task["instruction"] = instruction

    metadata = task.setdefault("metadata", {})
    metadata["hard_plus_blender_requirement"] = (
        "primary blend plus four derivative blend files are evaluator checked; the dependency audit blend must be linked "
        "through two earlier derivative blends in the crosswalk and orchestration files"
    )


def main() -> None:
    changed = []
    for relpath in TARGET_TASKS:
        task = load_yaml(relpath)
        update_blender_task(task)
        files = supplemental_files(task)
        append_hard_plus_instruction(task, files)
        add_supplemental_checks(task, files)
        update_metadata(task)
        dump_yaml(relpath, task)
        changed.append(relpath)
    print(f"hardened {len(changed)} Windows hard tasks")
    for relpath in changed:
        print(relpath)


if __name__ == "__main__":
    main()
