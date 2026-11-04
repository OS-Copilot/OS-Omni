"""Windows OpenTwitter: "the first post" of an Explore stream is the post the app listed first.

The fixture mirrors the shipped build (C:\\OS-Omni\\Apps\\OpenTwitter\\resources\\app.asar):
``SEED_POSTS`` are records of its ``shared/seed-data.json`` in their stored (newest first) order,
and ``_App`` follows ``server.js``: ``filterPosts`` keeps a post when
``[text, topic, author.displayName, author.handle]`` contains the query, new posts are unshifted
to the front, repost/like/save toggle, and ``alex`` starts with p-1005 liked and p-1001 saved.
"""

from __future__ import annotations

import copy

import pytest

from evaluators.windows import opentwitter_explore as explore
from evaluators.windows.opentwitter_v1_content_billing_596978 import (
    RULESET_SPEC as V1_SPEC,
    OpenTwitterV1ContentBilling596978Evaluator as V1,
)
from evaluators.windows.opentwitter_v2_accessibility_performance_231082 import (
    RULESET_SPEC as V2_SPEC,
    OpenTwitterV2AccessibilityPerformance231082Evaluator as V2,
)
from evaluators.windows.opentwitter_v3_support_roadmap_976928 import (
    RULESET_SPEC as V3_SPEC,
    OpenTwitterV3SupportRoadmap976928Evaluator as V3,
)

USERS = {
    "alex": "Alex Chen", "maya": "Maya Patel", "jamal": "Jamal Reed", "priya": "Priya Shah",
    "elena": "Elena Rossi", "hana": "Hana Kim", "amina": "Amina Okafor",
}
SEED_POSTS = [
    ("p-alex-2001", "alex", "Product", "Launch history note: consolidated product checklist, pricing review, and support owner into one release thread."),
    ("p-alex-2002", "alex", "Launch", "Saved the customer impact summary beside the rollout plan so support can answer without opening three docs."),
    ("p-alex-2003", "alex", "Content", "Updated social copy after the access review. The shorter version says what changed, who gets it, and where to switch it on."),
    ("p-alex-2004", "alex", "Product", "Product recap: notification cleanup is ready, billing export copy is still open, and the mobile draft restore issue stays blocked."),
    ("p-1001", "maya", "Design", "The new accessibility audit template is ready. It now separates keyboard traps, focus order, color contrast, and copy clarity into review lanes."),
    ("p-1007", "jamal", "Frontend", "A tiny frontend win: delaying non-critical chart hydration made the first paint feel instant on older laptops."),
    ("p-1010", "priya", "Security", "Security review reminder: every export button needs the same permission check as the page that generated the data."),
    ("p-alex-2010", "alex", "Search", "Reviewed profile history behavior. Older posts should still be findable by topic search, not only by scrolling."),
    ("p-1016", "elena", "Mobile", "Mobile release candidate is stable after the notification tap fix. The remaining blocker is a flaky offline draft restore test."),
    ("p-1018", "hana", "AI Products", "Assistant rollout plan update: we are testing answer citations, handoff points, and refusal copy before expanding beyond the pilot group."),
    ("p-1020", "amina", "Community", "Community launch prep is more than scheduling posts. We need reply templates, known issue links, and one owner for escalations."),
]
SETS = {"repost": "reposted", "like": "liked", "bookmark": "bookmarked"}
TYPES = {"repost": "post_repost_toggled", "like": "post_like_toggled", "bookmark": "post_bookmark_toggled"}


class _App:
    def __init__(self) -> None:
        self.users = {handle: {"handle": handle, "displayName": name, "bio": ""} for handle, name in USERS.items()}
        self.posts = [{"id": i, "authorHandle": a, "topic": t, "text": x} for i, a, t, x in SEED_POSTS]
        self.liked, self.reposted, self.bookmarked = ["p-1005"], [], ["p-1001"]
        self.events: list[dict] = []
        self.messages: list[dict] = []
        self.notifications = [{"id": "n1", "read": False}, {"id": "n2", "read": False}]

    def record(self, kind: str, **payload) -> None:
        self.events.append({"seq": len(self.events) + 1, "type": kind, "timestamp": "t", **payload})

    def login(self) -> None:
        self.record("session_login_success", handle="alex")

    def publish(self, text: str) -> str:
        post_id = f"p-new-{len(self.events)}"
        self.posts.insert(0, {"id": post_id, "authorHandle": "alex", "topic": "Updates", "text": text})
        self.record("post_created", postId=post_id, text=text, topic="Updates")
        return post_id

    def stream(self, query: str) -> list[str]:
        needle = query.lower()
        ids = [
            post["id"] for post in self.posts
            if needle in " ".join([post["text"], post["topic"], self.users[post["authorHandle"]]["displayName"], post["authorHandle"]]).lower()
        ]
        self.record("timeline_view", view="explore", query=query, handle="", total=len(ids))
        return ids

    def toggle(self, post_id: str, action: str) -> None:
        bucket = getattr(self, SETS[action])
        active = post_id in bucket
        bucket.remove(post_id) if active else bucket.append(post_id)
        self.record(TYPES[action], postId=post_id, authorHandle="x", active=not active)

    def is_active(self, post_id: str, action: str) -> bool:
        return post_id in getattr(self, SETS[action])

    def finish(self, spec: dict) -> dict:
        for row in spec["messages"]:
            self.messages.append({"handle": row["handle"], "text": row["text"], "outbound": True})
            self.record("message_sent", handle=row["handle"], text=row["text"])
        for row in self.notifications:
            row["read"] = True
        self.record("notifications_marked_read")
        self.rename(spec["profile"]["displayName"], spec["profile"]["bio"])
        self.record("timeline_view", view="profile", query="", handle="alex", total=0)
        return self.state()

    def rename(self, name: str, bio: str) -> None:
        self.users["alex"].update(displayName=name, bio=bio)
        self.record("profile_updated", displayName=name, bio=bio, avatar="")

    def state(self) -> dict:
        return {
            "events": copy.deepcopy(self.events),
            "session": {"loggedIn": True, "user": {"handle": "alex", "email": "alex@opentwitter.local"}},
            "likedPostIds": list(self.liked), "repostedPostIds": list(self.reposted), "bookmarkedPostIds": list(self.bookmarked),
            "currentUser": dict(self.users["alex"]),
            "posts": [{**post, "author": dict(self.users[post["authorHandle"]])} for post in self.posts],
            "messages": copy.deepcopy(self.messages), "notifications": copy.deepcopy(self.notifications),
            "bootstrap": {"trends": [
                {"label": "Support macros 01", "category": "Policy", "query": "Support"},
                {"label": "Roadmap notes 01", "category": "Policy", "query": "Product"},
                {"label": "Customer updates 02", "category": "Policy", "query": "Support"},
                {"label": "Community replies", "category": "Community", "query": "Community"},
            ]},
        }


def _run(spec: dict, pick=None, click=None) -> tuple[dict, list[str]]:
    """One in-order episode; ``pick`` chooses the post of a stream, ``click`` the buttons to press."""
    app = _App()
    app.login()
    for text in spec["posts"]:
        app.publish(text)
    engaged = []
    for label in spec["trend_queries"]:
        query = spec["trend_runtime_queries"][label]
        ids = app.stream(query)
        post_id = pick(app, label, ids) if pick else ids[0]
        engaged.append(post_id)
        for action in (click(app, label, post_id) if click else [a for a in SETS if not app.is_active(post_id, a)]):
            app.toggle(post_id, action)
            app.stream(query)  # the client refetches the stream after each toggle
    return app.finish(spec), engaged


def _failed(evaluator, state) -> list[str]:
    result = evaluator.evaluate_state(state)
    return list(result.metadata["failed_checks"])


def test_seed_fixture_streams_match_the_shipped_build():
    app = _App()
    assert app.stream("Mobile")[:2] == ["p-alex-2004", "p-1016"]
    assert app.stream("Product")[:2] == ["p-alex-2001", "p-alex-2004"]
    assert app.stream("Support")[:2] == ["p-alex-2001", "p-alex-2002"]
    assert [app.stream(q)[0] for q in ("Security", "Frontend", "AI Products", "Community", "Search", "Design", "Content", "Launch")] == [
        "p-1010", "p-1007", "p-1018", "p-1020", "p-alex-2010", "p-1001", "p-alex-2003", "p-alex-2001"]


def test_v2_mobile_stream_first_post_is_alex_product_recap():
    state, engaged = _run(V2_SPEC)
    assert engaged[3] == "p-alex-2004"
    assert _failed(V2, state) == []


def test_v2_engaging_the_second_mobile_post_fails():
    state, engaged = _run(V2_SPEC, pick=lambda app, label, ids: "p-1016" if label == "Mobile release candidate" else ids[0])
    assert engaged[3] == "p-1016"
    assert set(_failed(V2, state)) == {"opentwitter.accessibility.trend_mobile_release_candidate", "opentwitter.accessibility.business_order"}


def test_v3_streams_two_and_three_list_the_already_engaged_post_first():
    state, engaged = _run(V3_SPEC)
    assert engaged == ["p-alex-2001", "p-alex-2001", "p-alex-2001", "p-1020"]
    assert _failed(V3, state) == []
    trend = next(c for c in V3.evaluate_state(state).metadata["checks"] if c["name"] == "opentwitter.support.trend_roadmap_notes")
    assert trend["actual"]["matching_post"]["id"] == "p-alex-2001"
    assert trend["actual"]["already_active_at_view"] == dict.fromkeys(explore.ACTIONS, True)


def test_v3_engaging_the_next_unengaged_post_still_passes():
    def next_unengaged(app, label, ids):
        return next(i for i in ids if not all(app.is_active(i, a) for a in SETS))
    state, engaged = _run(V3_SPEC, pick=next_unengaged)
    assert engaged == ["p-alex-2001", "p-alex-2004", "p-alex-2002", "p-1020"]
    assert _failed(V3, state) == []


def _clicks(undo_in: tuple[str, ...]):
    def click(app, label, post_id):
        if label in undo_in:
            return list(SETS)  # press all three buttons even though they are already active
        if label == "Customer updates 02":
            return []
        return [a for a in SETS if not app.is_active(post_id, a)]
    return click


def test_v3_clicking_the_engaged_post_again_undoes_it_and_fails():
    failed = _failed(V3, _run(V3_SPEC, click=_clicks(("Roadmap notes 01",)))[0])
    assert {"opentwitter.support.trend_support_macros", "opentwitter.support.trend_roadmap_notes",
            "opentwitter.support.trend_customer_updates"} <= set(failed)


def test_v3_toggling_off_then_on_again_ends_engaged_and_passes():
    state, _ = _run(V3_SPEC, click=lambda app, label, post_id: list(SETS) if label != "Community replies" and label != "Support macros 01" else
                    [a for a in SETS if not app.is_active(post_id, a)])
    assert _failed(V3, state) == []


def test_v3_stream_must_be_opened_after_the_previous_one():
    app = _App()
    app.login()
    for text in V3_SPEC["posts"]:
        app.publish(text)
    app.stream("Support")
    for action in SETS:
        app.toggle("p-alex-2001", action)
    app.stream("Support")  # "Customer updates 02" opened, but "Roadmap notes 01" never was
    app.stream("Community")
    for action in SETS:
        app.toggle("p-1020", action)
    failed = _failed(V3, app.finish(V3_SPEC))
    assert "opentwitter.support.trend_roadmap_notes" in failed
    assert "opentwitter.support.trend_support_macros" not in failed


def test_final_display_name_does_not_rewrite_the_stream_the_agent_saw():
    # "Alex Support" contains the query "Support"; at the view the account was still Alex Chen.
    state, _ = _run(V3_SPEC)
    assert state["currentUser"]["displayName"] == "Alex Support"
    view = next(e for e in state["events"] if e.get("query") == "Support")
    stream, deleted = explore.stream_at(state["posts"], state["events"], "Support", view["seq"])
    assert deleted == []
    assert stream[0]["id"] == "p-alex-2001"
    assert explore.stream_at(state["posts"], state["events"], "Support", 10 ** 6)[0][0]["text"] == "Triage notes ready"


def test_v1_preseeded_save_needs_no_toggle():
    state, engaged = _run(V1_SPEC)
    assert engaged[1] == "p-1001"
    assert _failed(V1, state) == []


def test_v1_clicking_save_on_the_preseeded_post_unsaves_it_and_fails():
    state, _ = _run(V1_SPEC, click=lambda app, label, post_id: list(SETS))
    assert "opentwitter.content_billing.trend_incident_drills" in _failed(V1, state)


@pytest.mark.parametrize("reading", ["own_post_listed_first", "first_post_before_the_agent_posted"])
def test_v1_content_stream_accepts_both_readings_of_first_post(reading):
    def pick(app, label, ids):
        if label == "Feature naming 01" and reading == "first_post_before_the_agent_posted":
            return "p-alex-2003"
        return ids[0]
    state, engaged = _run(V1_SPEC, pick=pick)
    assert engaged[2] == ("p-alex-2003" if reading.startswith("first_post_before") else next(
        p["id"] for p in state["posts"] if p["text"] == "Content owner ready"))
    assert _failed(V1, state) == []


def test_active_at_derives_the_seed_state_from_final_state_and_toggles():
    events = [{"seq": 5, "type": "post_bookmark_toggled", "postId": "p-1001", "active": False}]
    assert explore.active_at(events, "p-1001", "post_bookmark_toggled", 3, final_active=False) is True
    assert explore.active_at(events, "p-1001", "post_bookmark_toggled", 6, final_active=False) is False
    assert explore.active_at([], "p-1007", "post_like_toggled", 3, final_active=False) is False


def test_deleted_matching_post_makes_the_stream_unreadable():
    app = _App()
    app.login()
    own = app.publish("Mobile handoff note")
    app.stream("Mobile")
    app.posts = [post for post in app.posts if post["id"] != own]
    app.record("post_deleted", postId=own, text="Mobile handoff note", topic="Updates")
    state = app.state()
    view = next(e for e in state["events"] if e.get("query") == "Mobile")
    assert explore.stream_at(state["posts"], state["events"], "Mobile", view["seq"])[1] == [own]


@pytest.mark.parametrize("module_name,stem", [
    ("evaluators.windows.opentwitter_v1_content_billing_596978", "opentwitter_v1_content_billing_596978"),
    ("evaluators.windows.opentwitter_v2_accessibility_performance_231082", "opentwitter_v2_accessibility_performance_231082"),
    ("evaluators.windows.opentwitter_v3_support_roadmap_976928", "opentwitter_v3_support_roadmap_976928"),
])
def test_ruleset_digest_is_the_spec_and_the_live_task_binds_it(module_name, stem):
    import hashlib
    import importlib
    import json
    from pathlib import Path

    import yaml

    module = importlib.import_module(module_name)
    digest = hashlib.sha256(json.dumps(module.RULESET_SPEC, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert module.RULESET_SHA256 == digest
    task = yaml.safe_load((Path(__file__).resolve().parents[1] / "tasks/v1/windows" / f"{stem}.yaml").read_text(encoding="utf8"))
    assert task["evaluation"]["params"]["expected_ruleset_sha256"] == digest
