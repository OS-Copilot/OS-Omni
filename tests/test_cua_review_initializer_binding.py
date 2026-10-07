"""Reviewed release initializers run under the OS-Omni initializer contract."""

from __future__ import annotations

from types import SimpleNamespace

from core.init import InitStatus, load_initializer
from evaluators.cua_review.core.evaluation import EvalResult, EvalStatus
from evaluators.cua_review.core.init_binding import (
    ReleaseControllerView,
    ReleaseInitializerAdapter,
)


class _RecordingRelease:
    def __init__(self, status=EvalStatus.PASS) -> None:
        self.status = status
        self.context = None

    def initialize(self, context):
        self.context = context
        return EvalResult(status=self.status, message="done", metadata={"stage": 1})


def test_vendored_release_initializer_is_adapted_by_the_loader() -> None:
    initializer = load_initializer(
        "evaluators.cua_review.initializers.android.openbank:OpenBankInitializer"
    )

    assert isinstance(initializer, ReleaseInitializerAdapter)


def test_adapter_converts_result_and_binds_ios_udid() -> None:
    release = _RecordingRelease()
    controller = SimpleNamespace(runtime=SimpleNamespace(udid="SIM-1"))

    result = ReleaseInitializerAdapter(release).initialize({"params": {}, "controller": controller})

    assert result.status == InitStatus.PASS
    assert result.metadata["stage"] == 1
    assert release.context["udid"] == "SIM-1"
    assert isinstance(release.context["controller"], ReleaseControllerView)


def test_adapter_maps_undetermined_to_error() -> None:
    result = ReleaseInitializerAdapter(_RecordingRelease(EvalStatus.UNDETERMINED)).initialize({})

    assert result.status == InitStatus.ERROR


def test_controller_view_normalizes_script_output_and_observation() -> None:
    controller = SimpleNamespace(
        run_bash_script=lambda script, timeout=30: {"status": "success", "output": "42\n"},
        observe=lambda: SimpleNamespace(ui_nodes=[{"text": "Ready"}], foreground_app="App"),
        health=lambda: {"status": "healthy"},
    )
    view = ReleaseControllerView(controller)

    result = view.run_bash_script("echo 42", timeout=5)
    assert (result["returncode"], result["stdout"], result["output"]) == (0, "42\n", "42\n")
    assert view.observe()["ui_nodes"] == [{"text": "Ready"}]
    assert view.is_alive() is True


def test_controller_view_offers_android_fallbacks_only_with_their_primitive() -> None:
    calls = []
    dumps = {
        "activity": "    topResumedActivity=ActivityRecord{11f20ac u0 com.killt.openbank/.Main} t2019}\n",
        "window": "",
    }

    def execute_adb(args):
        calls.append(args)
        return dumps.get(args[2], "") if args[:2] == ["shell", "dumpsys"] else ""

    view = ReleaseControllerView(SimpleNamespace(execute_adb=execute_adb))

    # Android 13 dumpsys output, which OS-Omni's get_current_activity() does not match.
    assert view.foreground_package() == "com.killt.openbank"
    dumps.update(activity="", window="  mCurrentFocus=Window{e59790e u0 chat.delta/org.Main}\n")
    assert view.foreground_package() == "chat.delta"
    calls.clear()
    view.start_app("com.killt.openbank", "com.killt.openbank.MainActivity")
    view.start_app("com.killt.openbank")
    assert calls[0] == ["shell", "am", "start", "-n", "com.killt.openbank/com.killt.openbank.MainActivity"]
    assert calls[1][:4] == ["shell", "monkey", "-p", "com.killt.openbank"]
    assert not hasattr(ReleaseControllerView(SimpleNamespace()), "start_app")
    assert not hasattr(view, "is_alive")


def test_patched_android_base_accepts_real_pm_path_output() -> None:
    from evaluators.cua_review.initializers.android._base import BaseAndroidInitializer

    controller = SimpleNamespace(
        execute_adb=lambda args: "package:/data/app/~~abc==/com.killt.openbank-xyz==/base.apk\n"
    )

    assert "is installed" in BaseAndroidInitializer()._validate_application(controller, "com.killt.openbank")
