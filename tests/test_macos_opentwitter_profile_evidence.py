"""macOS OpenTwitter: a bio saved without a profile_updated event is still credited.

Shipped OpenTwitter builds re-submitted the seeded avatar path on save, so the
server stored the new name/bio and then rejected the request before recording
``profile_updated``.  PASS/FAIL already comes from the stored ``currentUser``;
the ordered-event diagnostic now also credits that persisted state instead of
reporting the profile step as missing.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.macos.opentwitter_alex_community_handoff_social_workflow import (
    OpenTwitterAlexCommunityHandoffEvaluator,
)
from evaluators.macos.opentwitter_alex_launch_audit_social_workflow import (
    OpenTwitterAlexLaunchAuditEvaluator,
)

PARAMS = OpenTwitterAlexCommunityHandoffEvaluator.TASK_PARAMS


class _Controller:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    def run_python_script(self, code: str, timeout: int = 35) -> dict[str, Any]:
        return {"returncode": 0, "stdout": json.dumps({"port": 4350, "state": self.state})}


def _state(*, bio: str, record_profile_event: bool) -> dict[str, Any]:
    handle = PARAMS["expected_handle"]
    posts: list[dict[str, Any]] = []
    comments: dict[str, list[dict[str, Any]]] = {}
    liked: set[str] = set()
    reposted: set[str] = set()
    bookmarked: set[str] = set()
    for source in PARAMS["expected_source_posts"]:
        post_id = source["post_id"]
        posts.append({"id": post_id, "authorHandle": source["author_handle"], "text": source["text_contains"] + " ..."})
        if source.get("reply"):
            comments[post_id] = [{"authorHandle": handle, "text": source["reply"]}]
        for key, ids in (("liked", liked), ("reposted", reposted), ("bookmarked", bookmarked)):
            if source.get(key):
                ids.add(post_id)
    for index, created in enumerate(PARAMS["expected_created_posts"]):
        post_id = f"p-new-{index}"
        posts.append({"id": post_id, "authorHandle": handle, "text": created["text"]})
        for key, ids in (("liked", liked), ("reposted", reposted), ("bookmarked", bookmarked)):
            if created.get(key):
                ids.add(post_id)
    events = [
        dict(item)
        for item in PARAMS["expected_event_sequence"]
        if record_profile_event or item["type"] != "profile_updated"
    ]
    return {
        "posts": posts,
        "comments": comments,
        "events": events,
        "messages": [
            {"handle": item["handle"], "text": item["text"], "outbound": True}
            for item in PARAMS["expected_messages"]
        ],
        "notifications": [{"id": "n1", "read": True}, {"id": "n2", "read": True}],
        "likedPostIds": sorted(liked),
        "repostedPostIds": sorted(reposted),
        "bookmarkedPostIds": sorted(bookmarked),
        "session": {"loggedIn": True, "user": {"handle": handle, "displayName": PARAMS["expected_name"]}},
        "currentUser": {"handle": handle, "displayName": PARAMS["expected_name"], "bio": bio},
    }


def _final_observation() -> SimpleNamespace:
    return SimpleNamespace(
        foreground_app="OpenTwitter",
        foreground_bundle_id="local.osomni.opentwitter",
        ui_nodes=[{"text": marker} for marker in PARAMS["expected_final_ui_markers"]],
    )


def _evaluate(state: dict[str, Any]):
    return OpenTwitterAlexCommunityHandoffEvaluator().evaluate(
        {"controller": _Controller(state), "params": {}, "final_observation": _final_observation()}
    )


def _diagnostic(result) -> dict[str, Any]:
    return next(
        item for item in result.metadata["diagnostics"] if item["diagnostic_id"] == "ordered_business_events"
    )


def test_persisted_bio_without_profile_event_passes_and_is_credited() -> None:
    result = _evaluate(_state(bio=PARAMS["expected_bio"], record_profile_event=False))

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]
    diagnostic = _diagnostic(result)
    assert diagnostic["passed"] is True
    assert diagnostic["blocking"] is False
    assert diagnostic["observed"]["satisfied_by_persisted_state"] == [
        {"type": "profile_updated", "bio": PARAMS["expected_bio"]}
    ]


def test_recorded_profile_event_is_matched_normally() -> None:
    result = _evaluate(_state(bio=PARAMS["expected_bio"], record_profile_event=True))

    assert result.status == EvalStatus.PASS
    assert _diagnostic(result)["observed"]["satisfied_by_persisted_state"] == []


@pytest.mark.parametrize("record_profile_event", [False, True])
def test_wrong_stored_bio_still_fails(record_profile_event: bool) -> None:
    result = _evaluate(_state(bio="Tracking product launches", record_profile_event=record_profile_event))

    assert result.status == EvalStatus.FAIL
    assert any("bio" in reason for reason in result.metadata["failure_reasons"])
    if not record_profile_event:
        diagnostic = _diagnostic(result)
        assert diagnostic["passed"] is False
        assert diagnostic["observed"]["missing_expected_event"]["type"] == "profile_updated"


def test_launch_audit_copy_credits_persisted_profile_in_default_sequence() -> None:
    events = [{"type": "session_login_success", "handle": "alex"}, {"type": "notifications_marked_read"}]
    sequence = [
        {"type": "session_login_success", "handle": "alex"},
        {"type": "profile_updated", "bio": "Launch notes owner"},
        {"type": "notifications_marked_read"},
    ]
    matched = OpenTwitterAlexLaunchAuditEvaluator._match_ordered_events(
        events,
        sequence,
        persisted_profile={"handle": "alex", "bio": "Launch notes owner"},
    )
    assert matched["passed"] is True
    assert matched["matched_events"][1]["evidence"] == "persisted_profile_state"

    unmatched = OpenTwitterAlexLaunchAuditEvaluator._match_ordered_events(events, sequence)
    assert unmatched["passed"] is False
