from __future__ import annotations

from types import SimpleNamespace

from core.evaluation import EvalStatus
from core.init import InitStatus
from evaluators.android.cua_review_state import ForegroundTextEvaluator
from initializers.android.cua_review import SnapshotOpenAppInitializer
from platforms.android.opentrip_support import (
    DEFAULT_APP_PACKAGE,
    LOCAL_STATE_KEY,
    OpenTripAndroidStore,
)
from platforms.android.openshop_support import OpenShopAndroidStore


class FakeAndroidController:
    def __init__(self, package: str = "com.killt.opendriver") -> None:
        self.package = package
        self.calls: list[list[str]] = []

    def execute_adb(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[:3] == ["shell", "pm", "path"]:
            return f"package:/data/app/{args[3]}/base.apk"
        if args[:3] == ["shell", "dumpsys", "activity"]:
            return f"topResumedActivity={self.package}/.MainActivity"
        if args[:3] == ["shell", "dumpsys", "window"]:
            return f"mCurrentFocus={self.package}/.MainActivity"
        return ""


def test_snapshot_open_app_initializer_preserves_app_data() -> None:
    controller = FakeAndroidController()
    result = SnapshotOpenAppInitializer().initialize(
        {
            "controller": controller,
            "params": {
                "app_package": controller.package,
                "app_activity": "launcher",
                "clear_app_data": False,
                "wait_ms": 0,
                "snapshot_name": "review-snapshot",
            },
        }
    )

    assert result.status is InitStatus.PASS
    assert result.metadata["snapshot_name"] == "review-snapshot"
    assert ["shell", "pm", "clear", controller.package] not in controller.calls
    assert any(call[:3] == ["shell", "monkey", "-p"] for call in controller.calls)


def test_foreground_text_evaluator_accepts_required_visible_state() -> None:
    controller = FakeAndroidController()
    observation = SimpleNamespace(
        ui_nodes=[
            {"text": "Support"},
            {"text": "rider issue - open"},
            {"content_description": "Reply to ticket"},
        ]
    )
    result = ForegroundTextEvaluator().evaluate(
        {
            "controller": controller,
            "final_observation": observation,
            "params": {
                "app_package": controller.package,
                "required_text_tokens": ["Support", "rider issue", "Reply to ticket"],
                "forbidden_text_tokens": ["Password"],
            },
        }
    )

    assert result.status is EvalStatus.PASS
    assert result.metadata["missing_required"] == []
    assert result.metadata["forbidden_matches"] == []


def test_foreground_text_evaluator_requires_one_alternative() -> None:
    controller = FakeAndroidController()
    observation = SimpleNamespace(ui_nodes=[{"text": "Rider access"}])
    result = ForegroundTextEvaluator().evaluate(
        {
            "controller": controller,
            "final_observation": observation,
            "params": {
                "app_package": controller.package,
                "required_any_text_tokens": ["Login", "Sign in"],
            },
        }
    )

    assert result.status is EvalStatus.FAIL
    assert result.metadata["matched_required_any"] == []


def test_opentrip_store_reuses_webview_storage_reader() -> None:
    store = OpenTripAndroidStore(object())

    assert isinstance(store, OpenShopAndroidStore)
    assert store.app_package == DEFAULT_APP_PACKAGE
    assert store.local_state_key == LOCAL_STATE_KEY
