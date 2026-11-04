"""Android OpenTwitter: only the orders the English instruction states are graded.

Each test replays a list of business actions through a small model of the app (the
state document plus its ``evaluationEvents``), in the order a run performed them,
and grades the result with the task's own evaluator and YAML parameters.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.cua_review.platforms.android.opentwitter_support import stated_order_check

ROOT = Path(__file__).resolve().parents[1]
HANDLE = "alex"
START = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)


def _task(stem: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / "tasks/v1/android" / f"{stem}.yaml").read_text(encoding="utf-8"))


class _App:
    """Applies business actions the way OpenTwitter records them."""

    def __init__(self, seed_posts: list[dict[str, Any]]):
        self.clock = 0
        self.seq = 0
        self.posts = [dict(post) for post in seed_posts]
        self.comments: dict[str, list[dict[str, Any]]] = {}
        self.sets = {"like": [], "repost": [], "bookmark": []}
        self.following: list[str] = []
        self.messages: list[dict[str, Any]] = []
        self.notifications = [{"id": "n-1", "read": False}, {"id": "n-2", "read": False}]
        self.events: list[dict[str, Any]] = []

    def _now(self) -> str:
        self.clock += 7
        return (START + timedelta(seconds=self.clock)).isoformat().replace("+00:00", "Z")

    def _event(self, kind: str, at: str, **fields: Any) -> None:
        self.seq += 1
        self.events.append({"seq": self.seq, "type": kind, "timestamp": at, **fields})

    def post_id(self, ref: str) -> str:
        if ref.startswith("post:"):
            text = ref[5:]
            return next(p["id"] for p in self.posts if p["authorHandle"] == HANDLE and p["text"] == text)
        return ref

    def author(self, post_id: str) -> str:
        return next(p["authorHandle"] for p in self.posts if p["id"] == post_id)

    def apply(self, action: tuple[Any, ...]) -> None:
        kind, *args = action
        at = self._now()
        if kind in ("like", "repost", "bookmark"):
            post_id = self.post_id(args[0])
            self.sets[kind].append(post_id)
            self._event(f"post_{kind}_toggled", at, postId=post_id, authorHandle=self.author(post_id), active=True)
        elif kind == "unlike":
            post_id = self.post_id(args[0])
            self.sets["like"].remove(post_id)
            self._event("post_like_toggled", at, postId=post_id, authorHandle=self.author(post_id), active=False)
        elif kind == "comment":
            post_id = self.post_id(args[0])
            comment = {"id": f"c-{self.seq}", "authorHandle": HANDLE, "text": args[1], "createdAt": at}
            self.comments.setdefault(post_id, []).append(comment)
            self._event("comment_created", at, postId=post_id, commentId=comment["id"], text=args[1])
        elif kind == "post":
            post = {"id": f"p-new-{self.seq}", "authorHandle": HANDLE, "text": args[0], "createdAt": at}
            self.posts.insert(0, post)
            self._event("post_created", at, postId=post["id"], text=args[0])
        elif kind == "message":
            message = {"id": f"m-{self.seq}", "handle": args[0], "text": args[1], "createdAt": at, "outbound": True}
            self.messages.insert(0, message)
            self._event("message_sent", at, handle=args[0], text=args[1])
        elif kind == "follow":
            self.following.append(args[0])
            self._event("user_follow_toggled", at, handle=args[0], active=True)
        elif kind == "read_all":
            for row in self.notifications:
                row["read"] = True
            self._event("notifications_marked_read", at)
        elif kind == "view":  # browsing: recorded by the app, never graded
            self._event("timeline_view", at, view="explore", query=args[0])
        else:
            raise ValueError(kind)

    def state(self) -> dict[str, Any]:
        return {
            "session": {"loggedIn": True, "user": {"handle": HANDLE}},
            "posts": self.posts,
            "comments": self.comments,
            "userStateByHandle": {
                HANDLE: {
                    "following": self.following,
                    "likedPostIds": self.sets["like"],
                    "repostedPostIds": self.sets["repost"],
                    "bookmarkedPostIds": self.sets["bookmark"],
                    "messages": self.messages,
                    "notifications": self.notifications,
                }
            },
            "evaluationEvents": self.events,
            "evaluationEventSeq": self.seq,
        }


def _run(stem: str, seed_posts: list[dict[str, Any]], actions: list[tuple[Any, ...]], dom: dict[str, Any]):
    task = _task(stem)
    params = task["evaluation"]["params"]
    module_name, class_name = task["evaluation"]["evaluator_id"].split(":")
    module = importlib.import_module(module_name)
    app = _App(seed_posts)
    for action in actions:
        app.apply(action)
    state = app.state()

    class _Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def read_state_read_only(self) -> dict[str, Any]:
            return state

        def read_state(self) -> dict[str, Any]:
            return state

    patched = [module]
    if stem == "opentwitter_05_security_billing_api_audit":
        patched = [importlib.import_module(
            "evaluators.cua_review.evaluators.android.opentwitter_mobile_incident_frontend_audit")]
    return _evaluate(patched, module, class_name, params, _Store, dom)


def _evaluate(patched, module, class_name, params, store, dom):
    mp = pytest.MonkeyPatch()
    try:
        for target in patched:
            for attr in ("OpenShopAndroidStore", "OpenTwitterAndroidStore"):
                if hasattr(target, attr):
                    mp.setattr(target, attr, store)
            for value in vars(target).values():
                if isinstance(value, type) and "_read_dom_state" in vars(value):
                    mp.setattr(value, "_read_dom_state", staticmethod(lambda controller, package: dom))

        class _Controller:
            def execute_adb(self, args: Any) -> str:
                return ""

        return getattr(module, class_name)().evaluate({
            "controller": _Controller(),
            "params": params,
            "final_observation": SimpleNamespace(foreground_bundle_id=params["app_package"]),
        })
    finally:
        mp.undo()


def _failures(result) -> list[str]:
    return [item if isinstance(item, str) else item["check"] for item in result.metadata["failures"]]


def _order_check(result) -> dict[str, Any]:
    return next(check for check in result.metadata["checks"] if check["name"] == "instruction_stated_order")


def _seed(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": s["id"], "authorHandle": s["author_handle"], "text": s.get("text", "seed")} for s in specs]


def _engage(spec: dict[str, Any], reply: str | None = None) -> list[tuple[Any, ...]]:
    acts: list[tuple[Any, ...]] = [(action, spec["id"]) for action in spec.get("actions") or []]
    return acts + [("comment", spec["id"], reply or spec["reply_text"])]


# ----------------------------------------------------------------- 01 release review
T01 = "opentwitter_01_release_review_coordination"
P01 = _task(T01)["evaluation"]["params"]
DOM01 = {"view": "home", "body_text": "Home\nOwners aligned.\nSaved"}
HANA, PRIYA_POST, ELENA = P01["target_posts"]
MSG01 = {m["handle"]: ("message", m["handle"], m["text"]) for m in P01["messages"]}


def _owner01() -> list[tuple[Any, ...]]:
    return [("comment", "post:Owners aligned.", "Next steps assigned"), ("bookmark", "post:Owners aligned.")]


def _demo01() -> list[tuple[Any, ...]]:
    return (
        [("view", "AI Products")] + _engage(HANA) + [("view", "Security")] + _engage(PRIYA_POST)
        + [MSG01["priya"], MSG01["lina"], MSG01["hana"], ("post", "Review notes ready."), ("post", "Owners aligned.")]
        + [("view", "Mobile")] + _engage(ELENA) + [("read_all",), MSG01["devon"]] + _owner01()
    )


def test_01_demo_order_passes():
    result = _run(T01, _seed(P01["target_posts"]), _demo01(), DOM01)
    assert result.status is EvalStatus.PASS, _failures(result)


def test_01_different_but_valid_order_passes():
    # Posts first, Devon's message and the read-all before everything, the trends in
    # reverse, no browsing at all: only Priya < Lina < Hana and Review < Owners stay.
    actions = (
        [("read_all",), MSG01["devon"], ("post", "Review notes ready.")] + _engage(ELENA)
        + [MSG01["priya"], ("post", "Owners aligned.")] + _owner01() + _engage(PRIYA_POST)
        + [MSG01["lina"]] + _engage(HANA) + [MSG01["hana"]]
    )
    result = _run(T01, _seed(P01["target_posts"]), actions, DOM01)
    assert result.status is EvalStatus.PASS, _failures(result)
    assert _order_check(result)["passed"]


def test_01_brief_stated_message_order_violated_fails():
    actions = _demo01()
    i, j = actions.index(MSG01["priya"]), actions.index(MSG01["lina"])
    actions[i], actions[j] = actions[j], actions[i]
    result = _run(T01, _seed(P01["target_posts"]), actions, DOM01)
    assert _failures(result) == ["instruction_stated_order"]
    violation = _order_check(result)["observed"]["violations"][0]
    assert (violation["before"], violation["after"]) == ("message:priya", "message:lina")


def test_01_brief_stated_post_order_violated_fails():
    actions = _demo01()
    i, j = actions.index(("post", "Review notes ready.")), actions.index(("post", "Owners aligned."))
    actions[i], actions[j] = actions[j], actions[i]
    result = _run(T01, _seed(P01["target_posts"]), actions, DOM01)
    assert _failures(result) == ["instruction_stated_order"]


def test_01_duplicate_or_misdirected_business_action_fails():
    duplicate = _run(T01, _seed(P01["target_posts"]), _demo01() + [MSG01["lina"]], DOM01)
    assert "message_lina_exact_unique" in _failures(duplicate)
    wrong = [("message", "maya", MSG01["hana"][2]) if a == MSG01["hana"] else a for a in _demo01()]
    result = _run(T01, _seed(P01["target_posts"]), wrong, DOM01)
    assert "message_hana_exact_unique" in _failures(result)
    assert "message:hana" in _order_check(result)["observed"]["unresolved"]


# ----------------------------------------------------------------- 03 release / search
T03 = "opentwitter_03_research_search_coordination"
P03 = _task(T03)["evaluation"]["params"]
DOM03 = {"view": "messages", "body_text": "Messages\nNora Fields\nRecap link is live"}
SEED03 = _seed([P03["research_post"], P03["target_post"]])
MSG03 = [("message", m["handle"], m["text"]) for m in P03["messages"]]
OWNER03 = [("comment", "post:Release brief ready", "Brief link is live")] + [
    (action, "post:Release brief ready") for action in ("like", "bookmark", "repost")
]


def _demo03() -> list[tuple[Any, ...]]:
    return (
        _engage(P03["research_post"]) + [("follow", "rachel")] + _engage(P03["target_post"]) + MSG03[:3]
        + [("post", "Release brief ready"), ("post", "Search owner added")] + OWNER03 + [("read_all",), MSG03[3]]
    )


def test_03_demo_and_reordered_runs_pass():
    assert _run(T03, SEED03, _demo03(), DOM03).status is EvalStatus.PASS
    # Messages in reverse, read-all first, the owner post's actions in another order.
    actions = (
        [("read_all",)] + list(reversed(MSG03)) + [("post", "Release brief ready"), ("post", "Search owner added")]
        + list(reversed(OWNER03)) + _engage(P03["target_post"]) + [("follow", "rachel")] + _engage(P03["research_post"])
    )
    result = _run(T03, SEED03, actions, DOM03)
    assert result.status is EvalStatus.PASS, _failures(result)


def test_03_owner_post_engaged_before_both_posts_are_published_fails():
    actions = _demo03()
    second = actions.index(("post", "Search owner added"))
    like = ("like", "post:Release brief ready")
    actions.remove(like)
    actions.insert(second, like)  # liked between the two posts
    result = _run(T03, SEED03, actions, DOM03)
    assert _failures(result) == ["instruction_stated_order"]
    assert _order_check(result)["observed"]["violations"][0]["after"] == "like:Release brief ready"


def test_03_relike_after_both_posts_counts():
    actions = _demo03()
    second = actions.index(("post", "Search owner added"))
    actions.insert(second, ("like", "post:Release brief ready"))
    actions.insert(second + 1, ("unlike", "post:Release brief ready"))
    result = _run(T03, SEED03, actions, DOM03)
    assert result.status is EvalStatus.PASS, _failures(result)


def test_03_posts_in_reverse_order_fail():
    actions = _demo03()
    i, j = actions.index(("post", "Release brief ready")), actions.index(("post", "Search owner added"))
    actions[i], actions[j] = actions[j], actions[i]
    assert "instruction_stated_order" in _failures(_run(T03, SEED03, actions, DOM03))


# ----------------------------------------------------------------- 04 mobile incident
T04 = "opentwitter_04_mobile_incident_frontend_audit"
P04 = _task(T04)["evaluation"]["params"]
DOM04 = {"view": "messages", "active_message_handle": "priya", "message_thread_open": True,
         "body_text": "Priya Shah\nMobile audit filed."}
MSG04 = {m["handle"]: ("message", m["handle"], m["text"]) for m in P04["messages"]}
OWNER04 = [("comment", "post:Mobile gate ready.", "Release owner Elena,"),
           ("like", "post:Mobile gate ready."), ("bookmark", "post:Mobile gate ready.")]


def _demo04() -> list[tuple[Any, ...]]:
    a, b, c = P04["target_posts"]
    return (
        _engage(a) + _engage(b) + [MSG04["maya"], MSG04["devon"], MSG04["ben"]]
        + [("post", "Mobile gate ready."), ("post", "Runbook owner set.")] + _engage(c) + [("read_all",)]
        + OWNER04 + [MSG04["priya"]]
    )


def test_04_reordered_run_passes_and_event_sequence_param_is_gone():
    assert "event_sequence" not in P04
    a, b, c = P04["target_posts"]
    actions = (
        [MSG04["priya"], ("post", "Mobile gate ready.")] + OWNER04 + [MSG04["maya"], ("read_all",)] + _engage(c)
        + [("post", "Runbook owner set."), MSG04["devon"]] + _engage(b) + [MSG04["ben"]] + _engage(a)
    )
    result = _run(T04, _seed(P04["target_posts"]), actions, DOM04)
    assert result.status is EvalStatus.PASS, _failures(result)


def test_04_message_order_violated_fails():
    actions = _demo04()
    i, j = actions.index(MSG04["devon"]), actions.index(MSG04["ben"])
    actions[i], actions[j] = actions[j], actions[i]
    result = _run(T04, _seed(P04["target_posts"]), actions, DOM04)
    assert _failures(result) == ["instruction_stated_order"]


# ----------------------------------------------------------------- 05 security / billing (no stated order)
T05 = "opentwitter_05_security_billing_api_audit"
P05 = _task(T05)["evaluation"]["params"]


def test_05_any_order_passes_because_the_brief_states_none():
    assert "event_sequence" not in P05 and "stated_order" not in P05
    owner = [("comment", "post:Export audit ready", "Owners signed off"),
             ("like", "post:Export audit ready"), ("bookmark", "post:Export audit ready")]
    posts = [("post", spec["text"]) for spec in P05["created_posts"]]
    messages = [("message", m["handle"], m["text"]) for m in P05["messages"]]
    engagements = [act for spec in P05["target_posts"] for act in _engage(spec)]
    actions = [("read_all",)] + list(reversed(posts)) + owner + list(reversed(messages)) + list(reversed(engagements))
    result = _run(T05, _seed(P05["target_posts"]), actions, {"view": "notifications", "body_text": "Notifications"})
    assert result.status is EvalStatus.PASS, _failures(result)


# ----------------------------------------------------------------- changelog follow audit
TCL = "opentwitter_changelog_follow_audit_workflow_20260822"
PCL = _task(TCL)["evaluation"]["params"]
SEEDCL = [{"id": i["post_id"], "authorHandle": i["author_handle"], "text": "seed"} for i in PCL["interactions"]]


def _cl_engage() -> list[tuple[Any, ...]]:
    acts: list[tuple[Any, ...]] = []
    for item in PCL["interactions"]:
        acts += [(a, item["post_id"]) for a in ("like", "repost", "bookmark") if item.get(a)]
    acts += [("comment", c["post_id"], c["text"]) for c in PCL["comments"]]
    return acts


CL_OWN = [("comment", "post:Changelog pass done", "Release owner Lina"),
          ("like", "post:Changelog pass done"), ("bookmark", "post:Changelog pass done")]
CL_MSG = [("message", m["handle"], m["text"]) for m in PCL["messages"]]


def _demo_cl() -> list[tuple[Any, ...]]:
    return ([("read_all",), ("follow", "rachel"), ("follow", "eliseibrahim24")] + _cl_engage() + CL_MSG[:3]
            + [("post", "Changelog pass done"), ("post", "New follows added.")] + CL_OWN + CL_MSG[3:])


def test_changelog_demo_and_reordered_runs_pass():
    assert _run(TCL, SEEDCL, _demo_cl(), {}).status is EvalStatus.PASS
    # Priya < Nora("Follow note shared.") and the post order stay; the rest moves freely,
    # including Nora's other message coming last.
    actions = ([CL_MSG[3], ("post", "Changelog pass done"), CL_MSG[4], ("post", "New follows added.")] + CL_OWN
               + list(reversed(_cl_engage())) + [("follow", "eliseibrahim24"), ("follow", "rachel"), ("read_all",)]
               + list(reversed(CL_MSG[:3])))
    result = _run(TCL, SEEDCL, actions, {})
    assert result.status is EvalStatus.PASS, _failures(result)


def test_changelog_followed_by_violated_fails_and_nora_checks_are_distinct():
    actions = _demo_cl()
    actions[-2], actions[-1] = actions[-1], actions[-2]
    result = _run(TCL, SEEDCL, actions, {})
    assert _failures(result) == ["instruction_stated_order"]
    names = [check["name"] for check in result.metadata["checks"]]
    assert len([n for n in names if n.startswith("exact_message_nora")]) == 2 == len(
        {n for n in names if n.startswith("exact_message_nora")})


# ----------------------------------------------------------------- focus research community
TFR = "opentwitter_focus_research_community_workflow_20260822_v2"
PFR = _task(TFR)["evaluation"]["params"]
SEEDFR = [{"id": i["post_id"], "authorHandle": i["author_handle"], "text": "seed"} for i in PFR["interactions"]]
FR_MSG = [("message", m["handle"], m["text"]) for m in PFR["messages"]]
FR_OWN = [("comment", "post:Research plan set.", "Clips linked today"),
          ("like", "post:Research plan set."), ("bookmark", "post:Research plan set.")]


def _fr_engage() -> list[tuple[Any, ...]]:
    acts: list[tuple[Any, ...]] = []
    for item in PFR["interactions"]:
        acts += [(a, item["post_id"]) for a in ("like", "repost", "bookmark") if item.get(a)]
    return acts + [("comment", c["post_id"], c["text"]) for c in PFR["comments"]]


def test_focus_reordered_run_passes():
    actions = ([FR_MSG[3], ("read_all",), ("post", "Focus review ready"), FR_MSG[0], ("post", "Research plan set.")]
               + FR_OWN + list(reversed(_fr_engage())) + FR_MSG[1:3])
    result = _run(TFR, SEEDFR, actions, {})
    assert result.status is EvalStatus.PASS, _failures(result)


def test_focus_immediately_after_rejects_another_post_in_between():
    actions = (_fr_engage() + FR_MSG[:3] + [("post", "Focus review ready"), ("post", "Lunch break"),
                                             ("post", "Research plan set.")] + FR_OWN + [("read_all",), FR_MSG[3]])
    result = _run(TFR, SEEDFR, actions, {})
    assert _failures(result) == ["instruction_stated_order"]
    assert _order_check(result)["observed"]["violations"][0]["created_between"]


def test_focus_posts_in_reverse_order_fail():
    actions = (_fr_engage() + FR_MSG[:3] + [("post", "Research plan set."), ("post", "Focus review ready")]
               + FR_OWN + [("read_all",), FR_MSG[3]])
    assert _failures(_run(TFR, SEEDFR, actions, {})) == ["instruction_stated_order"]


# ----------------------------------------------------------------- helper
def test_stated_order_check_needs_every_anchor_and_strict_order():
    groups = [{"quote": "q", "chain": ["a", ["b", "c"]]}]
    ok, _, observed = stated_order_check(groups, {
        "a": {"at": "2026-10-30T20:00:00.000Z", "id": "1"},
        "b": {"at": "2026-10-30T20:00:01.000Z", "id": "2"},
        "c": {"at": "2026-10-30T20:00:02.000Z", "id": "3"},
    })
    assert ok and len(observed["pairs"]) == 2
    ok, _, observed = stated_order_check(groups, {"a": {"at": "2026-10-30T20:00:00Z"}, "b": None,
                                                  "c": {"at": "2026-10-30T20:00:00Z"}})
    assert not ok and observed["unresolved"] == ["b"] and observed["violations"][0]["after"] == "c"
