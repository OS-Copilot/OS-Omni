import io

from PIL import Image

from platforms.macos.host.runners.episode import runtime_screen_smoke_check
from platforms.macos.host.runtime_env.vm_runtime_controller import Observation


def _png_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(32, 64, 96)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeController:
    def __init__(self, observation: Observation):
        self.observation = observation

    def observe(self, *, include_ui_tree: bool, include_screenshot_data: bool) -> Observation:
        assert include_ui_tree is False
        assert include_screenshot_data is True
        return self.observation


def test_runtime_screen_smoke_check_accepts_matching_1920x1080_screenshot():
    controller = _FakeController(
        Observation(
            timestamp="20260527_000000_000",
            width=1920,
            height=1080,
            screenshot_data=_png_bytes(1920, 1080),
        )
    )

    ok, detail = runtime_screen_smoke_check(controller)

    assert ok is True
    assert "1920x1080" in detail


def test_runtime_screen_smoke_check_rejects_non_default_resolution():
    controller = _FakeController(
        Observation(
            timestamp="20260527_000000_000",
            width=4480,
            height=2520,
            screenshot_data=_png_bytes(4480, 2520),
        )
    )

    ok, detail = runtime_screen_smoke_check(controller)

    assert ok is False
    assert "expected 1920x1080" in detail


def test_runtime_screen_smoke_check_rejects_metadata_image_size_mismatch():
    controller = _FakeController(
        Observation(
            timestamp="20260527_000000_000",
            width=1920,
            height=1080,
            screenshot_data=_png_bytes(3840, 2160),
        )
    )

    ok, detail = runtime_screen_smoke_check(controller)

    assert ok is False
    assert "does not match observation metadata" in detail
