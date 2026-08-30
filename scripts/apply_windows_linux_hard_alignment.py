from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


ALIGNMENT = {
    "tasks/windows/actual_budget_full_setup.yaml": {
        "linux_peer": "linux.actual_budget.household_budget_setup_hard",
        "linux_peer_file": "tasks/linux/actual_budget_household_budget_setup_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/actual_budget_add_transactions.yaml": {
        "linux_peer": "linux.actual_budget.operations_multi_account_hard",
        "linux_peer_file": "tasks/linux/actual_budget_operations_multi_account_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/blender_robot_tower_layout_scene.yaml": {
        "linux_peer": "linux.blender.prepare_social_render",
        "linux_peer_file": "tasks/linux/blender_prepare_social_render_hard.yaml",
        "alignment": "direct_with_version_constraints",
        "note": "Windows uses Blender 2.79b, so EEVEE-specific Linux settings are represented through render/output and multi-blend checks.",
    },
    "tasks/windows/blender_warehouse_blockout_scene.yaml": {
        "linux_peer": "linux.blender.restage_product_objects",
        "linux_peer_file": "tasks/linux/blender_restage_product_objects_hard.yaml",
        "alignment": "direct_with_version_constraints",
        "note": "Windows uses Blender 2.79b, so EEVEE-specific Linux settings are represented through render/output and multi-blend checks.",
    },
    "tasks/windows/calc_formulas_conditional.yaml": {
        "linux_peer": "linux.calc.freeze_header_range",
        "linux_peer_file": "tasks/linux/calc_freeze_header_range_hard.yaml",
        "alignment": "difficulty_equivalent",
    },
    "tasks/windows/calc_crosssheet_chart.yaml": {
        "linux_peer": "linux.calc.demographic_profile_pivots",
        "linux_peer_file": "tasks/linux/calc_demographic_profile_pivots_hard.yaml",
        "alignment": "difficulty_equivalent",
    },
    "tasks/windows/calendar_create_recurring_event.yaml": {
        "linux_peer": "linux.thunderbird_calendar.build_recurring_release_plan_hard",
        "linux_peer_file": "tasks/linux/thunderbird_calendar_build_recurring_release_plan_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/calendar_manage_multiple_events.yaml": {
        "linux_peer": "linux.thunderbird_calendar.plan_next_week_reviews_hard",
        "linux_peer_file": "tasks/linux/thunderbird_calendar_plan_next_week_reviews_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/deltachat_share_sync_time_with_avery_and_project_updates.yaml": {
        "linux_peer": "linux.deltachat.coordination_roundup",
        "linux_peer_file": "tasks/linux/deltachat_reply_alice_hard.yaml",
        "alignment": "difficulty_equivalent",
    },
    "tasks/windows/deltachat_create_launch_debrief_from_existing_chats.yaml": {
        "linux_peer": "linux.deltachat.end_of_day_wrap",
        "linux_peer_file": "tasks/linux/deltachat_group_ops_sprint_hard.yaml",
        "alignment": "difficulty_equivalent",
    },
    "tasks/windows/drawio_ellipse_vertical_divider_styled.yaml": {
        "linux_peer": "linux.drawio.refresh_release_flow",
        "linux_peer_file": "tasks/linux/drawio_refresh_release_flow_hard.yaml",
        "alignment": "difficulty_equivalent",
    },
    "tasks/windows/drawio_sum_loop_flowchart.yaml": {
        "linux_peer": "linux.drawio.relabel_incident_sync",
        "linux_peer_file": "tasks/linux/drawio_relabel_incident_sync_hard.yaml",
        "alignment": "difficulty_equivalent",
    },
    "tasks/windows/gimp_apple_and_orange_focus_blur_bw_upside_down.yaml": {
        "linux_peer": "linux.gimp.crop_center",
        "linux_peer_file": "tasks/linux/gimp_crop_center_hard.yaml",
        "alignment": "difficulty_equivalent",
    },
    "tasks/windows/gimp_cartoon_girl_bottom_left_blend_flip_opacity.yaml": {
        "linux_peer": "linux.gimp.scale_image",
        "linux_peer_file": "tasks/linux/gimp_scale_image_hard.yaml",
        "alignment": "difficulty_equivalent",
    },
    "tasks/windows/impress_animation_transition.yaml": {
        "linux_peer": "linux.impress.add_dissolve_transition",
        "linux_peer_file": "tasks/linux/impress_add_dissolve_transition_hard.yaml",
        "alignment": "direct_plus_extra",
    },
    "tasks/windows/impress_slide_shape_bold.yaml": {
        "linux_peer": "linux.impress.create_six_image_slides",
        "linux_peer_file": "tasks/linux/impress_create_six_image_slides_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/notepad_append_text.yaml": {
        "linux_peer": "linux.notepadqq.sync_ops_bundle",
        "linux_peer_file": "tasks/linux/notepadqq_sync_ops_bundle_hard.yaml",
        "alignment": "functional_equivalent",
    },
    "tasks/windows/notepad_edit_config.yaml": {
        "linux_peer": "linux.notepadqq.prepare_release_packet",
        "linux_peer_file": "tasks/linux/notepadqq_prepare_release_packet_hard.yaml",
        "alignment": "functional_equivalent",
    },
    "tasks/windows/openshop_checkout_two_items.yaml": {
        "linux_peer": "linux.openshop.checkout_coffee",
        "linux_peer_file": "tasks/linux/openshop_checkout_coffee_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/openshop_add_headphones_to_cart.yaml": {
        "linux_peer": "linux.openshop.checkout_coffee",
        "linux_peer_file": "tasks/linux/openshop_checkout_coffee_hard.yaml",
        "alignment": "direct_plus_extra",
    },
    "tasks/windows/spotube_album_queue_light_english_playlist_repeat.yaml": {
        "linux_peer": "linux.spotube.import_city_weather_mix",
        "linux_peer_file": "tasks/linux/spotube_import_city_weather_mix_hard.yaml",
        "alignment": "functional_equivalent",
    },
    "tasks/windows/spotube_one_ok_rock_queue_single_repeat_pause.yaml": {
        "linux_peer": "linux.spotube.import_focus_capsule",
        "linux_peer_file": "tasks/linux/spotube_import_focus_capsule_hard.yaml",
        "alignment": "functional_equivalent",
    },
    "tasks/windows/thunderbird_collect_st_club_progress.yaml": {
        "linux_peer": "linux.thunderbird.thunderbird_filter_discount_to_promotions",
        "linux_peer_file": "tasks/linux/thunderbird_filter_discount_to_promotions_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/thunderbird_send_email_exact_body.yaml": {
        "linux_peer": "linux.thunderbird.thunderbird_unified_inbox",
        "linux_peer_file": "tasks/linux/thunderbird_unified_inbox_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/vscode_ops_handoff_workspace.yaml": {
        "linux_peer": "linux.vscode.prepare_release_packet",
        "linux_peer_file": "tasks/linux/vscode_prepare_release_packet_hard.yaml",
        "alignment": "functional_equivalent_plus_extra",
    },
    "tasks/windows/vscode_release_cleanup_workspace.yaml": {
        "linux_peer": "linux.vscode.apply_theme_ticket",
        "linux_peer_file": "tasks/linux/vscode_apply_theme_ticket_hard.yaml",
        "alignment": "functional_equivalent_plus_extra",
    },
    "tasks/windows/wireshark_advanced_filter_export.yaml": {
        "linux_peer": "linux.wireshark.export_protocol_bundle",
        "linux_peer_file": "tasks/linux/wireshark_export_protocol_bundle_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/wireshark_statistics_report.yaml": {
        "linux_peer": "linux.wireshark.export_link_and_syn_bundle",
        "linux_peer_file": "tasks/linux/wireshark_export_link_and_syn_bundle_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/writer_headings_list_pagebreak.yaml": {
        "linux_peer": "linux.writer.add_reference_cross_reference",
        "linux_peer_file": "tasks/linux/writer_add_reference_cross_reference_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/writer_toc_image_footnote.yaml": {
        "linux_peer": "linux.writer.deduplicate_train_records",
        "linux_peer_file": "tasks/linux/writer_deduplicate_train_records_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/zotero_create_collection_with_notes.yaml": {
        "linux_peer": "linux.zotero.research_collection_with_notes",
        "linux_peer_file": "tasks/linux/zotero_research_collection_with_notes_hard.yaml",
        "alignment": "direct",
    },
    "tasks/windows/zotero_organize_library.yaml": {
        "linux_peer": "linux.zotero.reference_library_buildout",
        "linux_peer_file": "tasks/linux/zotero_reference_library_buildout_hard.yaml",
        "alignment": "direct",
    },
}


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump_yaml(path: Path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def apply_metadata() -> None:
    for relpath, info in ALIGNMENT.items():
        path = ROOT / relpath
        data = load_yaml(path)
        metadata = data.setdefault("metadata", {})
        metadata["linux_peer"] = info["linux_peer"]
        metadata["linux_peer_file"] = info["linux_peer_file"]
        metadata["alignment_status"] = info["alignment"]
        if "note" in info:
            metadata["alignment_note"] = info["note"]
        dump_yaml(path, data)


def write_report() -> None:
    report_path = ROOT / "docs" / "windows_linux_hard_alignment.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Windows/Linux Hard Task Alignment",
        "",
        "This file records the intended one-to-one or role-equivalent peer for every Windows single-app hard task.",
        "Statuses marked `needs_task_and_evaluator_upgrade` are not considered fully aligned until both the task and evaluator are rewritten.",
        "",
        "| Windows task | Windows app | Linux peer | Status | Notes |",
        "|---|---|---|---|---|",
    ]
    for relpath, info in sorted(ALIGNMENT.items()):
        data = load_yaml(ROOT / relpath)
        metadata = data.get("metadata", {})
        app = metadata.get("app_name") or metadata.get("app") or ""
        note = info.get("note", "")
        lines.append(f"| `{data['task_id']}` | {app} | `{info['linux_peer']}` | `{info['alignment']}` | {note} |")

    lines.extend(
        [
            "",
            "## Platform Gap",
            "",
            "Linux has Marble map tasks. Windows currently has no installed map application with the same controllable/evaluable bookmark workflow. The options are to install a Windows map application and add two hard tasks, or to mark Marble as Linux-only in cross-platform difficulty analysis.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    apply_metadata()
    write_report()
    print(f"applied alignment metadata for {len(ALIGNMENT)} Windows hard tasks")
