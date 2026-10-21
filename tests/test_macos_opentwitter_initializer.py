from __future__ import annotations

import json

import pytest

from evaluators.cua_review.core.initialization import InitializationError
from evaluators.cua_review.initializers.macos.opentwitter import OpenTwitterInitializer


class FakeController:
    def launch_app(self, name):
        return {"success": True}


class FakeOpenTwitterInitializer(OpenTwitterInitializer):
    def __init__(self, *, logged_in=True, account="Alex Chen"):
        super().__init__()
        self.logged_in = logged_in
        self.account = account
        self.reset_count = 0

    def _read_loopback(self, controller, candidates, paths, **kwargs):
        document = {
            "session": {"loggedIn": self.logged_in, "user": {"name": self.account}},
            "posts": [{"text": "Seed community announcement"}],
        }
        return 4350, {"/api/evaluation": {"status": 200, "body": document}}, []

    def _guest_python(self, controller, script, *, timeout=20):
        assert "/api/dev/reset" in script
        self.reset_count += 1
        self.logged_in = False
        return {"returncode": 0, "stdout": json.dumps({"ok": True, "logged_in": False})}

    def _restart_app(self, controller, app_name):
        assert app_name == "OpenTwitter"


def test_signed_in_expected_account_is_reset_to_signed_out_seed():
    initializer = FakeOpenTwitterInitializer()
    description = initializer.verify_preconditions(
        FakeController(),
        {
            "expected_account_name": "Alex Chen",
            "required_phrases": ["Seed community announcement"],
            "forbidden_target_posts": ["Community map ready"],
        },
    )
    assert initializer.reset_count == 1
    assert initializer.logged_in is False
    assert initializer._did_boundary_reset is True
    assert "after restoring" in description


def test_signed_in_unexpected_account_is_not_reset():
    initializer = FakeOpenTwitterInitializer(account="Someone Else")
    with pytest.raises(InitializationError, match="no Alex Chen account"):
        initializer.verify_preconditions(
            FakeController(),
            {"expected_account_name": "Alex Chen", "required_phrases": ["Seed community announcement"]},
        )
    assert initializer.reset_count == 0


def test_signed_out_seed_is_left_untouched():
    initializer = FakeOpenTwitterInitializer(logged_in=False)
    initializer.verify_preconditions(
        FakeController(),
        {"expected_account_name": "Alex Chen", "required_phrases": ["Seed community announcement"]},
    )
    assert initializer.reset_count == 0
    assert initializer._did_boundary_reset is False
