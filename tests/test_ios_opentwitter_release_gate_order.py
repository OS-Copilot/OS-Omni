"""iOS OpenTwitter 245250: per-post engagement lists are enumerations, not sequences.

The brief lists each post's engagements in a different order ("a like, a reply
..., a save, and a repost"; "a save, a repost, a reply ..., and a like"), and
"the first/second/third new post" are labels. Its only stated order is "..., then
mark all notifications as read" / "upon completion"; a created post logically
exists before it is engaged. Every required business event exactly once.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from evaluators.ios import opentwitter_release_gate_engagement_245250 as rel
from tests.test_ios_opentwitter_brief_event_order import _state

RELEASE = rel.OpenTwitterReleaseGateEngagement245250Evaluator
REPO = Path(__file__).resolve().parents[1]
IDS = {"release gate": "post-rg", "build status": "post-bs", "rollout plan": "post-rp"}
B, R, L, C = "post_bookmark_toggled", "post_repost_toggled", "post_like_toggled", "comment_created"
MARK = ("notifications_marked_read",)


def _brief_faithful_other_order():
    """Seed posts first, then the new posts in reverse, reply first on every post."""
    return [
        (C, "p-1005", "launch checks clear"), (R, "p-1005", True), (B, "p-1005", True),
        (C, "p-alex-2004", "notify gate clear"), (L, "p-alex-2004", True), (R, "p-alex-2004", True),
        (C, "p-alex-2009", "archive owner set"), (B, "p-alex-2009", True), (L, "p-alex-2009", True),
        (C, "p-alex-2005", "empty state fixed"), (R, "p-alex-2005", True), (B, "p-alex-2005", True),
        (C, "p-1016", "mobile gate ready"), (L, "p-1016", True), (B, "p-1016", True), (R, "p-1016", True),
        (C, "p-1003", "release lane clear"), (R, "p-1003", True), (L, "p-1003", True), (B, "p-1003", True),
        ("post_created", "rollout plan"), (C, "rollout plan", "mobile ready"),
        (B, "rollout plan", True), (L, "rollout plan", True), (R, "rollout plan", True),
        ("post_created", "build status"), (C, "build status", "smoke passed"),
        (L, "build status", True), (B, "build status", True), (R, "build status", True),
        ("post_created", "release gate"), (C, "release gate", "deploy note"),
        (R, "release gate", True), (B, "release gate", True), (L, "release gate", True),
        MARK,
    ]


def _release_state(items):
    created = set(IDS.values())
    return _state(
        rel, items, created_ids=IDS,
        liked={"p-1005", "p-1003", "p-1016", "p-alex-2009", "p-alex-2004"} | created,
        bookmarked={"p-1001", "p-1003", "p-1016", "p-alex-2005", "p-alex-2009", "p-1005"} | created,
        reposted={"p-1003", "p-1016", "p-alex-2005", "p-alex-2004", "p-1005"} | created,
    )


def _failures(result):
    return set(result.metadata["failures"])


def _order_check(result):
    return next(c for c in result.metadata["checks"] if c["name"] == "durable_events_and_required_order")


def test_recorded_demo_order_still_passes():
    result = RELEASE.evaluate_state(_release_state(rel._expected_events()))
    assert result.status.value == "PASS", result.metadata["failures"]


def test_brief_faithful_run_in_another_order_passes():
    items = _brief_faithful_other_order()
    assert items != rel._expected_events()
    result = RELEASE.evaluate_state(_release_state(items))
    assert result.status.value == "PASS", result.metadata["failures"]


def test_an_extra_early_mark_all_read_is_idempotent():
    result = RELEASE.evaluate_state(_release_state([MARK] + _brief_faithful_other_order()))
    assert result.status.value == "PASS", result.metadata["failures"]


def test_marking_notifications_read_before_finishing_fails():
    items = _brief_faithful_other_order()
    items.remove(MARK)
    items.insert(len(items) - 1, MARK)
    result = RELEASE.evaluate_state(_release_state(items))
    assert _failures(result) == {"durable_events_and_required_order"}
    assert _order_check(result)["actual"]["order_violations"] == [
        [[L, "release gate", True], list(MARK)]
    ]


def test_duplicate_reply_or_unlike_event_fails():
    duplicate = _brief_faithful_other_order()
    duplicate.insert(0, (C, "p-1005", "launch checks clear"))
    result = RELEASE.evaluate_state(_release_state(duplicate))
    assert "durable_events_and_required_order" in _failures(result)
    assert _order_check(result)["actual"]["extra"] == [[C, "p-1005", "launch checks clear"]]

    toggled_off_and_on = _brief_faithful_other_order()
    toggled_off_and_on[1:1] = [(L, "p-1003", True), (L, "p-1003", False)]
    result = RELEASE.evaluate_state(_release_state(toggled_off_and_on))
    assert "durable_events_and_required_order" in _failures(result)


def test_missing_engagement_or_wrong_final_set_fails():
    missing = [item for item in _brief_faithful_other_order() if item != (B, "p-1003", True)]
    state = _release_state(missing)
    result = RELEASE.evaluate_state(state)
    assert "durable_events_and_required_order" in _failures(result)

    state = _release_state(_brief_faithful_other_order())
    state["userStateByHandle"]["alex"]["likedPostIds"].remove("p-1003")
    assert "likedPostIds_exact" in _failures(RELEASE.evaluate_state(state))


def test_task_binds_the_updated_ruleset():
    doc = yaml.safe_load(
        (REPO / "tasks/v1/ios/opentwitter_release_gate_engagement_245250.yaml").read_text(encoding="utf-8")
    )
    assert doc["evaluation"]["params"]["expected_ruleset_sha256"] == rel.RULESET_SHA256
    assert doc["metadata"]["evaluator_ruleset_sha256"] == rel.RULESET_SHA256
