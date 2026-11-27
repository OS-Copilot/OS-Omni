from unittest.mock import patch

from evaluators.cua_review.core.initialization import BaseInitializer
from evaluators.cua_review.core.evaluation import EvalResult, EvalStatus
from evaluators.cua_review.initializers.ios.opennote_open_app import (
    OpenNoteOpenAppInitializer,
)


def test_already_running_app_is_still_brought_to_foreground():
    initializer = BaseInitializer()

    with (
        patch(
            "evaluators.cua_review.core.initialization.running_app_pid",
            return_value=123,
        ),
        patch("evaluators.cua_review.core.initialization.launch_app") as launch,
        patch(
            "evaluators.cua_review.core.initialization.wait_until_running",
            return_value=123,
        ),
    ):
        detail = initializer._launch("simulator-udid", "com.example.target")

    launch.assert_called_once_with("simulator-udid", "com.example.target")
    assert detail == "com.example.target brought to the foreground (pid 123)"


def test_opennote_restarts_stale_editor_without_resetting_durable_state():
    initializer = OpenNoteOpenAppInitializer()

    with (
        patch(
            "evaluators.cua_review.initializers.ios.opennote_open_app.running_app_pid",
            return_value=123,
        ),
        patch(
            "evaluators.cua_review.initializers.ios.opennote_open_app.terminate_app"
        ) as terminate,
        patch(
            "evaluators.cua_review.initializers.ios.opennote_open_app.launch_app"
        ) as launch,
        patch(
            "evaluators.cua_review.initializers.ios.opennote_open_app.wait_until_running",
            return_value=456,
        ),
    ):
        detail = initializer._launch("simulator-udid", "com.killt.opennote")

    terminate.assert_called_once_with("simulator-udid", "com.killt.opennote")
    launch.assert_called_once_with("simulator-udid", "com.killt.opennote")
    assert detail.endswith("task entry surface (pid 456)")


def test_opennote_initializer_records_a_read_only_event_baseline():
    initializer = OpenNoteOpenAppInitializer()
    ready = EvalResult(status=EvalStatus.PASS, message="ready", metadata={})
    state = {
        "evaluationEvents": [
            {"seq": 2, "type": "seed"},
            {"seq": 9, "type": "profile_updated"},
            {"seq": True, "type": "invalid"},
        ]
    }
    with (
        patch.object(BaseInitializer, "initialize", return_value=ready),
        patch(
            "evaluators.cua_review.initializers.ios.opennote_open_app.OpenNoteStore.from_simulator"
        ) as from_simulator,
    ):
        from_simulator.return_value.read_state.return_value = state
        result = initializer.initialize({"params": {"udid": "simulator-udid"}})

    assert result.status == EvalStatus.PASS
    assert result.metadata["baseline_max_event_seq"] == 9
    assert result.metadata["source_state_mode"] == "runtime_event_baseline"
