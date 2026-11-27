from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from evaluators.cua_review.core.initialization import InitializationError
from evaluators.cua_review.initializers.macos.openshop import (
    DEFAULT_PORT,
    OpenShopSnapshotInitializer,
)


class FakeController:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.python_scripts = []
        self.launches = []

    def run_python_script(self, script, *, timeout):
        self.python_scripts.append(script)
        return self.outputs.pop(0)

    def launch_app(self, app_name):
        self.launches.append(app_name)
        return {"success": True}


def test_initializer_resets_same_expected_account_and_verifies_seed():
    initializer = OpenShopSnapshotInitializer()
    controller = FakeController([])
    before = {
        "/api/session": {
            "status": 200,
            "body": {"session": {"loggedIn": True, "user": {"phone": "13800138000"}}},
        }
    }
    after = {
        "/api/session": {"status": 200, "body": {"session": {"loggedIn": False, "user": None}}},
        "/api/benchmark": {"status": 200, "body": {"benchmarkMode": "task-1", "events": []}},
    }
    with (
        patch.object(initializer, "_read_loopback", side_effect=[(DEFAULT_PORT, before, []), (DEFAULT_PORT, after, [])]),
        patch.object(initializer, "_reset_task_snapshot") as reset,
        patch.object(initializer, "_verify_seed_assets") as verify_seed,
        patch.object(initializer, "_wait_for_visible", return_value="Lucas Lin / Password"),
    ):
        message = initializer.verify_preconditions(
            controller,
            {"benchmark_mode": "task-1", "expected_account_card": "Lucas Lin"},
        )

    reset.assert_called_once_with(controller, DEFAULT_PORT, "OpenShop", "task-1")
    verify_seed.assert_called_once()
    assert "restored the task seed" in message
    assert initializer._did_boundary_reset is True


def test_initializer_refuses_to_reset_unexpected_signed_in_account():
    initializer = OpenShopSnapshotInitializer()
    state = {
        "/api/session": {
            "status": 200,
            "body": {"session": {"loggedIn": True, "user": {"phone": "00000000000"}}},
        }
    }
    with (
        patch.object(initializer, "_read_loopback", return_value=(DEFAULT_PORT, state, [])),
        patch.object(initializer, "_reset_task_snapshot") as reset,
    ):
        with pytest.raises(InitializationError, match="unexpected account"):
            initializer.verify_preconditions(FakeController([]), {})
    reset.assert_not_called()


def test_reset_endpoint_and_restart_are_verified():
    initializer = OpenShopSnapshotInitializer()
    controller = FakeController(
        [
            {
                "returncode": 0,
                "output": json.dumps(
                    {"ok": True, "logged_in": False, "cart_empty": True, "benchmark_mode": "task-2"}
                ),
            },
            {"returncode": 0, "output": json.dumps({"stopped": True, "pid_count": 1})},
        ]
    )
    with (
        patch.object(initializer, "_inspect_installation", return_value=("/Applications/OpenShop.app", "local.osomni.openshop")),
        patch.object(initializer, "_wait_for_process", return_value="123"),
        patch.object(initializer, "_settle", return_value="settled"),
    ):
        initializer._reset_task_snapshot(controller, DEFAULT_PORT, "OpenShop", "task-2")

    assert "/api/dev/reset" in controller.python_scripts[0]
    assert "task-2" in controller.python_scripts[0]
    assert "Info.plist" in controller.python_scripts[1]
    assert controller.launches == ["OpenShop"]
    assert initializer._did_boundary_reset is True
