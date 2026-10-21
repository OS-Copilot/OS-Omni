from __future__ import annotations

import json
from unittest.mock import patch

from evaluators.cua_review.core.initialization import InitializationError
from evaluators.cua_review.initializers.macos.openbank import (
    DEFAULT_PORT,
    OpenBankSnapshotInitializer,
)


class RuntimeController:
    def __init__(self):
        self.python_scripts: list[str] = []
        self.launches: list[str] = []

    def launch_app(self, app_name: str):
        self.launches.append(app_name)
        return {"success": True}


def _state(*, logged_in: bool, email: str = "jordan@openbank.local"):
    session = {"loggedIn": logged_in}
    if logged_in:
        session["user"] = {
            "id": "cust-jordan" if email == "jordan@openbank.local" else "cust-other",
            "displayName": "Jordan Lee" if email == "jordan@openbank.local" else "Other User",
            "email": email,
        }
    return {
        "session": session,
        "customer": {"id": "cust-jordan", "displayName": "Jordan Lee", "email": "jordan@openbank.local"},
        "accounts": [{"id": "checking-2381"}, {"id": "savings-9140"}],
        "billers": [{"id": "bill-city-utilities"}, {"id": "bill-northstar-internet"}],
        "recipients": [{"id": "rec-maya"}, {"id": "rec-rainy-day"}],
        "transactions": [],
        "billPayments": [],
        "transfers": [],
    }


def test_initializer_resets_expected_prior_session_and_verifies_fresh_seed():
    initializer = OpenBankSnapshotInitializer()
    controller = RuntimeController()
    states = [_state(logged_in=True), _state(logged_in=False)]

    def read_state(*_args, **_kwargs):
        state = states.pop(0)
        return DEFAULT_PORT, {"/api/evaluation": {"status": 200, "body": state}}, []

    with (
        patch.object(initializer, "_read_loopback", side_effect=read_state),
        patch.object(initializer, "_reset_task_snapshot") as reset,
        patch.object(initializer, "_check_indexed"),
        patch.object(initializer, "_check_absent_file"),
        patch.object(initializer, "_wait_for_visible", return_value="Sign In Jordan"),
    ):
        message = initializer.verify_preconditions(
            controller,
            {
                "expected_customer_id": "cust-jordan",
                "expected_customer_email": "jordan@openbank.local",
                "required_absent_file": "~/Desktop/Reserve-Plan.txt",
            },
        )

    reset.assert_called_once_with(controller, DEFAULT_PORT, {
        "expected_customer_id": "cust-jordan",
        "expected_customer_email": "jordan@openbank.local",
        "required_absent_file": "~/Desktop/Reserve-Plan.txt",
    })
    assert "after restoring the per-task app snapshot" in message


def test_initializer_refuses_to_reset_unexpected_signed_in_user():
    initializer = OpenBankSnapshotInitializer()
    state = _state(logged_in=True, email="other@example.invalid")
    with (
        patch.object(
            initializer,
            "_read_loopback",
            return_value=(DEFAULT_PORT, {"/api/evaluation": {"status": 200, "body": state}}, []),
        ),
        patch.object(initializer, "_reset_task_snapshot") as reset,
    ):
        try:
            initializer.verify_preconditions(RuntimeController(), {})
        except InitializationError as exc:
            assert "unexpected account" in str(exc)
        else:
            raise AssertionError("initializer must not reset an unrelated active account")
    reset.assert_not_called()


def test_task_snapshot_reset_uses_dev_reset_cleans_only_expected_desktop_file_and_relaunches():
    initializer = OpenBankSnapshotInitializer()
    controller = RuntimeController()
    calls = []

    def guest_python(_controller, code, *, timeout):
        compile(code, "<guest-reset>", "exec")
        calls.append(code)
        if "/api/dev/reset" in code:
            return {"returncode": 0, "stdout": json.dumps({"ok": True, "logged_in": False})}
        return {"returncode": 0, "stdout": json.dumps({"stopped": True, "pid_count": 1})}

    params = {"app_name": "OpenBank", "required_absent_file": "~/Desktop/Reserve-Plan.txt"}
    with (
        patch.object(initializer, "_guest_python", side_effect=guest_python),
        patch.object(
            initializer,
            "_inspect_installation",
            return_value=("/Applications/OS-Omni Open Apps/OpenBank.app", "local.osomni.openbank"),
        ),
        patch.object(initializer, "_wait_for_process", return_value="1234"),
        patch.object(initializer, "_settle", return_value="settled"),
    ):
        initializer._reset_task_snapshot(controller, DEFAULT_PORT, params)

    assert len(calls) == 2
    assert "/api/dev/reset" in calls[0]
    assert "Reserve-Plan.txt" in calls[0]
    assert "target.parent.resolve() != desktop.resolve()" in calls[0]
    assert "OpenAppShell" in calls[1]
    assert controller.launches == ["OpenBank"]
