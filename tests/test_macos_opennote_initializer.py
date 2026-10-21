from __future__ import annotations

import json
from unittest.mock import patch

from evaluators.cua_review.core.initialization import InitializationError
from evaluators.cua_review.initializers.macos.opennote import (
    DEFAULT_PORT,
    OpenNoteSnapshotInitializer,
)


class RuntimeController:
    def __init__(self):
        self.python_scripts: list[str] = []
        self.launches: list[str] = []

    def run_python_script(self, code: str, *, timeout: int):
        self.python_scripts.append(code)
        if "/api/dev/reset" in code:
            return {"returncode": 0, "output": json.dumps({"ok": True, "logged_in": False})}
        return {"returncode": 0, "output": json.dumps({"stopped": True, "pid_count": 1})}

    def launch_app(self, app_name: str):
        self.launches.append(app_name)
        return {"success": True}


def _state(*, logged_in: bool, email: str = "lina@opennote.local"):
    session = {"loggedIn": logged_in}
    if logged_in:
        session["user"] = {"email": email, "handle": "lina", "displayName": "Lina Park"}
    return {"session": session, "notes": [{"title": "Secondhand coat notes from tiny bedroom"}]}


def test_opennote_initializer_restores_seed_and_relaunches_app():
    initializer = OpenNoteSnapshotInitializer()
    controller = RuntimeController()

    with (
        patch.object(initializer, "_inspect_installation", return_value=(
            "/Applications/OS-Omni Open Apps/OpenNote.app", "local.osomni.opennote"
        )),
        patch.object(initializer, "_wait_for_process", return_value="1234"),
        patch.object(initializer, "_settle", return_value="settled"),
    ):
        initializer._reset_task_snapshot(
            controller,
            DEFAULT_PORT,
            "OpenNote",
            {"wait_ms": 100},
        )

    assert len(controller.python_scripts) == 2
    assert "/api/dev/reset" in controller.python_scripts[0]
    assert "OpenNote.app/Contents/MacOS/OpenAppShell" in controller.python_scripts[1]
    assert controller.launches == ["OpenNote"]


def test_opennote_initializer_restores_seed_even_if_previous_task_is_signed_out():
    initializer = OpenNoteSnapshotInitializer()
    controller = RuntimeController()
    states = [
        _state(logged_in=True),
        _state(logged_in=False),
    ]
    reads = []

    def read_state(*_args, **_kwargs):
        state = states.pop(0)
        reads.append(state)
        return DEFAULT_PORT, {"/api/evaluation": {"status": 200, "body": state}}, []

    with (
        patch.object(initializer, "_read_loopback", side_effect=read_state),
        patch.object(initializer, "_reset_task_snapshot") as reset,
        patch.object(initializer, "_wait_for_visible", return_value="Log In Lina Park"),
    ):
        message = initializer.verify_preconditions(
            controller,
            {
                "expected_account_name": "lina@opennote.local",
                "expected_login_label": "Log In",
                "required_source_note_title": "Secondhand coat notes from tiny bedroom",
            },
        )

    reset.assert_called_once()
    assert "after restoring the seeded task snapshot" in message
    assert initializer._did_boundary_reset is True


def test_opennote_initializer_refuses_to_reset_an_unexpected_account():
    initializer = OpenNoteSnapshotInitializer()
    state = _state(logged_in=True, email="someone-else@example.invalid")

    with (
        patch.object(
            initializer,
            "_read_loopback",
            return_value=(DEFAULT_PORT, {"/api/evaluation": {"status": 200, "body": state}}, []),
        ),
        patch.object(initializer, "_reset_task_snapshot") as reset,
    ):
        try:
            initializer.verify_preconditions(
                RuntimeController(), {"expected_account_name": "lina@opennote.local"}
            )
        except InitializationError as exc:
            assert "unexpected account" in str(exc)
        else:
            raise AssertionError("initializer must reject an unrelated active account")

    reset.assert_not_called()
