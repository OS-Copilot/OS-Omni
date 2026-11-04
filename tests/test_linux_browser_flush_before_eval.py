import logging

from platforms.linux.runners import evaluation
from platforms.linux.runners.evaluation import flush_browser_storage


class _Controller:
    def __init__(self):
        self.scripts = []

    def run_bash_script(self, script, timeout=30):
        self.scripts.append(script)
        return {"output": "closed", "returncode": 0}


class _DiskEvaluator:
    pass


class _LiveEvaluator:
    REQUIRES_LIVE_BROWSER = True


def test_flush_runs_for_evaluators_that_read_disk(monkeypatch):
    monkeypatch.delenv("OS_OMNI_FLUSH_BROWSER_BEFORE_EVAL", raising=False)
    controller = _Controller()
    flush_browser_storage(controller, _DiskEvaluator(), logging.getLogger("t"))

    assert len(controller.scripts) == 1
    script = controller.scripts[0]
    # renderers first (commits each origin's storage), then a graceful browser close
    assert script.index("--type=renderer") < script.index("kill -TERM $browsers")


def test_live_browser_evaluator_keeps_browser(monkeypatch):
    monkeypatch.delenv("OS_OMNI_FLUSH_BROWSER_BEFORE_EVAL", raising=False)
    controller = _Controller()
    flush_browser_storage(controller, _LiveEvaluator(), logging.getLogger("t"))

    assert controller.scripts == []


def test_env_can_disable_flush(monkeypatch):
    monkeypatch.setenv("OS_OMNI_FLUSH_BROWSER_BEFORE_EVAL", "0")
    controller = _Controller()
    flush_browser_storage(controller, _DiskEvaluator(), logging.getLogger("t"))

    assert controller.scripts == []


def test_flush_failure_does_not_raise(monkeypatch):
    monkeypatch.delenv("OS_OMNI_FLUSH_BROWSER_BEFORE_EVAL", raising=False)

    class Broken:
        def run_bash_script(self, script, timeout=30):
            raise RuntimeError("guest down")

    flush_browser_storage(Broken(), _DiskEvaluator(), logging.getLogger("t"))


def test_devtools_evaluators_are_marked_live():
    from core.evaluation import load_evaluator

    for evaluator_id in (
        "evaluators.cua_review.evaluators.linux.opennavigation_sessions:OpenNavigationSessionEvaluator",
        "evaluators.linux.opentrip_sk2_qingdao_dual_booking_audit:OpenTripDualBookingEvaluator",
        "evaluators.linux.openphotoedit_window_portrait_dual_export_043767:OpenPhotoEditWindowPortraitDualExport059248Evaluator",
    ):
        assert getattr(load_evaluator(evaluator_id), "REQUIRES_LIVE_BROWSER", False) is True
    assert evaluation._BROWSER_FLUSH_SCRIPT.strip().startswith("browsers=")
