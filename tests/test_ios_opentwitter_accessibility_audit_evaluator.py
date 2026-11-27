"""Semantic regression checks for the OpenTwitter accessibility audit task."""

from __future__ import annotations

from copy import deepcopy

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.ios.opentwitter_accessibility_audit_engagement_567657 import (
    OpenTwitterAccessibilityAuditEngagement567657Evaluator,
)


def _correct_reference_state() -> dict:
    # Independent terminal-state reference from the model-visible task request.
    authored = {
        "access audit": "focus fixes",
        "contrase pass": "labels clear",
        "screen review": "keyboard path",
    }
    seeds = {
        "p-1001": ("maya", "The new accessibility audit template is ready. It now separates keyboard traps, focus order, color contrast, and copy clarity into review lanes.", "access thread set"),
        "p-1013": ("maya", "Design critique prompt for today: what would this screen look like if every label were half as long?", "focus map ready"),
        "p-alex-2003": ("alex", "Updated social copy after the access review. The shorter version says what changed, who gets it, and where to switch it on.", "copy access clear"),
        "p-alex-2012": ("alex", "Access review summary is in the product brief. Export buttons, billing downloads, and admin invites all need explicit owner checks.", "owner audit set"),
        "p-alex-2011": ("alex", "Support macro pass: removed vague language, added exact setting names, and linked the help article directly.", "audit trail clear"),
        "p-1012": ("iris", "Docs that start with the expected final state are easier to follow than docs that start with every possible option.", "focus ring clear"),
    }
    posts = [
        {"id": post_id, "authorHandle": author, "text": text}
        for post_id, (author, text, _) in seeds.items()
    ]
    comments = {
        post_id: [{"id": f"reply-{post_id}", "authorHandle": "alex", "text": reply}]
        for post_id, (_, _, reply) in seeds.items()
    }
    for index, (text, reply) in enumerate(authored.items(), 1):
        post_id = f"new-{index}"
        posts.append({"id": post_id, "authorHandle": "alex", "text": text})
        comments[post_id] = [{"id": f"reply-{post_id}", "authorHandle": "alex", "text": reply}]
    return {
        "posts": posts,
        "comments": comments,
        "userStateByHandle": {
            "alex": {
                "likedPostIds": ["p-1005", "p-1001", "p-1013", "p-alex-2003", "p-alex-2012", "p-alex-2011", "p-1012", "new-1", "new-2", "new-3"],
                "bookmarkedPostIds": ["p-1001", "p-1013", "p-alex-2003", "p-alex-2012", "p-alex-2011", "new-1", "new-2", "new-3"],
                "repostedPostIds": ["p-1001", "p-1013", "p-alex-2003", "p-alex-2012", "p-alex-2011", "new-1", "new-2", "new-3"],
            }
        },
        "session": {"loggedIn": True, "user": {"handle": "alex"}},
        # The task requires these final-state effects, not a hidden global action order.
        "evaluationEvents": [],
    }


def test_correct_terminal_state_passes_without_global_event_order() -> None:
    state = _correct_reference_state()
    state["evaluationEvents"] = [{"type": "comment_created", "text": "arbitrary audit ordering"}]
    result = OpenTwitterAccessibilityAuditEngagement567657Evaluator.evaluate_state(state)
    assert result.status == EvalStatus.PASS


def test_wrong_reply_and_missing_engagement_fail() -> None:
    state = deepcopy(_correct_reference_state())
    state["comments"]["p-1001"][0]["text"] = "access thread wrong"
    state["userStateByHandle"]["alex"]["likedPostIds"].remove("p-1013")
    result = OpenTwitterAccessibilityAuditEngagement567657Evaluator.evaluate_state(state)
    assert result.status == EvalStatus.FAIL
    failures = set(result.metadata["failures"])
    assert "seed_post_p-1001_exact" in failures
    assert "likedPostIds_exact" in failures


def test_unfinished_initial_state_fails() -> None:
    state = _correct_reference_state()
    state["posts"] = [post for post in state["posts"] if post["id"].startswith("p-")]
    state["comments"] = {}
    state["userStateByHandle"]["alex"] = {
        "likedPostIds": ["p-1005"],
        "bookmarkedPostIds": ["p-1001"],
        "repostedPostIds": [],
    }
    result = OpenTwitterAccessibilityAuditEngagement567657Evaluator.evaluate_state(state)
    assert result.status == EvalStatus.FAIL
