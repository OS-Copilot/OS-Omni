"""OpenPhotoEdit window_portrait (Web, WEB-076): the final on-screen UI is recorded, not graded.

The brief labels the outputs "first" and "second" and lists each one's brushes, but never says which
image to leave open or which brush to use last; its completion condition is that both files are
exported.  Requiring the detail image's Filter 51 / Burn 18-28 sliders at the end (read over DevTools,
with a DevTools failure forcing FAIL) graded an unstated order.
"""

from __future__ import annotations

import copy

from evaluators.linux import openphotoedit_window_portrait_dual_export_043767 as task

DETAIL_UI = {
    "title": "OpenPhotoEdit",
    "file": ["C:\\fakepath\\portrait_window_detail.jpg"],
    "ranges": [
        {"value": 51, "param": "filterStrength", "state": None},
        {"value": 18, "param": None, "state": "brushSize"},
        {"value": 28, "param": None, "state": "brushStrength"},
    ],
    "bodyText": "OpenPhotoEdit\n9 exposure\n-7 contrast\nlocal marks\nImported | 1536 x 1024 | Portrait",
}


def _observed(ui=None, errors=()):
    return {"sources": {}, "exports": {}, "ui": copy.deepcopy(ui) if ui is not None else {}, "errors": list(errors)}


def _graded(verdict):
    return verdict["status"], verdict["failures"], verdict["source_errors"]


def test_the_final_ui_does_not_change_the_verdict():
    reference = task.evaluate_observed(_observed(DETAIL_UI))
    # the run ended on the first image, or with the Mosaic brush (16 / 50) selected last
    before_open = dict(DETAIL_UI, file=["C:\\fakepath\\portrait_window_before.jpg"])
    mosaic_last = dict(DETAIL_UI, ranges=[{"value": 51, "param": "filterStrength", "state": None},
                                          {"value": 16, "param": None, "state": "brushSize"},
                                          {"value": 50, "param": None, "state": "brushStrength"}])
    for ui in (before_open, mosaic_last, {}):
        verdict = task.evaluate_observed(_observed(ui))
        assert _graded(verdict) == _graded(reference)
        assert "detail.final_ui" not in verdict["failures"]
        assert [row["check_id"] for row in verdict["advisory_checks"]] == ["detail.final_ui"]
        assert verdict["advisory_checks"][0]["passed"] is False
    assert reference["advisory_checks"][0]["passed"] is True
    assert all(check["check_id"] != "detail.final_ui" for check in reference["checks"])


def test_a_devtools_read_failure_is_not_a_source_error():
    verdict = task.evaluate_observed(_observed(errors=["ui: URLError: <urlopen error [Errno 111] Connection refused>"]))
    assert verdict["source_errors"] == []
    assert verdict["ui_errors"] == ["ui: URLError: <urlopen error [Errno 111] Connection refused>"]
    # an unreadable export still is
    verdict = task.evaluate_observed(_observed(DETAIL_UI, errors=["before: FileNotFoundError: x"]))
    assert verdict["source_errors"] == ["before: FileNotFoundError: x"]
    assert verdict["status"] == "FAIL"
