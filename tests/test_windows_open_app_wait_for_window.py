from types import SimpleNamespace

from core.init import InitStatus
from initializers.windows.open_app import OpenAppInitializer


class _Controller:
    def __init__(self, titles):
        self.titles = list(titles)
        self.launched = []

    def launch_app(self, name):
        self.launched.append(name)

    def observe(self, include_ui_tree=True, include_screenshot_data=True):
        title = self.titles.pop(0) if len(self.titles) > 1 else self.titles[0]
        return SimpleNamespace(foreground_window=title)


def test_waits_until_window_is_foreground(monkeypatch):
    monkeypatch.setattr("initializers.windows.open_app.time.sleep", lambda _: None)
    controller = _Controller(["", "Program Manager", "OpenTwitter - Sign In"])
    result = OpenAppInitializer().initialize(
        {"controller": controller, "params": {"app_name": "OpenTwitter", "wait_ms": 0, "wait_for_window": "opentwitter"}}
    )

    assert result.status == InitStatus.PASS
    assert result.metadata["window"] == "OpenTwitter - Sign In"
    assert controller.launched == ["OpenTwitter"]


def test_window_timeout_is_an_error_and_does_not_relaunch(monkeypatch):
    monkeypatch.setattr("initializers.windows.open_app.time.sleep", lambda _: None)
    controller = _Controller(["Program Manager"])
    result = OpenAppInitializer().initialize(
        {"controller": controller,
         "params": {"app_name": "OpenTwitter", "wait_for_window": "OpenTwitter", "window_timeout_ms": 0}}
    )

    assert result.status == InitStatus.ERROR
    assert "Program Manager" in result.message
    assert controller.launched == ["OpenTwitter"]


def test_without_wait_for_window_only_sleeps(monkeypatch):
    monkeypatch.setattr("initializers.windows.open_app.time.sleep", lambda _: None)
    controller = _Controller(["Program Manager"])
    result = OpenAppInitializer().initialize({"controller": controller, "params": {"app_name": "Notepad"}})

    assert result.status == InitStatus.PASS
    assert "window" not in result.metadata
