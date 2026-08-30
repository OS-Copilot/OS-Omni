from platforms.macos.host.runners.benchmark import (
    MACOS_ENABLE_GUEST_RUNTIME_SYNC_ENV,
    MACOS_SKIP_GUEST_RUNTIME_SYNC_ENV,
    MacOSBenchmarkRunner,
)


def test_guest_runtime_sync_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv(MACOS_ENABLE_GUEST_RUNTIME_SYNC_ENV, raising=False)
    monkeypatch.delenv(MACOS_SKIP_GUEST_RUNTIME_SYNC_ENV, raising=False)

    assert MacOSBenchmarkRunner._guest_runtime_sync_enabled() is False


def test_guest_runtime_sync_can_be_enabled_explicitly(monkeypatch):
    monkeypatch.setenv(MACOS_ENABLE_GUEST_RUNTIME_SYNC_ENV, "1")
    monkeypatch.delenv(MACOS_SKIP_GUEST_RUNTIME_SYNC_ENV, raising=False)

    assert MacOSBenchmarkRunner._guest_runtime_sync_enabled() is True


def test_guest_runtime_sync_skip_env_overrides_enable(monkeypatch):
    monkeypatch.setenv(MACOS_ENABLE_GUEST_RUNTIME_SYNC_ENV, "1")
    monkeypatch.setenv(MACOS_SKIP_GUEST_RUNTIME_SYNC_ENV, "1")

    assert MacOSBenchmarkRunner._guest_runtime_sync_enabled() is False
