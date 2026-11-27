from initializers.macos.blender import BlenderInitializer


class FakeController:
    width = 1920
    height = 1080

    def __init__(self):
        self.bash = []
        self.python = []

    def run_bash_script(self, script, timeout=None):
        self.bash.append(script)
        return {"status": "success", "returncode": 0, "output": ""}

    def run_python_script(self, script, timeout=None):
        self.python.append((script, timeout))
        return {"status": "success", "returncode": 0, "output": ""}


def test_blender_initializer_uses_launchservices_and_resolves_app_bundle():
    controller = FakeController()

    BlenderInitializer()._launch_app(
        controller,
        app_command="/Applications/Blender.app/Contents/MacOS/Blender",
        blend_path="/Users/bench/Downloads/scene.blend",
        launch_args=["--debug-gpu-force-workarounds"],
    )

    assert len(controller.bash) == 1
    assert "open -a /Applications/Blender.app --args" in controller.bash[0]
    assert "open -a /Applications/Blender.app /Users/bench/Downloads/scene.blend" in controller.bash[0]
    assert 'tell application "System Events"' in controller.bash[0]
    assert 'name is not "Blender"' in controller.bash[0]
    assert 'tell application "Blender" to activate' in controller.bash[0]


def test_blender_initializer_completes_first_run_quick_setup_without_ax_tree():
    controller = FakeController()

    BlenderInitializer()._dismiss_splash(controller)

    assert len(controller.python) == 1
    script, timeout = controller.python[0]
    assert "pyautogui.click(960, 771)" in script
    assert "pyautogui.press('escape')" in script
    assert timeout == 8
