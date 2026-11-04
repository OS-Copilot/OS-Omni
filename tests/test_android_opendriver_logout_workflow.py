"""android.opendriver.rider_full_service_logout: the final login page is also the
starting page, so the grader must also find the workflow's durable record (the
support ticket and its reply in the OpenDriver service) and the cleared app
credential, not just the login screen."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from core.evaluation import EvalStatus, load_evaluator
from evaluators.android.cua_review_state import ForegroundTextEvaluator

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK = REPO_ROOT / "tasks/v1/android/opendriver_rider_full_service_logout.yaml"
PACKAGE = "com.killt.opendriver"
RIDER = {"id": "usr_rider_primary", "name": "Avery", "email": "rider@example.com", "role": "rider"}
TOKEN = "f" * 32  # what the installed APK's TokenStore writes after login

# What the signed-out login page shows (the saved Opus 5.5 run's final screen).
LOGIN_PAGE = [
    "Rider access", "Dispatch ready", "Payments synced", "Secure session", "Sign in",
    "Choose a workspace and continue.", "Rider", "Driver", "Admin", "Avery",
    "rider@example.com", "Login", "Create account",
]
RIDER_WORKSPACE = ["Ride", "Active", "History", "Safety", "Account", "Logout"]


def _params() -> dict[str, Any]:
    return dict(yaml.safe_load(TASK.read_text(encoding="utf-8"))["evaluation"]["params"])


def _iso(moment: datetime, *, zulu: bool) -> str:
    text = moment.astimezone(timezone.utc).isoformat()
    return text.replace("+00:00", "Z") if zulu else text


class _Service:
    """The OpenDriver service contract the APK uses (both service builds)."""

    def __init__(self, tickets: list[dict[str, Any]], *, accept_login: bool = True) -> None:
        self.tickets = tickets
        self.accept_login = accept_login
        self.requests: list[tuple[str, str, Any]] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, code: int, payload: Any) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                service.requests.append(("POST", self.path, body))
                ok = (
                    service.accept_login
                    and body.get("email") == RIDER["email"]
                    and body.get("password") == "password123"
                    and body.get("role") == "rider"
                )
                if self.path == "/auth/login" and ok:
                    self._send(200, {"success": True, "data": {"token": "evaluator-session", "user": RIDER}})
                else:
                    self._send(401, {"success": False, "error": {"code": "INVALID_CREDENTIALS"}})

            def do_GET(self) -> None:  # noqa: N802
                service.requests.append(("GET", self.path, self.headers.get("Authorization")))
                if self.path == "/support/tickets" and self.headers.get("Authorization") == "Bearer evaluator-session":
                    self._send(200, {"success": True, "data": {"tickets": service.tickets}})
                else:
                    self._send(401, {"success": False, "error": {"code": "AUTH_REQUIRED"}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Controller:
    def __init__(self, *, token: str = "") -> None:
        self.token = token
        self.adb: list[list[str]] = []

    def execute_adb(self, args: list[str]) -> str:
        self.adb.append(list(args))
        if args[:3] == ["shell", "dumpsys", "activity"]:
            return f"topResumedActivity={PACKAGE}/.MainActivity"
        if args[:3] == ["shell", "dumpsys", "window"]:
            return f"mCurrentFocus={PACKAGE}/.MainActivity"
        if args[:2] == ["shell", "run-as"]:
            if self.token and args[-1] == "code_cache/opendriver/auth_token.txt":
                return self.token
            return f"cat: {args[-1]}: No such file or directory"
        return ""


def _seed_tickets(at: datetime) -> list[dict[str, Any]]:
    # Open seed tickets of this rider ("Payments" / "rider issue") and an older
    # resolved safety ticket, all present before the episode.
    return [
        {"id": "ticket-payments", "userId": RIDER["id"], "category": "Payments", "message": "Seed support record",
         "status": "open", "createdAt": _iso(at - timedelta(days=3), zulu=True), "replies": []},
        {"id": "ticket-rider", "userId": RIDER["id"], "category": "rider issue", "message": "Seed support record",
         "status": "open", "createdAt": _iso(at - timedelta(days=3), zulu=True), "replies": []},
        {"id": "ticket_three_month_safety", "userId": RIDER["id"], "category": "safety concern",
         "message": "safety concern: Driver missed a turn repeatedly.", "status": "resolved",
         "createdAt": _iso(at - timedelta(days=30), zulu=True)},
    ]


def _created_ticket(at: datetime, *, replies: list[dict[str, Any]] | None = None, zulu: bool = False, **fields: Any):
    ticket = {
        "id": "ticket-new",
        "userId": RIDER["id"],
        "rideId": "",
        "category": "safety concern",
        "message": "Need ride help",
        "status": "open",
        "createdAt": _iso(at, zulu=zulu),
        "updatedAt": _iso(at, zulu=zulu),
        "replies": [
            {"id": "reply-1", "ticketId": "ticket-new", "userId": RIDER["id"], "userName": "Avery", "role": "rider",
             "message": "Following up on this ticket.", "createdAt": _iso(at + timedelta(seconds=20), zulu=zulu)}
        ]
        if replies is None
        else replies,
    }
    ticket.update(fields)
    return ticket


def _trajectory(tmp_path: Path, first_step: datetime) -> str:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    records = [
        {"step_index": 1, "timestamp": _iso(first_step, zulu=False), "latency_ms": 6000.0},
        {"step_index": 2, "timestamp": _iso(first_step + timedelta(seconds=9), zulu=False), "latency_ms": 7000.0},
    ]
    (run_dir / "trajectory.jsonl").write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
    return str(run_dir)


@pytest.fixture
def episode(tmp_path: Path):
    """Start of the agent's first step, a run dir with its trajectory and a service factory."""
    started = datetime.now(timezone.utc) - timedelta(minutes=20)
    run_dir = _trajectory(tmp_path, started + timedelta(seconds=6))
    services: list[_Service] = []

    def service(tickets: list[dict[str, Any]], **kwargs: Any) -> _Service:
        services.append(_Service(tickets, **kwargs))
        return services[-1]

    yield SimpleNamespace(started=started, run_dir=run_dir, service=service)
    for item in services:
        item.close()


def _evaluate(service_url: str, *, screen: list[str] = LOGIN_PAGE, token: str = "", run_dir: str | None = None):
    params = _params()
    params["api_base_url"] = service_url
    evaluator = load_evaluator(yaml.safe_load(TASK.read_text(encoding="utf-8"))["evaluation"]["evaluator_id"])
    return evaluator.evaluate(
        {
            "controller": _Controller(token=token),
            "final_observation": SimpleNamespace(ui_nodes=[{"text": text} for text in screen]),
            "params": params,
            "run_dir": run_dir,
        }
    )


def test_untouched_login_screen_no_longer_passes(episode) -> None:
    service = episode.service(_seed_tickets(episode.started))
    params = _params()
    old = ForegroundTextEvaluator().evaluate(
        {
            "controller": _Controller(),
            "final_observation": SimpleNamespace(ui_nodes=[{"text": text} for text in LOGIN_PAGE]),
            "params": params,
        }
    )
    assert old.status is EvalStatus.PASS  # the defect: the starting screen passed

    result = _evaluate(service.url, run_dir=episode.run_dir)
    assert result.status is EvalStatus.FAIL
    assert result.metadata["checks"]["final_screen_signed_out"] is True
    assert result.metadata["failures"] == ["support_ticket_created_once", "support_ticket_replied"]


@pytest.mark.parametrize("zulu", [True, False], ids=["node-service-Z", "reconstructed-service-offset"])
def test_full_workflow_passes(episode, zulu: bool) -> None:
    created = episode.started + timedelta(minutes=8)
    service = episode.service(_seed_tickets(episode.started) + [_created_ticket(created, zulu=zulu)])

    result = _evaluate(service.url, run_dir=episode.run_dir)

    assert result.status is EvalStatus.PASS, result.metadata.get("failures")
    assert result.metadata["support_ticket"]["created_this_episode_ids"] == ["ticket-new"]
    # The evaluator signs in with the instruction's account and only reads afterwards.
    assert [(method, path) for method, path, _ in service.requests] == [("POST", "/auth/login"), ("GET", "/support/tickets")]


def test_ticket_without_a_reply_fails(episode) -> None:
    service = episode.service([_created_ticket(episode.started + timedelta(minutes=8), replies=[])])
    result = _evaluate(service.url, run_dir=episode.run_dir)
    assert result.status is EvalStatus.FAIL
    assert result.metadata["failures"] == ["support_ticket_replied"]


def test_only_a_support_reply_does_not_count_as_the_riders_reply(episode) -> None:
    created = episode.started + timedelta(minutes=8)
    admin_reply = {"id": "reply-admin", "userId": "usr_admin", "userName": "Ops", "role": "admin",
                   "message": "We are reviewing this ticket.", "createdAt": _iso(created, zulu=True)}
    service = episode.service([_created_ticket(created, replies=[admin_reply])])
    result = _evaluate(service.url, run_dir=episode.run_dir)
    assert result.metadata["failures"] == ["support_ticket_replied"]


@pytest.mark.parametrize(
    "fields",
    [{"category": "other"}, {"category": "driver issue"}, {"message": "I need help with my ride."}, {"message": "Need help"}],
)
def test_wrong_category_or_message_fails(episode, fields: dict[str, Any]) -> None:
    service = episode.service([_created_ticket(episode.started + timedelta(minutes=8), **fields)])
    result = _evaluate(service.url, run_dir=episode.run_dir)
    assert result.status is EvalStatus.FAIL
    assert "support_ticket_created_once" in result.metadata["failures"]


def test_ticket_from_an_earlier_run_does_not_count(episode) -> None:
    stale = _created_ticket(episode.started - timedelta(minutes=3))
    service = episode.service([stale])

    result = _evaluate(service.url, run_dir=episode.run_dir)
    assert result.status is EvalStatus.FAIL
    assert result.metadata["support_ticket"]["matching_ticket_ids"] == ["ticket-new"]
    assert result.metadata["support_ticket"]["created_this_episode_ids"] == []

    # Without a trajectory (evaluate-only), no episode bound applies.
    assert _evaluate(service.url, run_dir=None).status is EvalStatus.PASS


def test_ticket_created_in_the_first_step_counts(episode) -> None:
    # Step 1 is stamped after its action; its latency reaches back before it.
    service = episode.service([_created_ticket(episode.started + timedelta(seconds=2))])
    assert _evaluate(service.url, run_dir=episode.run_dir).status is EvalStatus.PASS


def test_the_ticket_is_created_once(episode) -> None:
    first = _created_ticket(episode.started + timedelta(minutes=8))
    second = _created_ticket(episode.started + timedelta(minutes=9), id="ticket-again")
    service = episode.service([second, first])
    result = _evaluate(service.url, run_dir=episode.run_dir)
    assert result.status is EvalStatus.FAIL
    assert result.metadata["failures"][0] == "support_ticket_created_once"


def test_still_signed_in_fails_even_with_the_ticket(episode) -> None:
    service = episode.service([_created_ticket(episode.started + timedelta(minutes=8))])

    stored_token = _evaluate(service.url, token=TOKEN, run_dir=episode.run_dir)
    assert stored_token.status is EvalStatus.FAIL
    assert stored_token.metadata["failures"] == ["app_credential_cleared"]

    workspace = _evaluate(service.url, screen=LOGIN_PAGE + RIDER_WORKSPACE, token=TOKEN, run_dir=episode.run_dir)
    assert workspace.metadata["failures"] == ["final_screen_signed_out", "app_credential_cleared"]


def test_unreachable_service_is_an_environment_error_unless_the_device_already_fails(episode) -> None:
    service = episode.service([])
    url = service.url
    service.close()

    assert _evaluate(url, run_dir=episode.run_dir).status is EvalStatus.ERROR
    signed_in = _evaluate(url, screen=LOGIN_PAGE + RIDER_WORKSPACE, token=TOKEN, run_dir=episode.run_dir)
    assert signed_in.status is EvalStatus.FAIL


def test_rejected_sign_in_is_an_environment_error(episode) -> None:
    service = episode.service([_created_ticket(episode.started + timedelta(minutes=8))], accept_login=False)
    result = _evaluate(service.url, run_dir=episode.run_dir)
    assert result.status is EvalStatus.ERROR
    assert "could not sign in" in result.message


def test_task_binds_the_workflow_evaluator_and_keeps_the_screen_params() -> None:
    task = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    params = task["evaluation"]["params"]
    assert task["evaluation"]["evaluator_id"] == (
        "evaluators.android.opendriver_rider_full_service_logout:OpenDriverRiderLogoutWorkflowEvaluator"
    )
    # Everything the grader requires is stated in the instruction.
    instruction = task["instruction"]
    for text in ("rider@example.com", "password123", "Rider role", "safety concern", "Need ride help",
                 "followed by a reply to the ticket", "logged out"):
        assert text in instruction
    assert params["rider_account"] == {"email": "rider@example.com", "password": "password123", "role": "rider"}
    assert params["support_ticket"]["category"] == "safety concern"
    assert params["support_ticket"]["message"] == "Need ride help"
    assert params["required_any_text_tokens"] == ["Login", "Sign in"]
    assert "Create account" in params["forbidden_text_exempt_phrases"]
