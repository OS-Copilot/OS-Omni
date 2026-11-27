"""Evaluator for ``android.opendriver.rider_full_service_logout``.

The task ends on the OpenDriver login page, which is also the page the episode
starts on, so the final screen alone cannot tell a finished workflow from an
untouched one.  The instruction's own business actions leave a durable record
in the OpenDriver service the application talks to: signing in is required to
create a support ticket, and the ticket ("safety concern", "Need ride help")
and the reply sent to it stay in the service after the application signs out.

This evaluator therefore requires

* the final screen to be the signed-out login page (the task's original
  ``ForegroundTextEvaluator`` check, unchanged);
* the application to hold no service credential any more (logout deletes the
  stored token, ``TokenStore.clear`` in the installed APK); and
* the signed-in rider's service record to contain exactly one support ticket
  created during this episode with the instructed category and message, with
  at least one reply sent by that rider.

Once the application has signed out it carries no credential to read the
rider's tickets with, so the evaluator signs in to the service itself with the
account the instruction names (``POST /auth/login``) and then only reads
(``GET /support/tickets``).  Signing in opens a session (the reconstructed
service in ``local_eval`` also logs the request) and changes no business
record; the evaluator never signs out, because the service cancels a seeded
account's active rides on logout.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.android.cua_review_state import ForegroundTextEvaluator

DEFAULT_APP_PACKAGE = "com.killt.opendriver"
DEFAULT_API_BASE_URL = "http://10.0.2.2:4321"
REQUEST_TIMEOUT_SECONDS = 30.0

#: Where the installed APK's TokenStore keeps the credential (see
#: ``evaluators/cua_review/platforms/android/opendriver_support.py``).
TOKEN_PATHS = (
    "code_cache/opendriver/auth_token.txt",
    "cache/opendriver/auth_token.txt",
    "files/.opendriver/auth_token.txt",
)

#: Allowance for timestamp rounding when bounding the episode start.
EPISODE_START_SLACK_SECONDS = 5.0


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").split())


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _host_url(url: str) -> str:
    # 10.0.2.2 is the emulator's alias for the host; the evaluator runs on the
    # host and reaches the same service on loopback.
    parsed = urlsplit(url)
    if parsed.hostname == "10.0.2.2":
        netloc = "127.0.0.1" + (f":{parsed.port}" if parsed.port else "")
        return urlunsplit(parsed._replace(netloc=netloc))
    return url


def _request_json(
    method: str, url: str, *, body: Mapping[str, Any] | None = None, token: str = ""
) -> tuple[int | None, Any, str]:
    """Return ``(http_status, decoded_payload, error)`` for one request."""
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(dict(body)).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(_host_url(url), data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status, raw = response.status, response.read()
    except HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (URLError, OSError) as exc:
        return None, None, f"unreachable: {getattr(exc, 'reason', exc)}"
    try:
        decoded = json.loads(raw.decode("utf-8", errors="replace") or "null")
    except json.JSONDecodeError:
        return status, None, "response is not JSON"
    # Both service builds wrap payloads as {"success": true, "data": {...}}.
    if isinstance(decoded, Mapping) and decoded.get("success") is True and isinstance(decoded.get("data"), Mapping):
        decoded = decoded["data"]
    return status, decoded, ""


def _stored_credential(controller: Any, app_package: str) -> dict[str, Any]:
    """Report whether the application still stores a service credential."""
    readable = False
    for path in TOKEN_PATHS:
        try:
            raw = str(controller.execute_adb(["shell", "run-as", app_package, "cat", path]) or "").strip()
        except Exception:  # noqa: BLE001 - an unreadable path is not a credential
            continue
        readable = True
        # Same acceptance rule as opendriver_support.read_app_credential: a
        # token is one whitespace-free string; "No such file" errors are not.
        if raw and len(raw) >= 20 and not any(char.isspace() for char in raw):
            return {"credential_present": True, "path": path, "paths_checked": list(TOKEN_PATHS)}
    return {"credential_present": False, "storage_readable": readable, "paths_checked": list(TOKEN_PATHS)}


def _episode_started_at(context: Mapping[str, Any]) -> tuple[datetime | None, str]:
    """Return when the agent's first step began, from the run's trajectory.

    A step record is stamped after its action ran and carries the step's
    observe+plan+act latency, so ``timestamp - latency`` is before the agent's
    first action.  Without a trajectory (evaluate-only runs) no bound applies.
    """
    run_dir = str(context.get("run_dir") or "").strip()
    path = Path(run_dir) / "trajectory.jsonl" if run_dir else None
    if path is None or not path.is_file():
        return None, "no trajectory.jsonl; tickets are not bounded by the episode start"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                stamped = _parse_time(record.get("timestamp"))
                if stamped is None:
                    break
                latency_ms = float(record.get("latency_ms") or 0.0)
                started = stamped - timedelta(milliseconds=max(latency_ms, 0.0))
                return started - timedelta(seconds=EPISODE_START_SLACK_SECONDS), str(path)
    except (OSError, ValueError, TypeError) as exc:
        return None, f"trajectory unreadable ({type(exc).__name__}); tickets are not bounded"
    return None, "trajectory has no timestamped step; tickets are not bounded"


def _items(payload: Any, key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key) if isinstance(payload, Mapping) else None
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


class OpenDriverRiderLogoutWorkflowEvaluator(BaseEvaluator):
    """Final signed-out screen plus the support ticket the rider created and replied to."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        api_base_url = str(params.get("api_base_url") or DEFAULT_API_BASE_URL).rstrip("/")
        account = dict(params.get("rider_account") or {})
        ticket_spec = dict(params.get("support_ticket") or {})
        email = str(account.get("email") or "").strip()
        password = str(account.get("password") or "")
        role = str(account.get("role") or "rider").strip()
        category = str(ticket_spec.get("category") or "").strip()
        message = _normalize(ticket_spec.get("message"))
        min_replies = int(ticket_spec.get("min_rider_replies", 1) or 0)
        if not (email and password and category and message):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params rider_account and support_ticket are required",
            )
        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.execute_adb is required")

        checks: dict[str, bool] = {}
        metadata: dict[str, Any] = {"app_package": app_package, "api_base_url": api_base_url}

        screen = ForegroundTextEvaluator().evaluate(context)
        metadata["final_screen"] = {"status": screen.status.value, "message": screen.message, **dict(screen.metadata or {})}
        if screen.status is EvalStatus.ERROR:
            return EvalResult(status=EvalStatus.ERROR, message=screen.message, metadata=metadata)
        checks["final_screen_signed_out"] = screen.status is EvalStatus.PASS

        credential = _stored_credential(controller, app_package)
        metadata["app_credential"] = credential
        checks["app_credential_cleared"] = not credential["credential_present"]

        backend_error = ""
        status, login, error = _request_json(
            "POST", f"{api_base_url}/auth/login", body={"email": email, "password": password, "role": role}
        )
        token = str(login.get("token") or "") if isinstance(login, Mapping) else ""
        user = login.get("user") if isinstance(login, Mapping) and isinstance(login.get("user"), Mapping) else {}
        metadata["service_sign_in"] = {"http_status": status, "error": error, "user_id": user.get("id"), "email": email, "role": role}
        tickets: list[Mapping[str, Any]] = []
        if not token:
            backend_error = f"could not sign in to the OpenDriver service as {email}: {error or f'HTTP {status}'}"
        else:
            status, payload, error = _request_json("GET", f"{api_base_url}/support/tickets", token=token)
            metadata["support_tickets_read"] = {"http_status": status, "error": error}
            if error or status != 200 or not isinstance(payload, Mapping) or not isinstance(payload.get("tickets"), list):
                backend_error = f"could not read the rider's support tickets: {error or f'HTTP {status}'}"
            else:
                tickets = _items(payload, "tickets")

        if backend_error:
            metadata["backend_error"] = backend_error
            metadata["checks"] = checks
            failures = [name for name, passed in checks.items() if not passed]
            metadata["failures"] = failures
            # A definite failure on the device side stands; otherwise the
            # requested workflow cannot be judged without the service.
            if failures:
                return EvalResult(status=EvalStatus.FAIL, message="OpenDriver rider is not signed out", metadata=metadata)
            return EvalResult(status=EvalStatus.ERROR, message=backend_error, metadata=metadata)

        started_at, start_source = _episode_started_at(context)
        metadata["episode_started_at"] = started_at.isoformat() if started_at else None
        metadata["episode_start_source"] = start_source
        user_id = str(user.get("id") or "")

        def own(item: Mapping[str, Any]) -> bool:
            owner = str(item.get("userId") or "")
            return not owner or not user_id or owner == user_id

        def fresh(item: Mapping[str, Any]) -> bool:
            created = _parse_time(item.get("createdAt"))
            return started_at is None or created is None or created >= started_at

        matching = [
            item
            for item in tickets
            if own(item)
            and str(item.get("category") or "").strip() == category
            and _normalize(item.get("message")) == message
        ]
        created = [item for item in matching if fresh(item)]
        metadata["support_ticket"] = {
            "expected": {"category": category, "message": message, "min_rider_replies": min_replies},
            "matching_ticket_ids": [item.get("id") for item in matching],
            "created_this_episode_ids": [item.get("id") for item in created],
            "observed_tickets": [
                {
                    "id": item.get("id"),
                    "category": item.get("category"),
                    "message": item.get("message"),
                    "createdAt": item.get("createdAt"),
                    "replies": len(_items(item, "replies")),
                }
                for item in tickets
            ],
        }
        # "A support ticket must be created": the business action happens once.
        checks["support_ticket_created_once"] = len(created) == 1

        replies: list[Mapping[str, Any]] = []
        if len(created) == 1:
            replies = [
                reply
                for reply in _items(created[0], "replies")
                if _normalize(reply.get("message"))
                and (
                    (user_id and str(reply.get("userId") or "") == user_id)
                    or (not reply.get("userId") and str(reply.get("role") or "") == role)
                )
            ]
        metadata["support_ticket"]["rider_replies"] = [
            {"id": reply.get("id"), "message": reply.get("message"), "createdAt": reply.get("createdAt")}
            for reply in replies
        ]
        # "... followed by a reply to the ticket".
        checks["support_ticket_replied"] = len(replies) >= max(min_replies, 1)

        failures = [name for name, passed in checks.items() if not passed]
        metadata["checks"] = checks
        metadata["failures"] = failures
        if failures:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="OpenDriver rider workflow incomplete: " + ", ".join(failures),
                metadata=metadata,
            )
        return EvalResult(
            status=EvalStatus.PASS,
            message="Rider signed out after creating and replying to the requested support ticket",
            metadata=metadata,
        )


__all__ = ["OpenDriverRiderLogoutWorkflowEvaluator"]
