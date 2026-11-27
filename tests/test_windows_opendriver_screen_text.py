"""Windows OpenDriver evaluators read the page from the screen the controller returns.

The Windows runtime controller returns a dataclass ``Observation`` (not a mapping),
and OpenDriver is a Flutter canvas: its UI Automation tree holds only the window
frame and Flutter's hidden autofill form, which names every value typed this session.
The trees below are the ones the controller returned in the reviewed runs.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from core.evaluation import EvalStatus, load_evaluator
from core.evaluation.context import with_task_binding
from core.specs.loader import load_task_spec
from evaluators.cua_review.evaluators.windows import opendriver
from evaluators.windows.opendriver_driver_onboarding_trip_support_snapshot1 import (
    OpenDriverDriverLifecycleEvaluator,
)
from platforms.windows.runtime_env.controller import Observation

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT2 = "tasks/v1/windows/opendriver_rider_account_support_logout_snapshot2.yaml"
LOGOUT = "tasks/v1/windows/opendriver_rider_account_support_logout.yaml"
ONBOARDING = "tasks/v1/windows/opendriver_driver_onboarding_trip_support_snapshot1.yaml"
DRIVER_OPS = "tasks/v1/windows/opendriver_driver_ops_snap1.yaml"

# OCR of the signed-out page and of the rider workspace as Tesseract reads them.
LOGIN_PAGE = ("opendriver\nSign in to manage rides, driving, or operations.\nv Rider\n& Driver\n"
              "@ Admin\n[ Name\n[Email\n| Password\nLogin\nCreate account\n")
RIDER_WORKSPACE = ("opendriver & Account\n(Ride ~Active QHistory © Safety & Account\n"
                   "No active ride.\nRequest a ride\n")


def _node(index, kind, text, x, y, w, h):
    return {"id": f"n{index}", "type": kind, "text": text, "selector": text,
            "rect": {"x": float(x), "y": float(y), "w": float(w), "h": float(h)},
            "accessible": True, "enabled": True}


def _signed_out_tree():
    """The final tree of the reviewed snapshot2 run, after Scan Rider was created."""
    form = ("Test Rider Submit test.rider.1783492350@example.com Submit •••••••••••• Submit "
            "Scan Rider Submit scan.rider@example.com Submit •••••••• Submit "
            "Stanford University, Stanford, CA Submit")
    return [
        _node(0, "panecontrol", "opendriver", 0, 0, 1480, 831),
        _node(1, "documentcontrol", "opendriver", 8, 31, 1464, 792),
        _node(2, "menubarcontrol", "System", 8, 8, 22, 22),
        _node(3, "buttoncontrol", "Minimize", 1333, 1, 47, 30),
        _node(4, "buttoncontrol", "Maximize", 1380, 1, 46, 30),
        _node(5, "buttoncontrol", "Close", 1426, 1, 47, 30),
        _node(6, "groupcontrol", form, 8, 31, 1464, 792),
        _node(7, "buttoncontrol", "Submit", 8, 33, 35, 12),
    ]


def _maximized_tree():
    """The final tree of the Opus 5.5 onboarding run (maximized, 1920x1080)."""
    return [
        _node(0, "panecontrol", "opendriver", -8, -8, 1936, 1048),
        _node(1, "documentcontrol", "Chrome Legacy Window", 0, 23, 1920, 1009),
        _node(2, "menubarcontrol", "System", 0, 0, 22, 22),
        _node(3, "buttoncontrol", "Minimize", 1779, 0, 47, 22),
        _node(4, "buttoncontrol", "Restore", 1826, 0, 46, 22),
        _node(5, "buttoncontrol", "Close", 1872, 0, 48, 22),
    ]


def _png(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (246, 247, 250)).save(buffer, format="PNG")
    return buffer.getvalue()


def _observation(nodes, width, height):
    return Observation(timestamp="20261104_000000_000", width=width, height=height, ui_nodes=nodes,
                       foreground_app="opendriver.exe", foreground_bundle_id="opendriver.exe",
                       foreground_window="opendriver", screenshot_data=_png(width, height))


@pytest.fixture
def ocr(monkeypatch):
    """Replace the OCR engine; record the size of every image it is given."""
    state = {"text": "", "error": "", "sizes": []}

    def fake(png):
        state["sizes"].append(Image.open(io.BytesIO(png)).size)
        return state["text"], state["error"]

    monkeypatch.setattr(opendriver, "ocr_image_text", fake)
    return state


class _Guest:
    def __init__(self, store, processes=None):
        self.store = store
        self.processes = processes or [{"process_name": "opendriver", "pid": 1, "window_title": "opendriver"}]

    def run_python_script(self, script, timeout=None):
        payload = {"database_path": r"C:\Users\User\AppData\Roaming\opendriver\data\opendriver-db.json",
                   "data": self.store}
        return {"returncode": 0, "stdout": json.dumps(payload), "output": json.dumps(payload)}

    def run_powershell_script(self, script, timeout=None):
        return {"returncode": 0, "output": json.dumps(self.processes)}


def _rider_store(sessions=()):
    return {
        "users": [
            {"id": "usr_rider_primary", "name": "Riley Rider", "email": "rider@example.com",
             "role": "rider", "passwordHash": "pbkdf2$a"},
            {"id": "usr_scan", "name": "Scan Rider", "email": "scan.rider@example.com",
             "role": "rider", "passwordHash": "pbkdf2$b"},
        ],
        "supportTickets": [
            {"id": "ticket_2", "userId": "usr_scan", "category": "safety concern",
             "message": "Follow up on my ride.", "status": "open"},
            {"id": "ticket_1", "userId": "usr_scan", "category": "safety concern",
             "message": "I need help with my ride.", "status": "open"},
        ],
        "sessions": list(sessions),
    }


def _evaluate(task, controller, observation):
    spec = load_task_spec(REPO_ROOT / task)
    context = with_task_binding({"params": dict(spec.evaluation.params), "controller": controller,
                                 "final_observation": observation}, spec)
    return load_evaluator(spec.evaluation.evaluator_id).evaluate(context)


def _check(result, check_id):
    return next(row for row in result.metadata["checks"] if row["check_id"] == check_id)


@pytest.mark.parametrize("task", [SNAPSHOT2, LOGOUT])
def test_logged_out_page_is_read_from_the_screenshot(task, ocr):
    ocr["text"] = LOGIN_PAGE
    observation = _observation(_signed_out_tree(), 1480, 879)
    assert not isinstance(observation, dict)  # the shape the old reader skipped

    result = _evaluate(task, _Guest(_rider_store()), observation)

    assert result.status is EvalStatus.PASS, result.metadata["failed_checks"]
    assert "Create account" in _check(result, "signed_out_entry_point")["observed"]["present"]
    # "Create account" is the entry point, not the Account tab; the autofill form's
    # "Scan Rider" / "scan.rider@example.com" is not on the page.
    assert _check(result, "workspace_absent")["observed"]["present"] == []
    screen = result.metadata["screen_text"]
    assert screen["source"] == ["ocr"] and screen["region"] == [8, 31, 1472, 823]
    assert ocr["sizes"] == [(1464, 792)]


def test_entry_point_text_does_not_count_as_the_account_tab():
    visible = opendriver._normalise(LOGIN_PAGE)
    assert opendriver.contains_text(visible, "Account")  # the contradiction before the fix
    masked = opendriver.mask_enclosing_text(visible, "Account", opendriver.SIGNED_OUT_PAGE_TEXT)
    assert not opendriver.contains_text(masked, "Account")
    workspace = opendriver._normalise(RIDER_WORKSPACE + "Create account")
    masked = opendriver.mask_enclosing_text(workspace, "Account", opendriver.SIGNED_OUT_PAGE_TEXT)
    assert opendriver.contains_text(masked, "Account")


@pytest.mark.parametrize("task", [SNAPSHOT2, LOGOUT])
def test_signed_in_workspace_fails_the_logout(task, ocr):
    ocr["text"] = RIDER_WORKSPACE
    result = _evaluate(task, _Guest(_rider_store()), _observation(_signed_out_tree(), 1480, 879))

    assert result.status is EvalStatus.FAIL
    assert {"signed_out_entry_point", "workspace_absent"} <= set(result.metadata["failed_checks"])
    present = _check(result, "workspace_absent")["observed"]["present"]
    assert {"Active", "History", "Safety", "Account", "No active ride", "Request a ride"} <= set(present)


def test_blank_window_is_not_a_signed_out_page(ocr):
    # The Opus 5.5 run: CanvasKit never loaded, OCR of the content area reads nothing.
    ocr["text"] = ""
    result = _evaluate(SNAPSHOT2, _Guest(_rider_store()), _observation(_maximized_tree(), 1920, 1080))

    assert result.status is EvalStatus.FAIL
    assert "signed_out_entry_point" in result.metadata["failed_checks"]


def test_unreadable_screen_falls_back_to_the_store_only_where_declared(ocr):
    ocr["error"] = "TesseractNotFoundError: tesseract is not installed"
    observation = _observation(_signed_out_tree(), 1480, 879)

    fallback = _evaluate(SNAPSHOT2, _Guest(_rider_store()), observation)
    assert fallback.status is EvalStatus.PASS
    assert _check(fallback, "signed_out_entry_point")["observed"]["database_state_fallback"] is True

    strict = _evaluate(LOGOUT, _Guest(_rider_store()), observation)
    assert strict.status is EvalStatus.FAIL
    assert "could not be read" in _check(strict, "signed_out_entry_point")["failure_reason"]

    signed_in = _evaluate(SNAPSHOT2, _Guest(_rider_store([{"id": "s", "token": "t", "userId": "usr_scan"}])),
                          observation)
    assert signed_in.status is EvalStatus.FAIL and "sessions_empty" in signed_in.metadata["failed_checks"]


def test_saved_mapping_observation_is_read_too(ocr):
    ocr["text"] = LOGIN_PAGE
    saved = {"a11y_tree": _signed_out_tree(), "foreground_app": "opendriver.exe",
             "foreground_window": "opendriver", "width": 1480, "height": 879,
             "screenshot_data": _png(1480, 879)}
    screen = opendriver.read_window_text(None, saved)

    assert screen["ui_node_count"] == 8 and screen["region"] == [8, 31, 1472, 823]
    assert "Create account" in screen["text"] and "Scan Rider" not in screen["text"]


def _support_ui(ocr_text, ocr):
    ocr["text"] = ocr_text
    spec = load_task_spec(REPO_ROOT / ONBOARDING)
    context = {"controller": _Guest({}), "final_observation": _observation(_maximized_tree(), 1920, 1080)}
    ui = OpenDriverDriverLifecycleEvaluator._collect_ui_evidence(context, dict(spec.evaluation.params))
    return {row["name"]: row for row in ui["checks"]}


def test_final_support_page_is_read_from_the_screenshot(ocr):
    page = ("Driver Workspace\nWork Money Account Support\nDriver safety and support\n"
            "Rider verification Report rider Operations support\nMessage\nCreate support ticket\n"
            "Rider conduct review\nrider issue - open\n")
    checks = _support_ui(page, ocr)
    assert checks["final_support_page_visible"]["passed"]
    assert checks["final_support_page_visible"]["actual"]["accessibility_page_match"]
    assert checks["support_ticket_dialog_closed"]["passed"]
    assert ocr["sizes"] == [(1920, 1009)]

    dialog = _support_ui(page + "Reply\nClose\nSend reply\n", ocr)
    assert not dialog["support_ticket_dialog_closed"]["passed"]


def test_unread_support_page_no_longer_passes_the_dialog_check(ocr):
    # Before the fix the frame-only tree made "Send reply" trivially absent.
    checks = _support_ui("", ocr)
    assert not checks["final_support_page_visible"]["passed"]
    assert not checks["support_ticket_dialog_closed"]["passed"]


def _driver_ops_store(note="Weekly payout"):
    documents = [
        {"id": "doc_1", "type": "driver_license", "identifier": "DL-ROAD27", "expiresAt": "2028-12-31",
         "status": "submitted"},
        {"id": "doc_2", "type": "insurance", "identifier": "INS-ROAD27", "expiresAt": "2028-06-30",
         "status": "submitted"},
        {"id": "doc_3", "type": "vehicle_inspection", "identifier": "INSP-ROAD27", "expiresAt": "2028-09-30",
         "status": "submitted"},
    ]
    return {
        "users": [{"id": "usr_roadops", "name": "RoadOps 27", "email": "roadops27@drv.test",
                   "role": "driver", "passwordHash": "pbkdf2$c"}],
        "driverProfiles": [{"id": "drv_profile_1", "userId": "usr_roadops", "licenseNumber": "CA-DL-2701",
                            "vehicleMake": "Toyota", "vehicleModel": "Prius", "vehicleYear": "2024",
                            "licensePlate": "ROAD27", "vehicleColor": "Blue", "documents": documents}],
        "ratings": [{"id": "rating_1", "rideId": "ride_seed_completed", "score": 4, "comment": "Clear pickup"}],
        "supportTickets": [{"id": "ticket_1", "userId": "usr_driver_primary", "category": "rider issue",
                            "message": "Rider conduct review", "status": "open", "replies": [
                                {"id": "r1", "ticketId": "ticket_1", "message": "Check rider history"},
                                {"id": "r2", "ticketId": "ticket_1", "message": "Pickup info ready"}]}],
        "payouts": [{"id": "payout_1", "driverId": "usr_driver_primary", "amount": 120,
                     "status": "requested", "note": note}],
    }


def test_driver_ops_grades_the_declared_storage_values():
    passed = _evaluate(DRIVER_OPS, _Guest(_driver_ops_store()), None)
    assert passed.status is EvalStatus.PASS, passed.metadata["failed_checks"]

    default_note = _evaluate(DRIVER_OPS, _Guest(_driver_ops_store("Weekly payout request")), None)
    assert default_note.status is EvalStatus.FAIL
    assert _check(default_note, "storage_expected_text")["observed"]["missing"] == ["Weekly payout"]
