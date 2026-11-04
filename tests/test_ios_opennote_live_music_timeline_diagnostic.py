"""iOS OpenNote live-music task: business events are graded, not the recorded suffix.

scan row IOS-030. The brief fixes the final profile role, the three notes and
the two engagements; it states no event count, order, navigation or timestamp
spacing. The old 19-event exact suffix (seed feed totals, contiguous seqs,
strictly increasing timestamps) is replaced by the gating
durable_events_and_required_order check: every requested business event
exactly once (an identical profile re-save counts once), no other business
event, browsing not counted, and no required order. The stated deliverables
themselves stay strict.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from evaluators.ios import opennote_live_music_visuals_three_notes_495011 as mod

CLS = mod.OpenNoteLiveMusicVisualsThreeNotes495011Evaluator
REPO = Path(__file__).resolve().parents[1]
NOTE_IDS = {"blue_green_note": "n-new-1", "live_music_note": "n-new-2", "curly_note": "n-new-3"}
PROFILE_VIEW = {"type": "feed_view", "view": "profile", "query": "", "category": "", "tag": "",
                "handle": "lina", "total": 99}
EXPLORE_VIEW = {"type": "feed_view", "view": "home", "query": "", "category": "Fashion", "tag": "",
                "handle": "", "total": 7}


def _groups() -> dict:
    groups = {
        "profile_role": {"match_count": 1, "profile": {"handle": "lina", "title": "City life editor Live music editor"}},
    }
    for group, note in mod._NOTE_EXPECTED.items():
        groups[group] = {
            "match_count": 1,
            "note": {"id": NOTE_IDS[group], **copy.deepcopy(note)},
            "application_build": copy.deepcopy(mod.EXPECTED_BUILD),
        }
    for name, predicate in (("drew_engagement", mod.drew_engagement_exact_predicate),
                            ("rain_engagement", mod.rain_engagement_exact_predicate)):
        _passed, expected, _actual, _reason = predicate({"groups": {}})
        groups[name] = copy.deepcopy(expected)
    return groups


def _business(label: str) -> dict:
    return copy.deepcopy(mod._expected_business_events({"groups": _groups()})[label])


# Engagements first, notes in reverse, the profile last, with extra profile and
# Explore views and several events sharing one timestamp.
OTHER_ORDER = [
    EXPLORE_VIEW, "rain_jacket_save", "rain_jacket_like", "drew_follow", EXPLORE_VIEW,
    "secondhand_coat_like", "curly_note_created", PROFILE_VIEW, "live_music_note_created",
    "blue_green_note_created", PROFILE_VIEW, "profile_updated",
]


def _evidence(items=OTHER_ORDER) -> dict:
    suffix = []
    for offset, item in enumerate(items):
        payload = _business(item) if isinstance(item, str) else copy.deepcopy(item)
        stamp = f"2026-11-04T10:00:{min(offset, 5):02d}Z"
        suffix.append({"seq": 40 + offset, "timestamp": stamp, **payload})
    return {
        "groups": _groups(),
        "event_suffix": suffix,
        "boundary": {"mode": "automatic_baseline_seq", "baseline_max_event_seq": 39},
    }


def _check(result):
    return next(c for c in result.metadata["checks"] if c["name"] == "durable_events_and_required_order")


def test_final_state_passes_with_a_different_event_suffix():
    result = CLS.evaluate_evidence(_evidence())
    assert result.status.value == "PASS", result.metadata["failures"]
    check = _check(result)
    assert check["diagnostic"] is False and check["passed"] is True
    assert "timeline_exact" not in mod.CHECKPOINTS


def test_identical_profile_resave_counts_once():
    result = CLS.evaluate_evidence(_evidence(OTHER_ORDER + ["profile_updated"]))
    assert result.status.value == "PASS", result.metadata["failures"]


def test_missing_business_events_fail_without_any_opt_in():
    result = CLS.evaluate_evidence(_evidence([PROFILE_VIEW]))
    assert result.metadata["failures"] == ["durable_events_and_required_order"]
    assert len(_check(result)["actual"]["missing"]) == 8


def test_duplicate_or_unexpected_business_event_fails():
    duplicate = CLS.evaluate_evidence(_evidence(OTHER_ORDER + ["curly_note_created"]))
    assert duplicate.metadata["failures"] == ["durable_events_and_required_order"]
    assert _check(duplicate)["actual"]["extra"] == ["curly_note_created"]

    other_like = {"type": "note_like_toggled", "noteId": "n-3002", "authorHandle": "theo_11", "active": True}
    unexpected = CLS.evaluate_evidence(_evidence(OTHER_ORDER + [other_like]))
    assert unexpected.metadata["failures"] == ["durable_events_and_required_order"]

    unliked = {**_business("rain_jacket_like"), "active": False}
    toggled = CLS.evaluate_evidence(_evidence(OTHER_ORDER + [unliked, "rain_jacket_like"]))
    assert toggled.metadata["failures"] == ["durable_events_and_required_order"]


def test_stated_deliverables_stay_strict():
    for mutate, failure in (
        (lambda g: g["profile_role"]["profile"].__setitem__("title", "City life editor"), "profile_role_exact"),
        (lambda g: g["live_music_note"]["note"].__setitem__("location", "Media zone"), "live_music_note_exact"),
        (lambda g: g["curly_note"].__setitem__("match_count", 2), "curly_note_exact"),
        (lambda g: g["drew_engagement"]["target_note"].__setitem__("followed", False), "drew_engagement_exact"),
        (lambda g: g["rain_engagement"]["target_note"].__setitem__("saved", False), "rain_engagement_exact"),
    ):
        raw = _evidence()
        mutate(raw["groups"])
        result = CLS.evaluate_evidence(raw)
        assert result.status.value == "FAIL"
        assert result.metadata["failures"] == [failure]


def test_task_binds_the_updated_ruleset():
    doc = yaml.safe_load(
        (REPO / "tasks/v1/ios/opennote_live_music_visuals_three_notes_495011.yaml").read_text(encoding="utf-8")
    )
    assert doc["evaluation"]["params"]["expected_ruleset_sha256"] == mod.RULESET_SHA256
    assert doc["metadata"]["verifier_rules"]["ruleset_sha256"] == mod.RULESET_SHA256
