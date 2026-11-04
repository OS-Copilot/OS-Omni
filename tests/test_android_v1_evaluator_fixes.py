"""Android v1 evaluator/task fixes: OpenBank, OpenNote, OpenShop, OpenTrip,
OpenTwitter and the OpenDriver logout screen check."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from core.evaluation import EvalStatus
from evaluators.android.cua_review_state import ForegroundTextEvaluator

REPO_ROOT = Path(__file__).resolve().parents[1]
ANDROID_TASKS = REPO_ROOT / "tasks" / "v1" / "android"


def _task(name: str) -> dict[str, Any]:
    return yaml.safe_load((ANDROID_TASKS / f"{name}.yaml").read_text(encoding="utf-8"))


class _Controller:
    def __init__(self, package: str = "") -> None:
        self.package = package

    def execute_adb(self, args: list[str]) -> str:
        if args[:3] == ["shell", "dumpsys", "activity"]:
            return f"topResumedActivity={self.package}/.MainActivity"
        if args[:3] == ["shell", "dumpsys", "window"]:
            return f"mCurrentFocus={self.package}/.MainActivity"
        return ""


# --------------------------------------------------------------- OpenBank
# local-api.js in the installed APK: BUSINESS_DATE = "2026-06-01"; a transfer to
# an external person recipient is "Completed" when scheduledDate <= BUSINESS_DATE
# and "Scheduled" after it.
OPENBANK_BUSINESS_DATE = "2026-06-01"
OPENBANK_TASKS = (
    "openbank_maya_leo_security_dispute_payment_paperless_transfer_1787397914946_938252",
    "openbank_ace_tessa_security_city_nora_1787392720204_995198",
    "openbank_card_rebate_dispute_1787391981468_550137",
)


def _openbank_class(name: str):
    module = importlib.import_module(f"evaluators.android.{name}")
    return getattr(module, module.__all__[0])


def _apk_transfer_status(scheduled_date: str) -> str:
    return "Completed" if scheduled_date <= OPENBANK_BUSINESS_DATE else "Scheduled"


@pytest.mark.parametrize("name", OPENBANK_TASKS)
def test_openbank_future_transfers_expect_the_apk_status(name: str) -> None:
    cls = _openbank_class(name)
    task = _task(name)
    assert cls.ruleset_digest() == cls.RULESET_SHA256
    assert task["evaluation"]["params"]["expected_ruleset_sha256"] == cls.RULESET_SHA256
    assert task["metadata"]["evaluator_ruleset_sha256"] == cls.RULESET_SHA256

    transfers = {
        key: spec
        for key, spec in cls.RULESET_SPEC["expected"]["records"].items()
        if spec["collection"] == "transfers" and spec["required"].get("scheduledDate")
    }
    future = [key for key, spec in transfers.items() if spec["required"]["scheduledDate"] > OPENBANK_BUSINESS_DATE]
    assert future
    for key, spec in transfers.items():
        required = spec["required"]
        assert required["status"] == _apk_transfer_status(required["scheduledDate"]), key

        # The record the APK writes for a faithful transfer passes the check.
        state = {
            "transfers": [
                {
                    "id": "transfer-1",
                    "recipientId": "rec-1",
                    **required,
                    "amount": float(required["amount"]),
                    "status": _apk_transfer_status(required["scheduledDate"]),
                }
            ]
        }
        expected = {"records": {key: spec}}
        (result,) = cls()._compare(state, expected)
        assert result["passed"], result


def test_openbank_maya_transfer_dated_july_30_is_scheduled_not_completed() -> None:
    cls = _openbank_class(OPENBANK_TASKS[0])
    spec = cls.RULESET_SPEC["expected"]["records"]["maya_fox_kitchen_followup"]
    record = {**spec["required"], "amount": 2.95}
    expected = {"records": {"maya_fox_kitchen_followup": spec}}

    (scheduled,) = cls()._compare({"transfers": [dict(record, status="Scheduled")]}, expected)
    (completed,) = cls()._compare({"transfers": [dict(record, status="Completed")]}, expected)

    assert scheduled["passed"] is True
    assert completed["passed"] is False


# --------------------------------------------------------------- OpenNote
OPENNOTE_TASKS = (
    "opennote_city_food_469121",
    "opennote_fashion_trip_970990",
    "opennote_film_beauty_573866",
    "opennote_fitness_mind_940880",
    "opennote_gaming_home_461774",
    "opennote_style_home_477136",
)


def _apk_tags(text: str) -> list[str]:
    """POST /api/notes in the installed APK's local-api.js."""
    raw = re.split(r"[,#\s]+", text)
    return [item.lstrip("#").strip() for item in raw if item.lstrip("#").strip()][:5]


def _opennote_state(handle: str, notes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "session": {"loggedIn": True, "user": {"handle": handle}},
        "users": [{"handle": handle, "title": ""}],
        "notes": notes,
        "evaluationEvents": [
            {"type": "note_created", "noteId": note["id"], "title": note["title"]}
            for note in notes
        ],
    }


def _opennote_evaluator(name: str):
    module = importlib.import_module(f"evaluators.android.{name}")
    cls = next(
        value
        for value in vars(module).values()
        if isinstance(value, type) and getattr(value, "RULESET_SPEC", None) is module.RULESET_SPEC
    )
    return cls(), module.RULESET_SPEC["expected"]


def _created_notes(expected: dict[str, Any], handle: str, tags_for) -> list[dict[str, Any]]:
    return [
        {
            "id": f"n-{index}",
            "authorHandle": handle,
            "title": spec["title"],
            "text": spec["text"],
            "category": spec["category"],
            "location": spec["location"],
            "tags": tags_for(spec),
        }
        for index, spec in enumerate(expected["created_notes"])
    ]


@pytest.mark.parametrize("name", OPENNOTE_TASKS)
def test_opennote_multiword_tag_typed_as_instructed_passes(name: str) -> None:
    evaluator, expected = _opennote_evaluator(name)
    handle = expected["handle"]
    assert any(" " in tag for spec in expected["created_notes"] for tag in spec["tags"])

    # What the app stores when the agent types the instructed tag text.
    notes = _created_notes(expected, handle, lambda spec: _apk_tags(" ".join(spec["tags"])))
    checks = evaluator.compare(_opennote_state(handle, notes), {"handle": handle, "created_notes": expected["created_notes"]})
    created = [c for c in checks if c["name"].startswith("created_note_") and c["name"].endswith("_exact")]

    assert len(created) == len(expected["created_notes"])
    assert all(c["passed"] for c in created), [c for c in created if not c["passed"]]


@pytest.mark.parametrize("name", OPENNOTE_TASKS)
def test_opennote_wrong_or_partial_tags_still_fail(name: str) -> None:
    evaluator, expected = _opennote_evaluator(name)
    handle = expected["handle"]
    wrong = {
        "first token only": lambda spec: _apk_tags(spec["tags"][0])[:1],
        "reversed tokens": lambda spec: list(reversed(_apk_tags(spec["tags"][0]))),
        "category default": lambda spec: [spec["category"]],
        "extra tag": lambda spec: _apk_tags(spec["tags"][0]) + ["extra"],
    }
    for label, tags_for in wrong.items():
        notes = _created_notes(expected, handle, tags_for)
        checks = evaluator.compare(_opennote_state(handle, notes), {"handle": handle, "created_notes": expected["created_notes"]})
        created = [c for c in checks if c["name"].startswith("created_note_") and c["name"].endswith("_exact")]
        assert not any(c["passed"] for c in created), label


# --------------------------------------------------------------- OpenShop
def test_openshop_commute_brief_names_the_seeded_historical_spec() -> None:
    task = _task("openshop_commute_summary_order_review")
    params = task["evaluation"]["params"]
    spec = params["review_selected_spec"]
    assert spec == task["init"]["params"]["target_review_selected_spec"] == "15.6-inch"

    instruction = task["instruction"]
    review_clause = instruction[instruction.index("The order history must contain a review"):]
    assert f"with the {spec} specification within the historical order ID {params['review_order_id']}" in review_clause
    assert "16-inch specification within the historical" not in instruction
    # The new order's backpack is still the 16-inch one.
    assert "Polar Day Slim Business Backpack in 16-inch" in instruction
    assert params["items"][0]["selected_spec"] == "16-inch"


# --------------------------------------------------------------- OpenTrip
def _stay_booking(booking_id: str, created_at: str, *, voucher: int, total: int) -> dict[str, Any]:
    return {
        "id": booking_id,
        "type": "hotel",
        "createdAt": created_at,
        "status": "Confirmed",
        "contactPhone": "13900002026",
        "note": "pool suite",
        "guests": 4,
        "item": {"id": "h2001", "name": "Sanya Seabreeze Resort", "city": "Sanya"},
        "room": {"id": "family-suite", "name": "Family Pool Suite"},
        "checkIn": "2026-06-24",
        "checkOut": "2026-06-27",
        "payment": {"label": "Alipay"},
        "charges": {"baseFare": 1155, "serviceFee": 38, "nights": 3, "voucherDiscount": voucher, "total": total},
    }


def _run_opentrip(monkeypatch, bookings: list[dict[str, Any]]):
    from evaluators.cua_review.evaluators.android import opentrip

    state = {
        "session": {"loggedIn": True, "user": {"voucherWallet": {"hotel": 0}, "redeemedCodes": ["STAY150"]}},
        "bookings": bookings,
    }

    class _Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def read_state(self) -> dict[str, Any]:
            return state

    monkeypatch.setattr(opentrip, "OpenTripAndroidStore", _Store)
    params = _task("opentrip_hotel_voucher_family_suite_booking")["evaluation"]["params"]
    return opentrip.OpenTripHotelVoucherBookingEvaluator().evaluate(
        {"controller": _Controller("com.killt.opentrip"), "params": params}
    )


def test_opentrip_single_voucher_booking_passes(monkeypatch) -> None:
    result = _run_opentrip(
        monkeypatch, [_stay_booking("OT1", "2026-10-08T19:02:15.063Z", voucher=150, total=1043)]
    )
    assert result.status is EvalStatus.PASS, result.metadata["failures"]


def test_opentrip_duplicate_booking_fails_and_reports_the_latest_order(monkeypatch) -> None:
    # Recorded run: the voucher booking first, then a second full-price booking
    # of the same stay, which is the latest order the final screen shows.
    first = _stay_booking("OT1791486135063", "2026-10-08T19:02:15.063Z", voucher=150, total=1043)
    latest = _stay_booking("OT1791486454849", "2026-10-08T19:07:34.849Z", voucher=0, total=1193)
    result = _run_opentrip(monkeypatch, [latest, first])

    assert result.status is EvalStatus.FAIL
    failures = result.metadata["failures"]
    assert failures[0] == "target_stay_booking_unique"
    # Previously every field check was skipped when two bookings matched.
    assert {"charges_voucherDiscount", "charges_total"} <= set(failures)
    assert result.metadata["booking"]["id"] == "OT1791486454849"
    assert [item["id"] for item in result.metadata["matching_bookings"]] == ["OT1791486454849", "OT1791486135063"]
    unique = next(c for c in result.metadata["checks"] if c["name"] == "target_stay_booking_unique")
    assert unique["observed"] == 2
    assert "books it once" in unique["failure_reason"]


def test_opentrip_duplicate_identical_bookings_still_fail(monkeypatch) -> None:
    result = _run_opentrip(
        monkeypatch,
        [
            _stay_booking("OT2", "2026-10-08T19:07:00.000Z", voucher=150, total=1043),
            _stay_booking("OT1", "2026-10-08T19:02:00.000Z", voucher=150, total=1043),
        ],
    )
    assert result.status is EvalStatus.FAIL
    assert result.metadata["failures"] == ["target_stay_booking_unique"]


# ------------------------------------------------------------ OpenTwitter
TWITTER_TASK = "opentwitter_04_mobile_incident_frontend_audit"


def _twitter_state(params: dict[str, Any], replies: dict[str, list[str]], messages: dict[str, str], posts: dict[str, str]):
    created = "2026-10-30T20:00:00Z"
    # Messages and posts are sent one after another in the order the brief states.
    at = lambda minute: f"2026-10-30T20:{minute:02d}:00Z"  # noqa: E731
    handle = params["expected_handle"]
    own_posts = [
        {"id": f"p-new-{index}", "authorHandle": handle, "text": text, "createdAt": at(30 + index)}
        for index, text in enumerate(posts.values())
    ]
    owner_id = own_posts[0]["id"]
    comments: dict[str, list[dict[str, Any]]] = {}
    for post_id, texts in replies.items():
        key = owner_id if post_id == "owner" else post_id
        comments[key] = [
            {"id": f"c-{key}-{index}", "authorHandle": handle, "text": text, "createdAt": created}
            for index, text in enumerate(texts)
        ]
    likes, reposts, bookmarks = [], [], []
    for spec in params["target_posts"]:
        for action in spec["actions"]:
            {"like": likes, "repost": reposts, "bookmark": bookmarks}[action].append(spec["id"])
    likes.append(owner_id)
    bookmarks.append(owner_id)
    return {
        "session": {"loggedIn": True, "user": {"handle": handle}},
        "posts": [
            {"id": spec["id"], "authorHandle": spec["author_handle"], "text": spec["text"]}
            for spec in params["target_posts"]
        ]
        + own_posts,
        "comments": comments,
        "userStateByHandle": {
            handle: {
                "likedPostIds": likes,
                "repostedPostIds": reposts,
                "bookmarkedPostIds": bookmarks,
                "messages": [
                    {"id": f"m-{peer}", "outbound": True, "handle": peer, "text": text, "createdAt": at(10 + index)}
                    for index, (peer, text) in enumerate(messages.items())
                ],
                "notifications": [{"id": "n-1", "read": True}],
            }
        },
        "evaluationEvents": [],
    }


def _run_twitter(monkeypatch, replies, messages=None, posts=None):
    from evaluators.android import opentwitter_04_mobile_incident_frontend_audit as module

    params = _task(TWITTER_TASK)["evaluation"]["params"]
    messages = messages or {spec["handle"]: spec["text"] for spec in params["messages"]}
    posts = posts or {spec["text"]: spec["text"] for spec in params["created_posts"]}
    state = _twitter_state(params, replies, messages, posts)

    class _Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def read_state_read_only(self) -> dict[str, Any]:
            return state

    monkeypatch.setattr(module, "OpenShopAndroidStore", _Store)
    monkeypatch.setattr(
        module.OpenTwitterMobileIncidentFrontendAuditEvaluator,
        "_read_dom_state",
        staticmethod(
            lambda controller, package: {
                "view": "messages",
                "active_message_handle": "priya",
                "message_thread_open": True,
                "body_text": "Priya Shah\nMobile audit filed.",
            }
        ),
    )
    return module.OpenTwitterMobileIncidentFrontendAuditEvaluator().evaluate(
        {
            "controller": _Controller(params["app_package"]),
            "final_observation": SimpleNamespace(foreground_bundle_id=params["app_package"]),
            "params": params,
        }
    )


# Texts exactly as the English brief quotes them, punctuation inside the quotes.
BRIEF_REPLIES = {
    "p-1016": ["Draft issue tracked."],
    "p-1014": ["Timeline owner set,"],
    "p-1007": ["Paint timing logged."],
    "owner": ["Release owner Elena,"],
}
PARAM_REPLIES = {
    "p-1016": ["Draft issue tracked"],
    "p-1014": ["Timeline owner set"],
    "p-1007": ["Paint timing logged"],
    "owner": ["Release owner Elena"],
}


def test_opentwitter_replies_typed_as_quoted_in_the_brief_pass(monkeypatch) -> None:
    result = _run_twitter(monkeypatch, BRIEF_REPLIES)
    assert result.status is EvalStatus.PASS, result.metadata["failures"]


def test_opentwitter_replies_without_the_quoted_punctuation_pass(monkeypatch) -> None:
    result = _run_twitter(monkeypatch, PARAM_REPLIES)
    assert result.status is EvalStatus.PASS, result.metadata["failures"]


def test_opentwitter_sentence_final_period_is_optional_only_where_ambiguous(monkeypatch) -> None:
    params = _task(TWITTER_TASK)["evaluation"]["params"]
    messages = {spec["handle"]: spec["text"] for spec in params["messages"]}
    messages["ben"] = "QA gate reviewed"
    posts = {"Mobile gate ready.": "Mobile gate ready.", "Runbook owner set.": "Runbook owner set"}
    assert _run_twitter(monkeypatch, BRIEF_REPLIES, messages, posts).status is EvalStatus.PASS

    # "Mobile gate ready." and "Mobile audit filed." are quoted mid-sentence, so
    # their period is part of the text.
    posts = {"Mobile gate ready.": "Mobile gate ready", "Runbook owner set.": "Runbook owner set."}
    failed = _run_twitter(monkeypatch, BRIEF_REPLIES, posts=posts)
    assert "created_post_Mobile gate ready._exact_unique" in failed.metadata["failures"]
    messages = {spec["handle"]: spec["text"] for spec in params["messages"]}
    messages["priya"] = "Mobile audit filed"
    failed = _run_twitter(monkeypatch, BRIEF_REPLIES, messages)
    assert "message_priya_exact_unique" in failed.metadata["failures"]


def test_opentwitter_other_or_duplicate_replies_still_fail(monkeypatch) -> None:
    wrong = dict(BRIEF_REPLIES, **{"p-1016": ["Draft issue tracked!"]})
    result = _run_twitter(monkeypatch, wrong)
    assert result.metadata["failures"] == ["target_post_p-1016_reply_exact_unique"]

    both = dict(BRIEF_REPLIES, owner=["Release owner Elena", "Release owner Elena,"])
    result = _run_twitter(monkeypatch, both)
    assert result.metadata["failures"] == ["owner_post_reply_exact_unique"]


# ---------------------------------------------------- OpenDriver logout screen
# The installed OpenDriver APK's login page (_AuthFormPanel): Login, then an
# OutlinedButton "Create account" (Rider/Driver) / "Admin accounts are invite-only".
LOGIN_PAGE = [
    "Rider access", "Dispatch ready", "Payments synced", "Secure session", "Sign in",
    "Choose a workspace and continue.", "Rider", "Driver", "Admin", "Name", "Email",
    "Password", "Login", "Create account",
]
RIDER_WORKSPACE = ["Ride", "Active", "History", "Safety", "Account\nTab 5 of 5", "Logout"]


def _foreground(nodes: list[str], params: dict[str, Any]):
    controller = _Controller(params["app_package"])
    return ForegroundTextEvaluator().evaluate(
        {
            "controller": controller,
            "final_observation": SimpleNamespace(ui_nodes=[{"text": text} for text in nodes]),
            "params": params,
        }
    )


def test_opendriver_logout_accepts_the_login_page_with_create_account() -> None:
    params = _task("opendriver_rider_full_service_logout")["evaluation"]["params"]
    assert _foreground(LOGIN_PAGE, params).status is EvalStatus.PASS
    admin = [text for text in LOGIN_PAGE if text != "Create account"] + ["Admin accounts are invite-only"]
    assert _foreground(admin, params).status is EvalStatus.PASS


def test_opendriver_logout_still_rejects_the_signed_in_workspace() -> None:
    params = _task("opendriver_rider_full_service_logout")["evaluation"]["params"]
    result = _foreground(LOGIN_PAGE + RIDER_WORKSPACE, params)
    assert result.status is EvalStatus.FAIL
    assert set(result.metadata["forbidden_matches"]) >= {"Account", "Active", "History", "Safety", "Logout"}

    only_account_tab = _foreground(LOGIN_PAGE + ["Account"], params)
    assert only_account_tab.metadata["forbidden_matches"] == ["Account"]


def test_foreground_text_evaluator_without_exemptions_is_unchanged() -> None:
    params = dict(_task("opendriver_rider_full_service_logout")["evaluation"]["params"])
    params.pop("forbidden_text_exempt_phrases")
    result = _foreground(LOGIN_PAGE, params)
    assert result.status is EvalStatus.FAIL
    assert result.metadata["forbidden_matches"] == ["Account"]
