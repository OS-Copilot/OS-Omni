"""iOS OpenNote 618106 / 194503 / 870344: grade the business events the brief asks for.

The old ``timeline_exact`` replayed the recorded 23/11/14-event suffix, browsing
included (home/profile feed views with seed totals, note opens), so a launch-time
feed view or one extra profile visit decided the grade. It was later made
diagnostic, which left no gate on extra or duplicate business actions.
``durable_events_and_required_order`` now compares the business events as a
multiset (browsing not counted; an identical profile re-save counts once) and
enforces only the order a brief states: none for 618106 and 194503; for 870344
"Create and publish three new notes ... and then update the profile and interact
with an existing note".
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from evaluators.ios import opennote_community_meal_three_notes_618106 as meal
from evaluators.ios import opennote_forum_outfit_three_notes_194503 as forum
from evaluators.ios import opennote_stage_makeup_three_notes_870344 as stage

REPO = Path(__file__).resolve().parents[1]
BASELINE = 100
BOUNDARY = {"mode": "automatic_baseline_seq", "baseline_max_event_seq": BASELINE}
CHECK = "durable_events_and_required_order"
BIO = "Collecting honest routes, useful details, and everyday ideas worth trying."

MEAL = meal.OpenNoteCommunityMealThreeNotes618106Evaluator
FORUM = forum.OpenNoteForumOutfitThreeNotes194503Evaluator
STAGE = stage.OpenNoteStageMakeupThreeNotes870344Evaluator


def _data_url(seed: str) -> tuple[str, dict]:
    payload = f"synthetic cover {seed}".encode()
    url = "data:image/jpeg;base64," + base64.b64encode(payload).decode()
    return url, {"mime": "image/jpeg", "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


@pytest.fixture(autouse=True)
def synthetic_covers(monkeypatch):
    """Real covers are large photos; bind each expected cover to a small data URL."""
    urls = {}
    for module in (meal, forum, stage):
        for group, expected in module._NOTE_EXPECTED.items():
            url, evidence = _data_url(f"{module.__name__}:{group}")
            if "valid_data_url" in expected["cover"]:
                evidence["valid_data_url"] = True
            monkeypatch.setitem(expected, "cover", evidence)
            urls[(module, group)] = url
    return urls


def _note(module, group, covers, note_id):
    expected = module._NOTE_EXPECTED[group]
    return {
        "id": note_id,
        "authorHandle": expected["authorHandle"],
        "title": expected["title"],
        "text": expected["text"],
        "category": expected["category"],
        "tags": list(expected["tags"]),
        "location": expected["location"],
        "cover": covers[(module, group)],
    }


def _created(module, group, note_id):
    expected = module._NOTE_EXPECTED[group]
    return {"type": "note_created", "noteId": note_id, "title": expected["title"],
            "category": expected["category"], "tags": list(expected["tags"])}


def _feed(view="home", category="Recommended", handle="", total=7):
    return {"type": "feed_view", "view": view, "query": "", "category": category, "tag": "",
            "handle": handle, "total": total}


def _events(payloads):
    # A launch-time feed view before the baseline is outside the window either way.
    rows = [{**_feed(total=420), "seq": BASELINE, "timestamp": "2026-11-04T10:00:00.000Z"}]
    for offset, payload in enumerate(payloads, start=1):
        rows.append({**payload, "seq": BASELINE + offset,
                     "timestamp": f"2026-11-04T10:{offset // 60:02d}:{offset % 60:02d}.000Z"})
    return rows


def _failed(result):
    return set(result.metadata["failures"])


def _check(result):
    return next(c for c in result.metadata["checks"] if c["name"] == CHECK)


def test_yaml_hashes_track_the_new_rulesets():
    for module, stem in (
        (meal, "opennote_community_meal_three_notes_618106"),
        (forum, "opennote_forum_outfit_three_notes_194503"),
        (stage, "opennote_stage_makeup_three_notes_870344"),
    ):
        canonical = hashlib.sha256(json.dumps(
            module.RULESET_SPEC, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        assert module.RULESET_SHA256 == canonical
        doc = yaml.safe_load((REPO / "tasks/v1/ios" / f"{stem}.yaml").read_text(encoding="utf-8"))
        assert doc["evaluation"]["params"]["expected_ruleset_sha256"] == canonical
        assert doc["metadata"]["verifier_rules"]["ruleset_sha256"] == canonical
        assert [spec["name"] for spec in module.CHECKPOINT_SPECS][-1] == CHECK
        assert "timeline_exact" not in json.dumps(module.RULESET_SPEC)


# ---------------------------------------------------------------------------
# 618106: three Food notes, save, like, follow, bio
# ---------------------------------------------------------------------------

MEAL_IDS = {"orange_note": "n-9001", "blue_note": "n-9002", "meal_plan": "n-9003"}
MEAL_PROFILE = {"type": "profile_updated", "displayName": "Lina Park", "title": "City life editor",
                "bio": BIO + " Community meal lead"}
MEAL_SAVE = {"type": "note_save_toggled", "noteId": "n-3002", "authorHandle": "theo_11", "active": True}
MEAL_LIKE = {"type": "note_like_toggled", "noteId": "n-3211", "authorHandle": "nora_02", "active": True}
MEAL_FOLLOW = {"type": "follow_toggled", "handle": "freya_60", "active": True}


def _meal_state(covers, payloads, *, bio=BIO + " Community meal lead", extra_notes=()):
    notes = [
        {"id": "n-3002", "authorHandle": "theo_11", "category": "Food",
         "title": "What changed after I tried lemon cake slice"},
        {"id": "n-3211", "authorHandle": "nora_02", "category": "Food",
         "title": "I changed one thing about picnic rice box"},
        {"id": "n-3024", "authorHandle": "freya_60", "category": "Food",
         "title": "The weak coffee part of weekday ramen"},
        *(_note(meal, group, covers, note_id) for group, note_id in MEAL_IDS.items()),
        *extra_notes,
    ]
    return {
        "notes": notes,
        "users": [{"handle": "lina", "displayName": "Lina Park", "title": "City life editor", "bio": bio}],
        "userState": {"lina": {"likedNoteIds": ["n-3211"], "savedNoteIds": ["n-3002"],
                               "following": ["freya_60"]}},
        "evaluationEvents": _events(payloads),
    }


def _meal_brief_run():
    """Notes first, then the profile, then the engagements; browsing in between."""
    return [
        _created(meal, "meal_plan", MEAL_IDS["meal_plan"]),
        _feed("profile", "", "lina", 33),
        _created(meal, "blue_note", MEAL_IDS["blue_note"]),
        _created(meal, "orange_note", MEAL_IDS["orange_note"]),
        _feed("profile", "", "lina", 35),
        MEAL_PROFILE,
        MEAL_PROFILE,  # saved twice with the same values
        _feed(category="Food", total=42),
        {"type": "note_detail_opened", "noteId": "n-3024"},
        MEAL_FOLLOW,
        {"type": "note_detail_opened", "noteId": "n-3211"},
        MEAL_LIKE,
        {"type": "note_detail_opened", "noteId": "n-3002"},
        MEAL_SAVE,
    ]


def test_618106_brief_faithful_run_in_another_order_passes(synthetic_covers):
    result = MEAL.evaluate_state(_meal_state(synthetic_covers, _meal_brief_run()), boundary=BOUNDARY)
    assert result.status.value == "PASS", result.metadata["failures"]
    assert _check(result)["actual"]["labels"][:3] == [
        "meal_plan_created", "blue_note_created", "orange_note_created",
    ]


def test_618106_extra_like_or_duplicate_note_fails(synthetic_covers):
    extra_like = _meal_brief_run() + [
        {"type": "note_like_toggled", "noteId": "n-3002", "authorHandle": "theo_11", "active": True}
    ]
    result = MEAL.evaluate_state(_meal_state(synthetic_covers, extra_like), boundary=BOUNDARY)
    assert _failed(result) == {CHECK}
    assert _check(result)["actual"]["extra"] == [f"unexpected:note_like_toggled:{BASELINE + 15}"]

    duplicate = _meal_brief_run() + [_created(meal, "blue_note", MEAL_IDS["blue_note"])]
    result = MEAL.evaluate_state(_meal_state(synthetic_covers, duplicate), boundary=BOUNDARY)
    assert _failed(result) == {CHECK}
    assert _check(result)["actual"]["extra"] == ["blue_note_created"]


def test_618106_missing_follow_or_wrong_bio_fails(synthetic_covers):
    missing = [row for row in _meal_brief_run() if row is not MEAL_FOLLOW]
    state = _meal_state(synthetic_covers, missing)
    state["userState"]["lina"]["following"] = []
    result = MEAL.evaluate_state(state, boundary=BOUNDARY)
    assert {"picnic_like_and_freya_follow_exact", CHECK} <= _failed(result)

    wrong = _meal_state(synthetic_covers, _meal_brief_run(), bio=BIO + " Community meal")
    assert "profile_bio_exact" in _failed(MEAL.evaluate_state(wrong, boundary=BOUNDARY))


# ---------------------------------------------------------------------------
# 194503: three Fashion notes, like + save the cold-brew post, bio
# ---------------------------------------------------------------------------

FORUM_IDS = {"arrival_note": "n-9101", "forum_plan_note": "n-9102", "group_session_note": "n-9103"}
FORUM_PROFILE = {"type": "profile_updated", "displayName": "Lina Park", "title": "City life editor",
                 "bio": BIO + " Forum travel editor"}
FORUM_LIKE = {"type": "note_like_toggled", "noteId": "n-3057", "authorHandle": "lina", "active": True}
FORUM_SAVE = {"type": "note_save_toggled", "noteId": "n-3057", "authorHandle": "lina", "active": True}


def _forum_state(covers, payloads, *, extra_notes=()):
    return {
        "notes": [
            {"id": "n-3057", "authorHandle": "lina", "category": "Food",
             "title": "Monday cold brew walk with half-hour line"},
            *(_note(forum, group, covers, note_id) for group, note_id in FORUM_IDS.items()),
            *extra_notes,
        ],
        "users": [{"handle": "lina", "bio": BIO + " Forum travel editor"}],
        "userState": {"lina": {"likedNoteIds": ["n-3057"], "savedNoteIds": ["n-3057"]}},
        "evaluationEvents": _events(payloads),
    }


def _forum_brief_run():
    """Profile first, then the save before the like, then the three notes."""
    return [
        _feed("profile", "", "lina", 32),
        _feed("profile", "", "lina", 32),
        FORUM_PROFILE,
        {"type": "note_detail_opened", "noteId": "n-3057"},
        FORUM_SAVE,
        FORUM_LIKE,
        _created(forum, "group_session_note", FORUM_IDS["group_session_note"]),
        _feed("profile", "", "lina", 33),
        _created(forum, "arrival_note", FORUM_IDS["arrival_note"]),
        _created(forum, "forum_plan_note", FORUM_IDS["forum_plan_note"]),
        _feed("profile", "", "lina", 35),
    ]


def _forum_result(state):
    # 194503 has no evaluate_state helper; this is the same path evaluate() takes.
    raw = FORUM._collect_raw(
        state, boundary=BOUNDARY, application_build=forum.EXPECTED_BUILD,
        observed_at="2026-11-04T10:30:00+00:00", evaluation_session_id="unit", udid="unit",
    )
    return FORUM.evaluate_evidence(raw)


def test_194503_brief_faithful_run_in_another_order_passes(synthetic_covers):
    result = _forum_result(_forum_state(synthetic_covers, _forum_brief_run()))
    assert result.status.value == "PASS", result.metadata["failures"]


def test_194503_extra_note_or_toggle_off_on_fails(synthetic_covers):
    extra_note = {"id": "n-9199", "authorHandle": "lina", "title": "Forum Arrival Outfit draft",
                  "text": "x", "category": "Fashion", "tags": ["forum"], "location": "", "cover": ""}
    payloads = _forum_brief_run() + [
        {"type": "note_created", "noteId": "n-9199", "title": "Forum Arrival Outfit draft",
         "category": "Fashion", "tags": ["forum"]}
    ]
    result = _forum_result(_forum_state(synthetic_covers, payloads, extra_notes=[extra_note]))
    assert _failed(result) == {CHECK}

    toggled = _forum_brief_run() + [{**FORUM_LIKE, "active": False}, FORUM_LIKE]
    result = _forum_result(_forum_state(synthetic_covers, toggled))
    assert _failed(result) == {CHECK}
    assert "cold_brew_like" in _check(result)["actual"]["extra"]


def test_194503_wrong_note_body_still_fails(synthetic_covers):
    state = _forum_state(synthetic_covers, _forum_brief_run())
    state["notes"][1]["text"] = state["notes"][1]["text"].replace("Wear flat shoes", "Wear boots")
    assert "arrival_note_exact" in _failed(_forum_result(state))


# ---------------------------------------------------------------------------
# 870344: three Beauty notes "and then" the Role update and Like/Save
# ---------------------------------------------------------------------------

STAGE_IDS = {"white_note": "n-9201", "blue_note": "n-9202", "two_role_note": "n-9203"}
STAGE_PROFILE = {"type": "profile_updated", "displayName": "Lina Park",
                 "title": "City life editor Stage makeup editor", "bio": BIO}
STAGE_LIKE = {"type": "note_like_toggled", "noteId": "n-3003", "authorHandle": "lena_27", "active": True}
STAGE_SAVE = {"type": "note_save_toggled", "noteId": "n-3003", "authorHandle": "lena_27", "active": True}


def _stage_state(covers, payloads):
    return {
        "notes": [
            {"id": "n-3003", "authorHandle": "lena_27", "category": "Beauty",
             "title": "Friday cushion foundation with one shade too peachy"},
            *(_note(stage, group, covers, note_id) for group, note_id in STAGE_IDS.items()),
        ],
        "users": [{"handle": "lina", "title": "City life editor Stage makeup editor"}],
        "userState": {"lina": {"likedNoteIds": ["n-3003"], "savedNoteIds": ["n-3003"]}},
        "evaluationEvents": _events(payloads),
    }


def _stage_brief_run():
    """All three notes, then the Like/Save before the profile (the brief orders neither)."""
    return [
        _created(stage, "two_role_note", STAGE_IDS["two_role_note"]),
        _created(stage, "white_note", STAGE_IDS["white_note"]),
        _feed("profile", "", "lina", 33),
        _created(stage, "blue_note", STAGE_IDS["blue_note"]),
        _feed(category="Beauty", total=41),
        {"type": "note_detail_opened", "noteId": "n-3003"},
        STAGE_SAVE,
        STAGE_LIKE,
        _feed("profile", "", "lina", 35),
        STAGE_PROFILE,
    ]


def test_870344_brief_faithful_run_in_another_order_passes(synthetic_covers):
    result = STAGE.evaluate_state(_stage_state(synthetic_covers, _stage_brief_run()), boundary=BOUNDARY)
    assert result.status.value == "PASS", result.metadata["failures"]
    assert _check(result)["actual"]["order_violations"] == []


def test_870344_profile_update_before_the_last_note_fails(synthetic_covers):
    run = _stage_brief_run()
    run.remove(STAGE_PROFILE)
    run.insert(1, STAGE_PROFILE)  # after the first note, before white/blue
    result = STAGE.evaluate_state(_stage_state(synthetic_covers, run), boundary=BOUNDARY)
    assert _failed(result) == {CHECK}
    assert _check(result)["actual"]["order_violations"] == [
        ["white_note_created", "profile_updated"],
        ["blue_note_created", "profile_updated"],
    ]


def test_870344_like_before_any_note_fails(synthetic_covers):
    run = _stage_brief_run()
    run.remove(STAGE_LIKE)
    run.insert(0, STAGE_LIKE)
    result = STAGE.evaluate_state(_stage_state(synthetic_covers, run), boundary=BOUNDARY)
    assert _failed(result) == {CHECK}
    assert len(_check(result)["actual"]["order_violations"]) == 3


def test_870344_duplicate_note_or_wrong_role_fails(synthetic_covers):
    duplicate = _stage_brief_run() + [_created(stage, "white_note", STAGE_IDS["white_note"])]
    result = STAGE.evaluate_state(_stage_state(synthetic_covers, duplicate), boundary=BOUNDARY)
    assert _failed(result) == {CHECK}

    wrong = _stage_state(synthetic_covers, _stage_brief_run())
    wrong["users"][0]["title"] = "City life editor Stage makeup"
    assert "profile_role_exact" in _failed(STAGE.evaluate_state(wrong, boundary=BOUNDARY))
