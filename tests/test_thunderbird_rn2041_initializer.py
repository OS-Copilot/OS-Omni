"""Tests for the RN-2041 SMTP sink startup race."""

from __future__ import annotations

from evaluators.cua_review.initializers.macos import thunderbird_rn2041_snapshot as module
from evaluators.cua_review.initializers.macos.thunderbird_rn2041_snapshot import (
    ThunderbirdRN2041SnapshotInitializer,
)
from evaluators.cua_review.core.initialization import InitializationError


def test_capture_mailbox_waits_for_launchctl_child_to_bind(monkeypatch) -> None:
    initializer = ThunderbirdRN2041SnapshotInitializer()
    responses = iter(
        [
            {"listening": False, "capture_exists": True},
            {"listening": False, "capture_exists": True},
            {"listening": False, "capture_exists": True},
            {"listening": True, "capture_exists": True},
        ]
    )
    calls = []
    monkeypatch.setattr(initializer, "_guest_json", lambda *args, **kwargs: (calls.append(1), next(responses))[1])
    monkeypatch.setattr(initializer, "_start_capture_server", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    initializer._ensure_capture_mailbox(object(), {"smtp_start_timeout_seconds": 8})

    assert len(calls) == 4
    assert initializer._service_started is True


def test_capture_mailbox_startup_poll_is_bounded(monkeypatch) -> None:
    initializer = ThunderbirdRN2041SnapshotInitializer()
    monkeypatch.setattr(
        initializer,
        "_guest_json",
        lambda *args, **kwargs: {"listening": False, "capture_exists": True},
    )
    monkeypatch.setattr(initializer, "_start_capture_server", lambda *args, **kwargs: None)
    times = iter([0.0, 0.0, 0.6, 1.1])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    try:
        initializer._ensure_capture_mailbox(object(), {"smtp_start_timeout_seconds": 1})
    except InitializationError as exc:
        assert "did not start on 127.0.0.1:1025" in str(exc)
    else:
        raise AssertionError("initializer should fail after the bounded startup wait")
