from evaluators.cua_review.initializers.macos.deltachat_snapshot import (
    DeltaChatSnapshotInitializer,
)


class FakeController:
    def __init__(self):
        self.calls = []

    def run_bash_script(self, script, timeout=None):
        self.calls.append(("run_bash_script", script, timeout))
        return {"returncode": 0, "status": "success"}

    def launch_app(self, app_name):
        self.calls.append(("launch_app", app_name))
        return {"success": True}

    def hotkey(self, keys):
        self.calls.append(("hotkey", keys))
        return {"success": True}


class TestableDeltaChatInitializer(DeltaChatSnapshotInitializer):
    def _wait_for_process(self, controller, app_path):
        return "4242"


def test_launch_dismisses_transient_overlay_and_refocuses_deltachat():
    controller = FakeController()

    result = TestableDeltaChatInitializer()._launch(
        controller, "DeltaChat", "/Applications/DeltaChat.app"
    )

    assert controller.calls == [
        (
            "run_bash_script",
            "/usr/bin/killall CharacterPalette 2>/dev/null || true",
            10,
        ),
        ("launch_app", "DeltaChat"),
        ("hotkey", "escape"),
        ("hotkey", "escape"),
        ("launch_app", "DeltaChat"),
    ]
    assert "dismissed transient overlays" in result
