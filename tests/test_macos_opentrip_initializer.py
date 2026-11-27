from __future__ import annotations

import json

import pytest

from evaluators.cua_review.core.initialization import InitializationError
from evaluators.cua_review.initializers.macos.opentrip import OpenTripInitializer


class FakeController:
    def __init__(self):
        self.launches = []

    def launch_app(self, name):
        self.launches.append(name)
        return {"success": True}


class FakeOpenTripInitializer(OpenTripInitializer):
    def __init__(self, *, logged_in=True, phone="13900002026", thunderbird_stopped=True):
        super().__init__()
        self.logged_in = logged_in
        self.phone = phone
        self.thunderbird_stopped = thunderbird_stopped
        self.reset_calls = []
        self.guest_scripts = []

    def _read_loopback(self, controller, candidates, paths, **kwargs):
        session = {"loggedIn": self.logged_in, "user": {"phone": self.phone} if self.logged_in else None}
        body = {
            "/api/session": {"session": session},
            "/api/bookings": {"bookings": []},
            "/api/benchmark": {"benchmarkMode": self.reset_calls[-1] if self.reset_calls else "old", "events": []},
        }
        return 4330, {path: {"status": 200, "body": body[path]} for path in paths}, []

    def _guest_python(self, controller, script, *, timeout=20):
        self.guest_scripts.append(script)
        if "/api/dev/reset" in script:
            marker = "payload = "
            payload_expr = script.split(marker, 1)[1].split(".encode", 1)[0]
            payload = json.loads(payload_expr[1:-1])
            mode = payload["benchmarkMode"]
            self.reset_calls.append(mode)
            self.logged_in = False
            return {"returncode": 0, "stdout": json.dumps({"ok": True, "logged_in": False, "benchmark_mode": mode})}
        if "def thunderbird_pids()" in script:
            return {
                "returncode": 0,
                "stdout": json.dumps({"running_before": True, "stopped": self.thunderbird_stopped}),
            }
        return {"returncode": 0, "stdout": json.dumps({"stopped": True, "pid_count": 1})}

    def _inspect_installation(self, controller, app_name):
        return "/Applications/OpenTrip.app", {}

    def _wait_for_process(self, controller, app_path):
        return "42"

    def _settle(self, params):
        return "settled"

    def _wait_for_visible(self, controller, markers, **kwargs):
        assert "13900002026" in markers
        return "sign in Lucas Lin"


def test_initializer_resets_known_account_for_serial_task_boundary():
    initializer = FakeOpenTripInitializer()
    result = initializer.verify_preconditions(
        FakeController(),
        {
            "expected_logged_in": False,
            "expected_account_phone": "13900002026",
            "benchmark_mode": "macos.opentrip.test",
            "expected_seed": {"account": {"phone": "13900002026", "name": "Lucas Lin"}},
        },
    )
    assert initializer.reset_calls == ["macos.opentrip.test"]
    assert any("org.mozilla.thunderbird" in script for script in initializer.guest_scripts)
    assert "signed out" in result
    assert initializer._did_boundary_reset is True


def test_initializer_refuses_to_reset_unexpected_signed_in_account():
    initializer = FakeOpenTripInitializer(phone="999")
    with pytest.raises(InitializationError, match="unexpected account"):
        initializer.verify_preconditions(
            FakeController(),
            {"expected_account_phone": "13900002026", "benchmark_mode": "macos.opentrip.test"},
        )
    assert initializer.reset_calls == []


def test_initializer_fails_closed_if_thunderbird_overlay_cannot_be_closed():
    initializer = FakeOpenTripInitializer(thunderbird_stopped=False)
    controller = FakeController()

    with pytest.raises(InitializationError, match="Thunderbird remained open"):
        initializer.verify_preconditions(
            controller,
            {
                "expected_account_phone": "13900002026",
                "benchmark_mode": "macos.opentrip.test",
                "expected_seed": {"account": {"phone": "13900002026", "name": "Lucas Lin"}},
            },
        )

    assert controller.launches == []
