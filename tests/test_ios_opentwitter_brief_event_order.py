"""iOS OpenTwitter 451238 / 483271: grade what the English brief asks, in the order it states.

451238: the brief says "Save, like, and repost" the Runbooks post, and its only
stated order is Devon Brooks' post being saved, reposted and liked "then" replied to.
483271: the only stated order is the creation order of the three new posts.
"""

from __future__ import annotations

from evaluators.ios import opentwitter_incident_engagement_profile_451238 as inc
from evaluators.ios import opentwitter_transit_signal_engagement_483271 as tra

INCIDENT = inc.OpenTwitterIncidentEngagementProfile451238Evaluator
TRANSIT = tra.OpenTwitterTransitSignalEngagement483271Evaluator


def _event(item, ids, comment_ids):
    kind = item[0]
    if kind == "notifications_marked_read":
        return {"type": kind}
    if kind == "post_created":
        return {"type": kind, "postId": ids[item[1]], "text": item[1]}
    if kind == "comment_created":
        post_id = ids.get(item[1], item[1])
        return {"type": kind, "postId": post_id, "text": item[2],
                "commentId": comment_ids[(post_id, item[2])]}
    if kind == "profile_updated":
        return {"type": kind, "displayName": item[1], "bio": item[2], "avatar": item[3]}
    return {"type": kind, "postId": ids.get(item[1], item[1]), "active": item[2]}


def _state(module, items, *, created_ids, liked, bookmarked, reposted, extra=None):
    comments = {}
    comment_ids = {}
    for item in items:
        if item[0] == "comment_created":
            post_id = created_ids.get(item[1], item[1])
            comment_id = f"cm-{len(comment_ids) + 1}"
            comment_ids[(post_id, item[2])] = comment_id
            comments.setdefault(post_id, []).append(
                {"id": comment_id, "authorHandle": "alex", "text": item[2]}
            )
    posts = [
        {"id": post_id, "authorHandle": spec["authorHandle"], "text": spec["text"]}
        for post_id, spec in module.SEED_POSTS.items()
    ] + [
        {"id": post_id, "authorHandle": "alex", "text": text}
        for text, post_id in created_ids.items()
    ]
    events = [
        {**_event(item, created_ids, comment_ids), "seq": seq}
        for seq, item in enumerate(items, start=1)
    ]
    state = {
        "session": {"loggedIn": True, "user": {"handle": "alex"}},
        "posts": posts,
        "comments": comments,
        "users": [{"handle": "alex", "displayName": "Alex Incident", "bio": "incident owner", "avatar": ""}],
        "userStateByHandle": {
            "alex": {
                "likedPostIds": sorted(liked),
                "bookmarkedPostIds": sorted(bookmarked),
                "repostedPostIds": sorted(reposted),
                "notifications": [{"id": "n-1", "read": True}, {"id": "n-2", "read": True}],
            }
        },
        "evaluationEvents": events + list(extra or []),
    }
    return state


def _failures(result):
    return set(result.metadata["failures"])


# ---------------------------------------------------------------------------
# 451238 incident engagement
# ---------------------------------------------------------------------------

INC_IDS = {"incident brief": "post-ib", "risk ledger": "post-rl", "service recap": "post-sr"}
B, R, L, C = "post_bookmark_toggled", "post_repost_toggled", "post_like_toggled", "comment_created"


def _inc_brief_order(mark_first=True, devon=None, runbooks=None):
    devon = devon or [(B, "p-1002", True), (R, "p-1002", True), (L, "p-1002", True),
                      (C, "p-1002", "incident owner")]
    runbooks = runbooks or [(B, "p-1014", True), (L, "p-1014", True), (R, "p-1014", True),
                            (C, "p-1014", "runbook owner set")]
    body = devon + runbooks + [
        ("post_created", "incident brief"), (B, "incident brief", True), (R, "incident brief", True),
        (L, "incident brief", True), (C, "incident brief", "owner update"),
        ("post_created", "risk ledger"), (R, "risk ledger", True), (B, "risk ledger", True),
        (L, "risk ledger", True), (C, "risk ledger", "impact noted"),
        ("post_created", "service recap"), (L, "service recap", True), (B, "service recap", True),
        (R, "service recap", True), (C, "service recap", "next check"),
        (B, "p-1009", True), (L, "p-1009", True), (R, "p-1009", True), (C, "p-1009", "owner path clear"),
        (R, "p-alex-2006", True), (L, "p-alex-2006", True), (B, "p-alex-2006", True),
        (C, "p-alex-2006", "status owner next"),
        (B, "p-1010", True), (L, "p-1010", True),
        ("profile_updated", "Alex Incident", "incident owner", ""),
    ]
    mark = [("notifications_marked_read",)]
    return mark + body if mark_first else body + mark


def _inc_state(items, *, bookmarked=None, reposted=None):
    created = set(INC_IDS.values())
    return _state(
        inc, items, created_ids=INC_IDS,
        liked=inc.EXPECTED_LIKED_STATIC | created,
        bookmarked=(bookmarked if bookmarked is not None else inc.EXPECTED_BOOKMARKED_STATIC) | created,
        reposted=(reposted if reposted is not None else inc.EXPECTED_REPOSTED_STATIC) | created,
    )


def test_incident_brief_faithful_run_passes():
    result = INCIDENT.evaluate_state(_inc_state(_inc_brief_order()))
    assert result.status.value == "PASS", result.metadata["failures"]


def test_incident_marking_notifications_read_last_or_twice_passes():
    last = INCIDENT.evaluate_state(_inc_state(_inc_brief_order(mark_first=False)))
    twice = INCIDENT.evaluate_state(
        _inc_state(_inc_brief_order() + [("notifications_marked_read",)])
    )
    assert last.status.value == "PASS", last.metadata["failures"]
    assert twice.status.value == "PASS", twice.metadata["failures"]


def test_incident_runbooks_must_be_saved_and_reposted():
    like_and_reply_only = [(L, "p-1014", True), (C, "p-1014", "runbook owner set")]
    state = _inc_state(
        _inc_brief_order(runbooks=like_and_reply_only),
        bookmarked=inc.EXPECTED_BOOKMARKED_STATIC - {"p-1014"},
        reposted=inc.EXPECTED_REPOSTED_STATIC - {"p-1014"},
    )
    assert _failures(INCIDENT.evaluate_state(state)) == {
        "bookmarked_post_ids_exact", "reposted_post_ids_exact", "durable_events_and_required_order",
    }


def test_incident_devon_reply_must_follow_the_three_toggles():
    reply_first = [(B, "p-1002", True), (C, "p-1002", "incident owner"),
                   (R, "p-1002", True), (L, "p-1002", True)]
    result = INCIDENT.evaluate_state(_inc_state(_inc_brief_order(devon=reply_first)))
    assert _failures(result) == {"durable_events_and_required_order"}
    check = next(c for c in result.metadata["checks"] if c["name"] == "durable_events_and_required_order")
    assert len(check["actual"]["order_violations"]) == 2


def test_incident_other_posts_may_reply_before_toggles():
    items = _inc_brief_order()
    index = items.index((C, "p-1009", "owner path clear"))
    items.insert(items.index((B, "p-1009", True)), items.pop(index))
    result = INCIDENT.evaluate_state(_inc_state(items))
    assert result.status.value == "PASS", result.metadata["failures"]


def test_incident_toggle_off_and_on_is_a_duplicate():
    items = _inc_brief_order() + [(L, "p-1010", False), (L, "p-1010", True)]
    assert _failures(INCIDENT.evaluate_state(_inc_state(items))) == {"durable_events_and_required_order"}


# ---------------------------------------------------------------------------
# 483271 transit engagement
# ---------------------------------------------------------------------------

TRA_IDS = {"transit pulse": "post-tp", "sensor trend": "post-st", "route update": "post-ru"}


def _tra_brief_order(creation=("transit pulse", "sensor trend", "route update")):
    return [
        (B, "p-1006", True), (R, "p-1006", True), (C, "p-1006", "city signal clear"),
        (R, "p-1007", True), (B, "p-1007", True), (C, "p-1007", "chart paint stable"),
        (L, "p-1008", True), (R, "p-1008", True), (C, "p-1008", "coast trend held"),
        *[("post_created", text) for text in creation],
        (B, "route update", True), (R, "route update", True), (L, "route update", True),
        (C, "route update", "mobile route"),
        (R, "transit pulse", True), (B, "transit pulse", True), (L, "transit pulse", True),
        (C, "transit pulse", "map delay"),
        (L, "sensor trend", True), (R, "sensor trend", True), (B, "sensor trend", True),
        (C, "sensor trend", "coast stable"),
        (R, "p-1016", True), (B, "p-1016", True), (L, "p-1016", True),
        (C, "p-1016", "route gate stable"),
        (L, "p-1032", True), (B, "p-1032", True), (R, "p-1032", True),
        (C, "p-1032", "archive signal set"),
        (B, "p-1066", True),
    ]


def _tra_state(items, extra=None):
    created = set(TRA_IDS.values())
    sets = tra.EXPECTED_STATIC_ENGAGEMENTS
    return _state(
        tra, items, created_ids=TRA_IDS,
        liked=sets["likedPostIds"] | created,
        bookmarked=sets["bookmarkedPostIds"] | created,
        reposted=sets["repostedPostIds"] | created,
        extra=extra,
    )


def test_transit_brief_faithful_run_passes():
    result = TRANSIT.evaluate_state(_tra_state(_tra_brief_order()))
    assert result.status.value == "PASS", result.metadata["failures"]


def test_transit_source_step_order_still_passes():
    items = [_ for _ in tra._expected_events()]
    result = TRANSIT.evaluate_state(_tra_state(items))
    assert result.status.value == "PASS", result.metadata["failures"]


def test_transit_wrong_creation_order_fails():
    items = _tra_brief_order(creation=("sensor trend", "transit pulse", "route update"))
    assert _failures(TRANSIT.evaluate_state(_tra_state(items))) == {"durable_events_and_required_order"}


def test_transit_unrequested_engagement_inside_the_window_fails():
    items = _tra_brief_order()
    items.insert(5, (L, "p-1006", True))
    assert "durable_events_and_required_order" in _failures(TRANSIT.evaluate_state(_tra_state(items)))


def test_transit_missing_required_event_fails():
    items = [item for item in _tra_brief_order() if item != (B, "p-1066", True)]
    assert "durable_events_and_required_order" in _failures(TRANSIT.evaluate_state(_tra_state(items)))
