"""Web tasks: only the orders the English instruction states are graded.

OpenNavigation route reviews: the session ordinals ("the first session ...") are labels;
only "a final seventh session" / "the eighth and final session" and 2_3's "voice ... before
the Overview is viewed" are orders.  OpenShop core order: "a saved note reading ReviewCoreA,
which must subsequently be replaced with ReviewCoreA-Final".
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.cua_review.evaluators.linux import opennavigation_sessions as nav

ROOT = Path(__file__).resolve().parents[1]


def _params(name: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / "tasks/v1/web" / f"{name}.yaml").read_text(encoding="utf-8"))["evaluation"]["params"]


# ------------------------------------------------------------------ OpenNavigation


def _session(spec: dict[str, Any], clicks: list[str] | None = None) -> dict[str, Any]:
    if clicks is None:
        clicks = (["Voice"] if spec.get("voice") else []) + (["Overview"] if spec.get("overview") else [])
    return {"destination": spec["destination"], "mode": spec["mode"], "origin": spec["origin"],
            "clicks": clicks + ["End"], "ended": True}


def _events(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, t = [], 0
    for session in sessions:
        t += 1
        out.append({"t": t, "action": "start", "destination": session["destination"],
                    "origin": session["origin"], "mode": session["mode"]})
        for label in session["clicks"]:
            t += 1
            out.append({"t": t, "action": "click", "label": label})
        t += 1
        out.append({"t": t, "action": "end"})
    return out


def _grade(monkeypatch, params: dict[str, Any], sessions: list[dict[str, Any]]):
    reading = {"pages": [{"recorder": True, "events": _events(sessions)}], "errors": []}
    monkeypatch.setattr(nav, "read_events", lambda controller, port=None: reading)
    params = dict(params)
    params.pop("min_trajectory_records", None)  # trajectory length is not what these tests are about
    return nav.OpenNavigationSessionEvaluator().evaluate({"controller": None, "params": params})


def test_route_review_2_1_sessions_in_another_order_pass_but_not_with_the_old_ordered_flag(monkeypatch):
    params = _params("opennavigation_route_review_2_1")
    specs = params["expected_sessions"]
    assert params["ordered"] is False and specs[-1]["final"] is True
    # Sessions 1-6 in reverse, the final Googleplex Bike session last.
    sessions = [_session(spec) for spec in reversed(specs[:-1])] + [_session(specs[-1])]
    result = _grade(monkeypatch, params, sessions)
    assert result.status is EvalStatus.PASS, result.metadata["failures"]
    # The previous configuration demanded the recorded demo order.
    legacy = dict(params, ordered=True)
    assert _grade(monkeypatch, legacy, sessions).status is EvalStatus.FAIL


def test_route_review_2_1_final_session_must_come_last(monkeypatch):
    params = _params("opennavigation_route_review_2_1")
    specs = params["expected_sessions"]
    sessions = [_session(specs[-1])] + [_session(spec) for spec in specs[:-1]]
    result = _grade(monkeypatch, params, sessions)
    assert result.metadata["failures"] == ["stated_order.final_session"]


def test_route_review_2_1_missing_or_wrong_session_fails(monkeypatch):
    params = _params("opennavigation_route_review_2_1")
    specs = params["expected_sessions"]
    sessions = [_session(spec) for spec in specs]
    missing = _grade(monkeypatch, params, sessions[1:])
    assert "session.1" in missing.metadata["failures"]
    # Meta Headquarters Drive twice but without the voice icon: one of the two required sessions is missing.
    no_voice = copy.deepcopy(sessions)
    no_voice[0]["clicks"] = ["Overview", "End"]
    assert "session.1" in _grade(monkeypatch, params, no_voice).metadata["failures"]
    # A single session cannot stand for two required ones.
    once = [s for i, s in enumerate(sessions) if i != 4]
    assert _grade(monkeypatch, params, once).status is EvalStatus.FAIL


def test_route_review_2_3_voice_before_overview_and_final_session(monkeypatch):
    params = _params("opennavigation_route_review_2_3")
    specs = params["expected_sessions"]
    assert specs[0]["voice_before_overview"] is True and specs[-1]["final"] is True
    shuffled = [specs[i] for i in (6, 2, 0, 4, 1, 5, 3, 7)]
    sessions = [_session(spec) for spec in shuffled]
    result = _grade(monkeypatch, params, sessions)
    assert result.status is EvalStatus.PASS, result.metadata["failures"]

    overview_first = copy.deepcopy(sessions)
    overview_first[2]["clicks"] = ["Overview", "Mute", "End"]  # the Stanford Walk session
    assert "session.1" in _grade(monkeypatch, params, overview_first).metadata["failures"]
    overview_again = copy.deepcopy(sessions)
    overview_again[2]["clicks"] = ["Overview", "Mute", "Overview", "End"]
    assert _grade(monkeypatch, params, overview_again).status is EvalStatus.PASS

    # The two Mountain View Transit Center Transit sessions: one of them must come after all the others.
    meta_drive = shuffled.index(specs[1])
    transit_not_last = sessions[:meta_drive] + sessions[meta_drive + 1:] + [sessions[meta_drive]]
    failures = _grade(monkeypatch, params, transit_not_last).metadata["failures"]
    assert failures == ["stated_order.final_session"]


def test_route_review_2_2_states_no_order(monkeypatch):
    params = _params("opennavigation_route_review_2_2")
    specs = params["expected_sessions"]
    assert params["ordered"] is False and not any(spec.get("final") for spec in specs)
    sessions = [_session(spec) for spec in reversed(specs)]
    assert _grade(monkeypatch, params, sessions).status is EvalStatus.PASS


def test_unordered_matching_finds_an_assignment_greedy_order_would_miss():
    loose = {"destination": "Meta Headquarters", "mode": "drive", "origin": "Current location", "overview": True}
    strict = dict(loose, voice=True)
    sessions = [_session(strict), _session(loose)]
    assert nav.assign_sessions([loose, strict], sessions) == [1, 0]


# ------------------------------------------------------------------ OpenShop core order

from evaluators.linux import openshop_core_order_stepwise_20260827 as core  # noqa: E402


class _Shop:
    """Answers the evaluator's guest GET requests from a fixed API state."""

    def __init__(self, payloads: dict[str, Any]):
        self.payloads = payloads

    def run_bash_script(self, script: str, timeout: int = 30) -> dict[str, Any]:
        path = script.split("http://127.0.0.1:", 1)[1].split('"', 1)[0].split("/", 1)[1]
        return {"returncode": 0, "output": json.dumps(self.payloads["/" + path])}


def _core_state(notes: list[str], browse: bool = True) -> dict[str, Any]:
    params = _params("openshop_core_order_stepwise_20260827")
    latest = params["orders"]["latest"]
    prices = {"p1001": 299, "p1005": 89, "p1006": 49, "p1004": 177}
    items = [{"product": {"id": i["product_id"], "price": prices[i["product_id"]]}, "quantity": i["quantity"],
              "selectedSpec": i["selected_spec"]} for i in latest["items"]]
    events: list[dict[str, Any]] = []
    if browse:
        events += [{"type": "category_viewed", "category": "Bags"}, {"type": "product_viewed", "productId": "p1004"}]
    events.append({"type": "checkout_submitted", "addressId": "addr-office", "paymentMethodId": "wechat",
                   "note": "CoreOfficeA", "total": "984.0", "itemCount": 4})
    for note in notes:
        events.append({"type": "order_review_note_saved", "orderId": "TB1", "reviewNote": note})
        if browse:
            events.append({"type": "order_viewed", "orderId": "TB1"})
    order = {"id": "TB1", "status": latest["status"], "note": "CoreOfficeA", "reviewNote": notes[-1] if notes else "",
             "total": 984, "address": {"label": "Office"}, "payment": {"id": "wechat", "label": "WeChat Pay"},
             "items": items}
    return {
        "/api/session": {"session": {"loggedIn": True, "user": {"phone": "13800138000"}}},
        "/api/cart": {"items": [], "total": 0},
        "/api/orders": {"orders": [order]},
        "/api/benchmark": {"events": [dict(e, seq=i + 1) for i, e in enumerate(events)]},
    }


def _core(notes: list[str], browse: bool = True):
    params = _params("openshop_core_order_stepwise_20260827")
    return core.OpenShopApiEvaluator().evaluate({"controller": _Shop(_core_state(notes, browse)), "params": params})


def test_openshop_core_review_note_saved_then_replaced_passes():
    assert _core(["ReviewCoreA", "ReviewCoreA-Final"]).status is EvalStatus.PASS
    assert _core(["ReviewCoreA", "ReviewCoreA-Final"], browse=False).status is EvalStatus.PASS
    # An extra save of the final text before the intermediate one changes nothing.
    assert _core(["ReviewCoreA-Final", "ReviewCoreA", "ReviewCoreA-Final"]).status is EvalStatus.PASS


@pytest.mark.parametrize("notes", [["ReviewCoreA-Final"], ["ReviewCoreA-Final", "ReviewCoreA-Final"]])
def test_openshop_core_review_note_without_the_stated_intermediate_save_fails(notes):
    result = _core(notes)
    assert result.status is EvalStatus.FAIL and "event sequence" in result.message
    # The previous parameters (no stated order) passed this run.
    params = _params("openshop_core_order_stepwise_20260827")
    params.pop("benchmark_event_sequence")
    legacy = core.OpenShopApiEvaluator().evaluate({"controller": _Shop(_core_state(notes)), "params": params})
    assert legacy.status is EvalStatus.PASS


def test_openshop_core_final_note_must_be_the_replacement():
    result = _core(["ReviewCoreA-Final", "ReviewCoreA"])
    assert result.status is EvalStatus.FAIL and "reviewNote" in result.message
