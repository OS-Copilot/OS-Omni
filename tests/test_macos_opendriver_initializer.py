from __future__ import annotations

from evaluators.cua_review.core.initialization import InitializationError
from evaluators.cua_review.initializers.macos.opendriver import (
    DEFAULT_BACKEND_DIR,
    OpenDriverInitializer,
)


class SeedController:
    def __init__(self, seed_returncode: int = 0, quit_returncode: int = 0):
        self.seed_returncode = seed_returncode
        self.quit_returncode = quit_returncode
        self.calls: list[tuple[str, int]] = []

    def run_bash_script(self, script: str, *, timeout: int):
        self.calls.append((script, timeout))
        if "npm run seed" in script:
            return {
                "returncode": self.seed_returncode,
                "stdout": "Seeded opendriver backend\n" if not self.seed_returncode else "",
                "stderr": "seed failed" if self.seed_returncode else "",
            }
        return {"returncode": self.quit_returncode, "stdout": "", "stderr": ""}


def test_opendriver_initializer_reseeds_only_its_app_and_quits_stale_ui():
    controller = SeedController()

    OpenDriverInitializer._restore_seeded_state(controller, {})

    assert len(controller.calls) == 2
    seed_script, seed_timeout = controller.calls[0]
    assert "npm run seed" in seed_script
    assert '"$HOME"/' in seed_script
    assert DEFAULT_BACKEND_DIR.removeprefix("~/") in seed_script
    assert seed_timeout == 60
    quit_script, quit_timeout = controller.calls[1]
    assert "local.osomni.opendriver" in quit_script
    assert "OpenDriver.app/Contents/MacOS/OpenAppShell" in quit_script
    assert quit_timeout == 12


def test_opendriver_initializer_stops_when_seed_command_fails():
    controller = SeedController(seed_returncode=1)

    try:
        OpenDriverInitializer._restore_seeded_state(controller, {})
    except InitializationError as exc:
        assert "seed data could not be restored" in str(exc)
    else:
        raise AssertionError("a failed seed command must stop initialization")

    assert len(controller.calls) == 1


def test_opendriver_initializer_stops_when_stale_app_does_not_quit():
    controller = SeedController(quit_returncode=1)

    try:
        OpenDriverInitializer._restore_seeded_state(controller, {})
    except InitializationError as exc:
        assert "did not quit" in str(exc)
    else:
        raise AssertionError("a stale app process must stop initialization")
