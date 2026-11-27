"""Windows OpenNote v1 (stage makeup, community meal, live music, forum arrival): no order is stated.

Each ``instruction`` (tasks/v1/windows/opennote_*.yaml) is numbered Chinese steps with no
"then"/"after"/"before"/"in this order" between business actions, so the step order is a
demonstration.  Only the sign-in must come before the account's actions; each action still has
to happen exactly once, and feed, detail and final-page views are neither required nor counted.
"""

from __future__ import annotations

import pytest

from evaluators.windows import (
    opennote_community_meal_three_notes_1788409691786_981937 as meal,
    opennote_forum_arrival_three_notes_1788412586968_101704 as forum,
    opennote_live_music_visuals_three_notes_1788411372670_327795 as music,
    opennote_stage_makeup_three_notes_1788408391290_206403 as stage,
)
from tests.test_windows_opennote_same_title_targets import _Store

LOGIN_FORM = {"code_login_tab_html": 1, "phone_input_html": 1, "code_input_html": 1}


def _stage(store: _Store):
    eng = stage.RULESET_SPEC["engagement"]
    store.seed(eng["note_id"], eng["authorHandle"], eng["title"], "Beauty")
    profile = {"handle": "lina", "displayName": "Lina Park", "title": stage.RULESET_SPEC["profile"]["title"], "bio": "Bio"}
    notes = stage.EXPECTED_NOTES
    return profile, stage.RULESET_SPEC["application_build"], {
        "white_note": lambda: store.publish("n-white", notes["white_note"]),
        "like": lambda: store.toggle("note_like_toggled", store.liked, eng["note_id"], eng["authorHandle"]),
        "save": lambda: store.toggle("note_save_toggled", store.saved, eng["note_id"], eng["authorHandle"]),
        "profile": lambda: store.record("profile_updated", displayName="Lina Park", title=profile["title"], bio="Bio"),
        "blue_note": lambda: store.publish("n-blue", notes["blue_note"]),
        "two_role_note": lambda: store.publish("n-roles", notes["two_role_note"]),
    }


def _meal(store: _Store):
    spec = meal.RULESET_SPEC
    for note_id, author, title in [("n-3343", "cole_51", spec["bakery_save"]["title"]), ("n-3211", "nora_02", spec["picnic_like"]["title"]),
                                   ("n-3046", "lina", spec["picnic_save"]["title"])]:
        store.seed(note_id, author, title, "Food")
    profile = {k: spec["profile"][k] for k in ("handle", "displayName", "title", "bio")}
    notes = meal.EXPECTED_NOTES
    return profile, meal.EXPECTED_BUILD, {
        "bakery_save": lambda: store.toggle("note_save_toggled", store.saved, "n-3343", "cole_51"),
        "orange_note": lambda: store.publish("n-orange", notes["orange_note"]),
        "picnic_like": lambda: store.toggle("note_like_toggled", store.liked, "n-3211", "nora_02"),
        "picnic_save": lambda: store.toggle("note_save_toggled", store.saved, "n-3046", "lina"),
        "profile": lambda: store.record("profile_updated", displayName="Lina Park", title=profile["title"], bio=profile["bio"]),
        "blue_note": lambda: store.publish("n-blue", notes["blue_note"]),
        "meal_plan": lambda: store.publish("n-plan", notes["meal_plan"]),
    }


def _music(store: _Store):
    spec = music.RULESET_SPEC
    store.seed("n-3001", "drew_49", spec["drew"]["title"], "Fashion")
    store.seed("n-3419", "lina", spec["seasonal"]["title"], "Fashion")
    profile = {k: spec["profile"][k] for k in ("handle", "displayName", "title", "bio")}
    notes = music.EXPECTED_NOTES

    def follow():
        store.following.append("drew_49")
        store.record("follow_toggled", handle="drew_49", active=True)

    return profile, music.BUILD, {
        "profile": lambda: store.record("profile_updated", displayName="Lina Park", title=profile["title"], bio=profile["bio"]),
        "blue_green_note": lambda: store.publish("n-guitar", notes["blue_green_note"]),
        "follow": follow,
        "drew_like": lambda: store.toggle("note_like_toggled", store.liked, "n-3001", "drew_49"),
        "live_music_note": lambda: store.publish("n-visuals", notes["live_music_note"]),
        "seasonal_like": lambda: store.toggle("note_like_toggled", store.liked, "n-3419", "lina"),
        "curly_note": lambda: store.publish("n-curly", notes["curly_note"]),
    }


def _forum(store: _Store):
    spec = forum.RULESET_SPEC
    store.seed("n-3207", "lina", spec["old_street"]["title"], "Travel")
    profile = {k: spec["profile"][k] for k in ("handle", "displayName", "title", "bio")}
    notes = forum.EXPECTED_NOTES
    return profile, forum.BUILD, {
        "forum_arrival_note": lambda: store.publish("n-arrival", notes["forum_arrival_note"]),
        "like": lambda: store.toggle("note_like_toggled", store.liked, "n-3207", "lina"),
        "save": lambda: store.toggle("note_save_toggled", store.saved, "n-3207", "lina"),
        "profile": lambda: store.record("profile_updated", displayName="Lina Park", title=profile["title"], bio=profile["bio"]),
        "two_day_note": lambda: store.publish("n-two-day", notes["two_day_note"]),
        "group_session_note": lambda: store.publish("n-group", notes["group_session_note_and_final_ui"]),
    }


TASKS = {"stage": (stage, _stage), "meal": (meal, _meal), "music": (music, _music), "forum": (forum, _forum)}
#: The step order each instruction demonstrates.
DEMONSTRATED = {
    "stage": ["white_note", "like", "save", "profile", "blue_note", "two_role_note"],
    "meal": ["bakery_save", "orange_note", "picnic_like", "picnic_save", "profile", "blue_note", "meal_plan"],
    "music": ["profile", "blue_green_note", "follow", "drew_like", "live_music_note", "seasonal_like", "curly_note"],
    "forum": ["forum_arrival_note", "like", "save", "profile", "two_day_note", "group_session_note"],
}


def _run(task: str, order: list[str], *, before_login: tuple[str, ...] = (), last_view: bool = False) -> dict:
    module, setup = TASKS[task]
    store = _Store()
    profile, build, actions = setup(store)
    for name in before_login:
        actions[name]()
    store.record("session_login_success", handle="lina")
    for name in order:
        if name not in before_login:
            actions[name]()
    if last_view:
        store.record("feed_view", view="home", query="", category="Recommended", tag="", handle="")
    raw = store.raw(module, profile, build)
    raw["login_form"] = LOGIN_FORM
    return module.evaluate_state(raw, "fresh_clone_verified")


@pytest.mark.parametrize("task", list(TASKS))
def test_demonstrated_order_passes(task):
    verdict = _run(task, DEMONSTRATED[task])
    assert verdict["status"] == "PASS", verdict["failures"]


@pytest.mark.parametrize("task", list(TASKS))
def test_reversed_order_passes(task):
    verdict = _run(task, DEMONSTRATED[task][::-1])
    assert verdict["status"] == "PASS", verdict["failures"]


@pytest.mark.parametrize("task", list(TASKS))
def test_ending_on_another_page_passes(task):
    # Forum: the profile feed the app shows after the last Publish used to have to be the last event.
    verdict = _run(task, DEMONSTRATED[task], last_view=True)
    assert verdict["status"] == "PASS", verdict["failures"]


@pytest.mark.parametrize("task", list(TASKS))
def test_business_action_before_the_sign_in_fails(task):
    first = DEMONSTRATED[task][-1]
    verdict = _run(task, DEMONSTRATED[task], before_login=(first,))
    assert verdict["failures"] == ["workflow_timeline_exact"]


@pytest.mark.parametrize("task", list(TASKS))
def test_missing_business_action_fails(task):
    order = DEMONSTRATED[task][:-1]
    verdict = _run(task, order)
    assert verdict["status"] == "FAIL"
    assert "workflow_timeline_exact" in verdict["failures"] and len(verdict["failures"]) == 2


@pytest.mark.parametrize("task,action,check", [
    ("stage", "like", "beauty_engagement_exact"),
    ("meal", "bakery_save", "bakery_save_exact"),
    ("music", "seasonal_like", "seasonal_engagement_exact"),
    ("forum", "save", "old_street_engagement_exact"),
    ("stage", "profile", "profile_role_exact"),
])
def test_duplicate_business_action_fails(task, action, check):
    verdict = _run(task, DEMONSTRATED[task] + [action])
    assert verdict["failures"] == [check]


def test_live_music_needs_no_explore_navigation():
    # The old workflow_navigation_hard check wanted note-detail opens and a Fashion feed view between
    # given actions; the reversed run has none of them in those places.
    verdict = _run("music", DEMONSTRATED["music"][::-1])
    assert "workflow_navigation_hard" not in {check["check_id"] for check in verdict["checks"]}
    assert verdict["status"] == "PASS"


@pytest.mark.parametrize("module,stem", [
    (stage, "opennote_stage_makeup_three_notes_1788408391290_206403"),
    (meal, "opennote_community_meal_three_notes_1788409691786_981937"),
    (music, "opennote_live_music_visuals_three_notes_1788411372670_327795"),
    (forum, "opennote_forum_arrival_three_notes_1788412586968_101704"),
])
def test_ruleset_digest_matches_the_task(module, stem):
    import hashlib
    import json
    from pathlib import Path

    import yaml

    digest = hashlib.sha256(json.dumps(module.RULESET_SPEC, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert module.RULESET_SHA256 == digest
    root = Path(__file__).resolve().parents[1]
    for folder in ("tasks/v1/windows",):
        task = yaml.safe_load((root / folder / f"{stem}.yaml").read_text(encoding="utf8"))
        assert task["evaluation"]["params"]["expected_ruleset_sha256"] == digest
