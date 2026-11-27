from evaluators.cua_review.evaluators.macos.opennote_three_posts_saved import (
    OpenNoteThreePostsSavedSourceEvaluator,
)
from evaluators.macos.opennote_macos1_canal_train_walk_liked_profile_workflow import (
    OpenNoteGameTripSavedProfileEvaluator,
)


def test_opennote_foreground_uses_menu_bar_and_window_when_shell_bundle_is_stale():
    evaluator = OpenNoteThreePostsSavedSourceEvaluator()
    metadata = {"checks": []}
    context = {
        "final_observation": {
            "foreground_app": "OpenAppShell",
            "foreground_bundle_id": "local.osomni.openfood",
            "a11y_tree": [
                {"roleDescription": "menu bar item", "text": "Apple"},
                {"roleDescription": "menu bar item", "text": "OpenNote"},
                {"roleDescription": "standard window", "text": "OpenNote"},
                {"roleDescription": "link", "text": "Explore"},
            ],
        }
    }

    evaluator._check_final_ui(
        metadata,
        context,
        {"app_name": "OpenNote", "bundle_id": "local.osomni.opennote", "expected_final_ui_markers": ["Saved"]},
        [],
    )

    assert metadata["checks"][0]["name"] == "final_ui.foreground_opennote"
    assert metadata["checks"][0]["passed"] is True
    # Correct foreground identity does not make a missing task-specific view pass.
    assert metadata["checks"][1]["passed"] is False


def test_opennote_foreground_does_not_accept_an_unrelated_accessibility_tree():
    evaluator = OpenNoteThreePostsSavedSourceEvaluator()
    metadata = {"checks": []}
    evaluator._check_final_ui(
        metadata,
        {"final_observation": {
            "foreground_app": "OpenAppShell",
            "foreground_bundle_id": "local.osomni.openfood",
            "a11y_tree": [
                {"roleDescription": "menu bar item", "text": "Apple"},
                {"roleDescription": "menu bar item", "text": "OpenFood"},
                {"roleDescription": "standard window", "text": "OpenFood"},
            ],
        }},
        {"app_name": "OpenNote", "bundle_id": "local.osomni.opennote", "expected_final_ui_markers": ["Saved"]},
        [],
    )

    assert metadata["checks"][0]["passed"] is False


def test_opennote_serialized_a11y_tree_supplies_final_view_markers():
    summary = OpenNoteThreePostsSavedSourceEvaluator()._observation_summary(
        {"a11y_tree": [{"roleDescription": "text", "text": "Saved"}]}
    )

    assert "Saved" in summary["text"]


def test_opennote_tags_allow_app_case_normalization_but_keep_order_and_values():
    match = OpenNoteThreePostsSavedSourceEvaluator._ordered_tags_match

    # The GUI field shows lowercase, while the macOS app API stores the first
    # tag with an uppercase initial. This semantic case-only change is accepted.
    assert match(["coatswap", "repair"], ["Coatswap", "repair"])

    # Tag order and tag identity remain part of the task requirement.
    assert not match(["coatswap", "repair"], ["repair", "Coatswap"])
    assert not match(["coatswap", "repair"], ["Coatswap", "mending"])
    assert not match(["coatswap", "repair"], ["Coatswap"])


def test_opennote_raw_final_ui_nodes_override_stale_app_shell_telemetry():
    evaluator = OpenNoteThreePostsSavedSourceEvaluator()
    metadata = {"checks": []}
    evaluator._check_final_ui(
        metadata,
        {"final_observation": {
            "foreground_app": "OpenAppShell",
            "foreground_bundle_id": "local.osomni.openfood",
            "ui_nodes": [
                {"roleDescription": "menu bar item", "text": "OpenNote"},
                {"roleDescription": "standard window", "text": "OpenNote"},
            ],
        }},
        {"app_name": "OpenNote", "bundle_id": "local.osomni.opennote", "expected_final_ui_markers": ["Saved"]},
        [],
    )

    assert metadata["checks"][0]["passed"] is True
    # Foreground compatibility does not satisfy the task's separate view check.
    assert metadata["checks"][1]["passed"] is False


def test_canal_train_final_ui_recognizes_open_note_from_raw_accessibility_nodes():
    class Observation:
        foreground_app = "OpenAppShell"
        foreground_bundle_id = "local.osomni.openfood"
        ui_nodes = [
            {"roleDescription": "menu bar item", "text": "Apple"},
            {"roleDescription": "menu bar item", "text": "OpenNote"},
            {"roleDescription": "standard window", "text": "OpenNote"},
        ]

    ui = OpenNoteGameTripSavedProfileEvaluator._collect_final_ui(Observation())

    assert ui["foreground_app"] == "OpenAppShell"
    assert ui["accessibility_app_name"] is True


def test_canal_train_final_ui_rejects_unrelated_accessibility_app():
    class Observation:
        foreground_app = "OpenAppShell"
        foreground_bundle_id = "local.osomni.openfood"
        ui_nodes = [
            {"roleDescription": "menu bar item", "text": "OpenFood"},
            {"roleDescription": "standard window", "text": "OpenFood"},
        ]

    ui = OpenNoteGameTripSavedProfileEvaluator._collect_final_ui(Observation())

    assert ui["accessibility_app_name"] is False
