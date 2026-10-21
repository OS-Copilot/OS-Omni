from __future__ import annotations

from initializers.macos.maps import MapsInitializer


def test_setup_script_uses_accessibility_prompt_dismissal_without_global_scan():
    script = MapsInitializer._setup_script(
        initial_url="",
        reset_state=False,
        force_english=False,
        dismiss_prompts=True,
    )

    assert 'open -b com.apple.Maps' in script
    assert 'tell application "Maps" to activate' in script
    assert "repeat 12 times" not in script
    assert "set promptButtons" not in script
    assert "set promptProcesses" not in script


class NoPromptController:
    def __init__(self):
        self.observe_calls = 0
        self.actions = []

    def observe(self, **kwargs):
        self.observe_calls += 1
        return type("Observation", (), {"ui_nodes": []})()

    def execute_action(self, action, ui_nodes):
        self.actions.append(action)
        return {"success": True, "returncode": 0}


def test_no_prompt_dismissal_finishes_after_one_accessibility_observation():
    controller = NoPromptController()

    MapsInitializer._dismiss_prompt_actions(controller)

    assert controller.observe_calls == 1
    assert controller.actions == []
