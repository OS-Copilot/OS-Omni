"""macOS OpenTwitter Alex workflows: brief-named searches are deliverables.

The ordered event ledger stays a non-blocking diagnostic (no brief states an
order between the searches, replies, posts and messages).  Where a brief asks
for the search itself -- "found via the query Community launch", "by searching
for security review", "the Explore search area must yield four distinct result
sets for the queries ..." -- each named query must have run at least once, at
any position and any number of times.  The control-guide brief names no
search, so it requires none.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from evaluators.cua_review.core.evaluation import EvalStatus

ROOT = Path(__file__).resolve().parents[1]
TASKS = {
    "community_handoff": "opentwitter_alex_community_handoff_social_workflow",
    "control_guide": "opentwitter_alex_control_guide_runbook_workflow",
    "launch_audit": "opentwitter_alex_launch_audit_social_workflow",
    "security_closure": "opentwitter_alex_security_closure_social_workflow",
}
SEARCH_TASKS = ["community_handoff", "launch_audit", "security_closure"]


def _task(name: str) -> dict:
    return yaml.safe_load((ROOT / "tasks/v1/macos" / f"{TASKS[name]}.yaml").read_text(encoding="utf-8"))


def _evaluator(task: dict):
    module_name, class_name = task["evaluation"]["evaluator_id"].split(":")
    return getattr(importlib.import_module(module_name), class_name)()


class _Controller:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    def run_python_script(self, code: str, timeout: int = 35) -> dict[str, Any]:
        return {"returncode": 0, "stdout": json.dumps({"port": 4350, "state": self.state})}


def _state(params: dict, *, searches: list[str]) -> dict[str, Any]:
    """A correct durable final state; the ledger holds only the given searches
    (after the login), followed by the business events in reverse brief order."""
    handle = params["expected_handle"]
    posts: list[dict[str, Any]] = []
    comments: dict[str, list[dict[str, Any]]] = {}
    liked: set[str] = set()
    reposted: set[str] = set()
    bookmarked: set[str] = set()
    business: list[dict[str, Any]] = []
    for source in params["expected_source_posts"]:
        post_id = source["post_id"]
        posts.append({"id": post_id, "authorHandle": source["author_handle"], "text": source["text_contains"] + " ..."})
        if source.get("reply"):
            comments[post_id] = [{"authorHandle": handle, "text": source["reply"]}]
            business.append({"type": "comment_created", "postId": post_id, "text": source["reply"]})
        for key, ids in (("liked", liked), ("reposted", reposted), ("bookmarked", bookmarked)):
            if source.get(key):
                ids.add(post_id)
    for index, created in enumerate(params["expected_created_posts"]):
        post_id = f"p-new-{index}"
        posts.append({"id": post_id, "authorHandle": handle, "text": created["text"]})
        business.append({"type": "post_created", "text": created["text"]})
        for key, ids in (("liked", liked), ("reposted", reposted), ("bookmarked", bookmarked)):
            if created.get(key):
                ids.add(post_id)
    messages = [
        {"handle": item["handle"], "text": item["text"], "outbound": True} for item in params["expected_messages"]
    ]
    business.extend({"type": "message_sent", "handle": m["handle"], "text": m["text"]} for m in messages)
    business.append({"type": "profile_updated", "bio": params["expected_bio"]})
    business.append({"type": "notifications_marked_read"})
    events = [
        {"type": "session_login_success", "handle": handle},
        *({"type": "timeline_view", "view": "explore", "query": query} for query in searches),
        *business[::-1],
    ]
    return {
        "posts": posts,
        "comments": comments,
        "events": events,
        "messages": messages,
        "notifications": [{"id": "n1", "read": True}, {"id": "n2", "read": True}],
        "likedPostIds": sorted(liked),
        "repostedPostIds": sorted(reposted),
        "bookmarkedPostIds": sorted(bookmarked),
        "session": {"loggedIn": True, "user": {"handle": handle, "displayName": params["expected_name"]}},
        "currentUser": {"handle": handle, "displayName": params["expected_name"], "bio": params["expected_bio"]},
    }


def _run(task: dict, state: dict[str, Any]):
    params = task["evaluation"]["params"]
    observation = SimpleNamespace(
        foreground_app="OpenTwitter",
        foreground_bundle_id="local.osomni.opentwitter",
        ui_nodes=[{"text": marker} for marker in params["expected_final_ui_markers"]],
    )
    return _evaluator(task).evaluate(
        {"controller": _Controller(state), "params": dict(params), "final_observation": observation}
    )


def _failed(result) -> list[str]:
    return [check["check_id"] for check in result.metadata["checks"] if not check["passed"]]


@pytest.mark.parametrize("name", SEARCH_TASKS)
def test_searches_in_another_order_and_repeated_pass(name: str) -> None:
    task = _task(name)
    params = task["evaluation"]["params"]
    assert params["require_search_queries"] is True
    queries = list(params["expected_search_queries"])
    # Reverse order, odd casing/spacing, one query searched twice.
    searches = [f"  {query.upper()} " for query in queries[::-1]] + [queries[0]]
    result = _run(task, _state(params, searches=searches))

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]
    ordered = next(d for d in result.metadata["diagnostics"] if d["diagnostic_id"] == "ordered_business_events")
    assert ordered["blocking"] is False
    assert ordered["passed"] is False  # the demo ledger order was not followed, and that is fine


@pytest.mark.parametrize("name", SEARCH_TASKS)
def test_a_brief_named_search_that_never_ran_fails(name: str) -> None:
    task = _task(name)
    params = task["evaluation"]["params"]
    queries = list(params["expected_search_queries"])
    result = _run(task, _state(params, searches=queries[1:]))

    assert result.status == EvalStatus.FAIL
    assert _failed(result) == [f"search_query_{queries[0]}"]


def test_control_guide_brief_names_no_search_and_requires_none() -> None:
    task = _task("control_guide")
    params = task["evaluation"]["params"]
    assert not params.get("require_search_queries")
    result = _run(task, _state(params, searches=[]))

    assert result.status == EvalStatus.PASS, result.metadata["failure_reasons"]


@pytest.mark.parametrize("name", sorted(TASKS))
def test_duplicate_reply_still_fails(name: str) -> None:
    task = _task(name)
    params = task["evaluation"]["params"]
    state = _state(params, searches=list(params["expected_search_queries"]))
    post_id, replies = next(iter(state["comments"].items()))
    replies.append(dict(replies[0]))
    result = _run(task, state)

    assert result.status == EvalStatus.FAIL
    assert _failed(result) == [f"source_post_{post_id}_reply"]
