"""Windows OpenNote: a step that names a seeded note only by a title several seeded notes share.

In the shipped seed (C:\\OS-Omni\\Apps\\OpenNote\\resources\\app.asar, shared/seed-data.json) the
Food column has three notes titled "A half-day version of picnic boxes that works for a slow
afternoon" (n-3024 freya_60, n-3046 lina, n-3420 noah_16) and Fashion has two titled "shoe
pairings: small changes that keeps the whole closet simpler" (n-3001 drew_49, n-3188 ada_41).
The steps give no other mark, so any one of them is the note they name.
"""

from __future__ import annotations

import pytest

from evaluators.windows import opennote_community_meal_three_notes_1788409691786_981937 as meal
from evaluators.windows import opennote_live_music_visuals_three_notes_1788411372670_327795 as music

PICNIC = "A half-day version of picnic boxes that works for a slow afternoon"
SHOES = "shoe pairings: small changes that keeps the whole closet simpler"


class _Store:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.notes: list[dict] = []
        self.saved: list[str] = []
        self.liked: list[str] = []
        self.following: list[str] = []

    def record(self, kind: str, **payload) -> int:
        self.events.append({"seq": len(self.events) + 1, "timestamp": "t", "type": kind, **payload})
        return len(self.events)

    def seed(self, note_id: str, author: str, title: str, category: str) -> None:
        self.notes.append({"id": note_id, "authorHandle": author, "title": title, "category": category})

    def toggle(self, kind: str, bucket: list[str], note_id: str, author: str) -> None:
        self.record("note_detail_opened", noteId=note_id)
        bucket.append(note_id)
        self.record(kind, noteId=note_id, authorHandle=author, active=True)

    def publish(self, note_id: str, expected: dict) -> None:
        self.notes.append({"id": note_id, **{k: expected[k] for k in ("authorHandle", "title", "text", "category", "tags", "location", "cover")}})
        self.record("note_created", noteId=note_id, title=expected["title"], category=expected["category"], tags=expected["tags"])

    def raw(self, module, profile: dict, build: dict) -> dict:
        notes = module.EXPECTED_NOTES
        return {
            "state": {
                "events": self.events, "notes": self.notes, "savedNoteIds": self.saved, "likedNoteIds": self.liked,
                "following": self.following,
                "session": {"loggedIn": True, "user": {"handle": "lina", "displayName": "Lina Park", "email": "lina@opennote.local"}},
                "currentUser": profile,
            },
            "assets": {row["cover"]: row["cover_content"] for row in notes.values()},
            "build": build, "task_id": module.TASK_ID, "instruction_sha256": module.INSTRUCTION_SHA256,
            "ruleset_sha256": module.RULESET_SHA256,
        }


def _meal_run(picnic_saves: list[tuple[str, str]]) -> dict:
    store = _Store()
    for note_id, author, title in [("n-3343", "cole_51", meal.RULESET_SPEC["bakery_save"]["title"]),
                                   ("n-3211", "nora_02", meal.RULESET_SPEC["picnic_like"]["title"]),
                                   ("n-3024", "freya_60", PICNIC), ("n-3046", "lina", PICNIC), ("n-3420", "noah_16", PICNIC),
                                   ("n-3100", "theo_11", "Another Food note")]:
        store.seed(note_id, author, title, "Food")
    food = {"view": "home", "category": "Food", "query": "", "tag": "", "handle": ""}
    store.record("session_login_success", handle="lina")
    store.record("feed_view", **food)
    store.toggle("note_save_toggled", store.saved, "n-3343", "cole_51")
    store.publish("n-orange", meal.EXPECTED_NOTES["orange_note"])
    store.record("feed_view", **food)
    store.toggle("note_like_toggled", store.liked, "n-3211", "nora_02")
    for note_id, author in picnic_saves:
        store.toggle("note_save_toggled", store.saved, note_id, author)
    profile = {k: meal.RULESET_SPEC["profile"][k] for k in ("handle", "displayName", "title", "bio")}
    store.record("profile_updated", displayName=profile["displayName"], title=profile["title"], bio=profile["bio"])
    store.publish("n-blue", meal.EXPECTED_NOTES["blue_note"])
    store.publish("n-plan", meal.EXPECTED_NOTES["meal_plan"])
    return meal.evaluate_state(store.raw(meal, profile, meal.EXPECTED_BUILD), "fresh_clone_verified")


@pytest.mark.parametrize("note_id,author", [("n-3024", "freya_60"), ("n-3046", "lina"), ("n-3420", "noah_16")])
def test_community_meal_accepts_any_same_titled_picnic_note(note_id, author):
    verdict = _meal_run([(note_id, author)])
    assert verdict["status"] == "PASS", verdict["failures"]
    picnic = next(c for c in verdict["checks"] if c["check_id"] == "picnic_engagement_exact")
    assert picnic["actual"]["save_note_id"] == note_id


@pytest.mark.parametrize("saves", [[], [("n-3100", "theo_11")]])
def test_community_meal_still_requires_a_picnic_note_saved(saves):
    verdict = _meal_run(saves)
    assert verdict["status"] == "FAIL"
    assert {"picnic_engagement_exact", "workflow_timeline_exact"} <= set(verdict["failures"])


def test_community_meal_ruleset_binding_matches_task_yaml():
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for folder in ("tasks/v1/windows",):
        for module, stem in ((meal, "opennote_community_meal_three_notes_1788409691786_981937"),
                             (music, "opennote_live_music_visuals_three_notes_1788411372670_327795")):
            task = yaml.safe_load((root / folder / f"{stem}.yaml").read_text(encoding="utf8"))
            assert task["evaluation"]["params"]["expected_ruleset_sha256"] == module.RULESET_SHA256


def _music_run(follow: tuple[str, str], like: tuple[str, str]) -> dict:
    store = _Store()
    for note_id, author, title in [("n-3001", "drew_49", SHOES), ("n-3188", "ada_41", SHOES),
                                   ("n-3419", "lina", music.RULESET_SPEC["seasonal"]["title"])]:
        store.seed(note_id, author, title, "Fashion")
    store.record("session_login_success", handle="lina")
    profile = {k: music.RULESET_SPEC["profile"][k] for k in ("handle", "displayName", "title", "bio")}
    store.record("profile_updated", displayName=profile["displayName"], title=profile["title"], bio=profile["bio"])
    store.publish("n-guitar", music.EXPECTED_NOTES["blue_green_note"])
    store.record("note_detail_opened", noteId=follow[0])
    store.following.append(follow[1])
    store.record("follow_toggled", handle=follow[1], active=True)
    store.toggle("note_like_toggled", store.liked, *like)
    store.publish("n-visuals", music.EXPECTED_NOTES["live_music_note"])
    store.record("feed_view", view="home", query="", category="Fashion", tag="", handle="")
    store.toggle("note_like_toggled", store.liked, "n-3419", "lina")
    store.publish("n-curly", music.EXPECTED_NOTES["curly_note"])
    return music.evaluate_state(store.raw(music, profile, music.BUILD), "fresh_clone_verified")


@pytest.mark.parametrize("note_id,author", [("n-3001", "drew_49"), ("n-3188", "ada_41")])
def test_live_music_accepts_either_same_titled_shoe_note(note_id, author):
    verdict = _music_run((note_id, author), (note_id, author))
    assert verdict["status"] == "PASS", verdict["failures"]


def test_live_music_follow_and_like_must_be_on_the_same_note():
    verdict = _music_run(("n-3001", "drew_49"), ("n-3188", "ada_41"))
    assert "drew_engagement_exact" in verdict["failures"]
