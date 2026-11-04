"""iOS Reminders list tasks: grade the list's contents wherever the run stopped.

With ``navigate_to_list: true`` (the two v1 Reminders tasks) the evaluator brings
Reminders forward and opens the list with Back / the list row before reading it.
Without the param the old "must end inside the list" behaviour is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

import evaluators.ios.reminder_list_state as module
from evaluators.ios.reminder_list_state import ReminderListStateEvaluator

REPO = Path(__file__).resolve().parents[1]
BUNDLE = "com.apple.reminders"
LIST = "Benchmark Tasks"
TITLES = ["Plan Friday team lunch", "Send final vendor ping", "Buy sparkling water"]


def _nav(title, back=True):
    nodes = [{"id": "title", "type": "StaticText", "text": title, "rect": {"y": 100}}]
    if back:
        nodes.append({"id": "back", "type": "Button", "text": "Back", "rect": {"y": 60}})
    return nodes


SCREENS = {
    "springboard": [{"id": "icon", "type": "Icon", "text": "Reminders", "rect": {"y": 400}}],
    "home": [
        {"id": "add-list", "type": "Button", "text": "Add List", "rect": {"y": 800}},
        {"id": "row-reminders", "type": "Cell", "text": "Reminders, 0", "rect": {"y": 300}},
        {"id": "row-benchmark", "type": "Cell", "text": "Benchmark Tasks, 3", "rect": {"y": 360}},
    ],
    "list": _nav(LIST) + [
        {"id": f"r{index}", "type": "Cell", "text": f"{title}, incomplete", "rect": {"y": 200 + 50 * index}}
        for index, title in enumerate(TITLES)
    ],
    "other_list": _nav("Reminders"),
    "sheet": [{"id": "done", "type": "Button", "text": "Done", "rect": {"y": 60}}],
}


class FakeController:
    def __init__(self, screen, resume="other_list"):
        self.screen = screen
        self.resume = resume
        self.actions = []

    def observe(self, include_ui_tree=True):
        bundle = "com.apple.springboard" if self.screen == "springboard" else BUNDLE
        return SimpleNamespace(foreground_bundle_id=bundle, ui_nodes=[dict(n) for n in SCREENS[self.screen]])

    def activate_app(self, bundle_id):
        self.actions.append(("activate_app", bundle_id))
        if self.screen == "springboard":
            self.screen = self.resume

    def execute_action(self, action, ui_nodes):
        self.actions.append((action["type"], action.get("target")))
        if action["type"] == "scroll":
            return {"success": True}
        if action["type"] == "tap" and action["target"] == "back" and self.screen in {"list", "other_list"}:
            self.screen = "home"
        elif action["type"] == "tap" and action["target"] == "row-benchmark" and self.screen == "home":
            self.screen = "list"
        else:
            return {"success": False}
        return {"success": True}


def _evaluate(controller, **params):
    base = {"bundle_id": BUNDLE, "list_name": LIST, "ordered_titles": TITLES, "exact_titles": TITLES}
    base.update(params)
    return ReminderListStateEvaluator().evaluate({
        "controller": controller,
        "final_observation": controller.observe(),
        "params": base,
    })


def _no_sleep(monkeypatch):
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)


def test_ending_on_springboard_inside_another_list_is_graded_on_contents(monkeypatch):
    _no_sleep(monkeypatch)
    controller = FakeController("springboard", resume="other_list")
    result = _evaluate(controller, navigate_to_list=True)
    assert result.status.value == "PASS", result.message
    assert result.metadata["navigation"]["steps"] == ["activate_app", "back", "open_list"]


def test_ending_on_lists_home_opens_the_list(monkeypatch):
    _no_sleep(monkeypatch)
    result = _evaluate(FakeController("home"), navigate_to_list=True)
    assert result.status.value == "PASS", result.message
    assert result.metadata["navigation"]["steps"] == ["open_list"]


def test_already_inside_the_list_needs_no_navigation(monkeypatch):
    _no_sleep(monkeypatch)
    controller = FakeController("list")
    result = _evaluate(controller, navigate_to_list=True)
    assert result.status.value == "PASS"
    assert result.metadata["navigation"] is None
    assert not [a for a in controller.actions if a[0] in {"tap", "activate_app"}]


def test_wrong_contents_still_fail_after_navigation(monkeypatch):
    _no_sleep(monkeypatch)
    result = _evaluate(FakeController("home"), navigate_to_list=True,
                       ordered_titles=TITLES + ["Book projector"], exact_titles=TITLES + ["Book projector"])
    assert result.status.value == "FAIL"
    assert result.metadata["navigation"]["reached_list"] is True


def test_open_editor_sheet_is_not_dismissed(monkeypatch):
    _no_sleep(monkeypatch)
    controller = FakeController("sheet")
    result = _evaluate(controller, navigate_to_list=True)
    assert result.status.value == "FAIL"
    assert ("tap", "done") not in controller.actions


def test_without_the_param_ending_outside_the_list_fails_as_before(monkeypatch):
    _no_sleep(monkeypatch)
    home = FakeController("home")
    spring = FakeController("springboard")
    assert _evaluate(home).status.value == "FAIL"
    assert _evaluate(spring).status.value == "FAIL"
    assert home.actions == [] and spring.actions == []


def test_v1_reminders_tasks_opt_in():
    for name in ("reminders_manage_seeded_list", "reminders_rework_seeded_agenda"):
        doc = yaml.safe_load((REPO / "tasks/v1/ios" / f"{name}.yaml").read_text(encoding="utf-8"))
        assert doc["evaluation"]["evaluator_id"] == "evaluators.ios.reminder_list_state:ReminderListStateEvaluator"
        assert doc["evaluation"]["params"]["navigate_to_list"] is True
