"""OpenSheet (Web): with several daily-shift*.json downloads, the newest one is graded, not the first by name."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from evaluators.cua_review.core.evaluation import EvalStatus
from evaluators.cua_review.evaluators.linux.opensheet import (
    OpenSheetPlantBudgetInventoryEvaluator,
    _newest_first,
)

TASK = Path(__file__).resolve().parents[1] / "tasks/v1/web/opensheet_daily_shift_photo2.yaml"


def _params() -> dict:
    return yaml.safe_load(TASK.read_text(encoding="utf-8"))["evaluation"]["params"]


def _cells(expected: dict) -> dict:
    return {address: ({"formula": value, "value": ""} if str(value).startswith("=") else {"value": str(value)})
            for address, value in expected.items()}


def _workbook(params: dict) -> dict:
    primary = {"name": "Sheet1", "cells": _cells(params["expected_primary_cells"]),
               "view": dict(params["expected_primary_view"]), "filters": {}}
    for spec in params["expected_primary_styles"]:
        for address in spec["addresses"]:
            primary["cells"][address]["style"] = dict(spec["style"])
    second = {"name": "Sheet2", "cells": _cells(params["expected_second_sheet_cells"])}
    return {"id": "book-1", "title": params["expected_workbook_title"], "sheets": [primary, second]}


class _Guest:
    """Answers the workbook read with the stored workbooks and the export scan with ``exports``."""

    def __init__(self, workbooks, exports):
        self.workbooks, self.exports = workbooks, exports

    def run_python_script(self, code, timeout=60):
        if "read_state(" in code:
            return {"stdout": json.dumps(self.workbooks)}
        return {"stdout": json.dumps(self.exports)}


def _evaluate(exports):
    params = _params()
    book = _workbook(params)
    return OpenSheetPlantBudgetInventoryEvaluator().evaluate(
        {"controller": _Guest([book], exports(book)), "params": params})


def test_newest_export_is_graded_even_when_it_sorts_after_an_older_one():
    def exports(book):
        stale = copy.deepcopy(book)
        stale["sheets"] = stale["sheets"][:1]  # an earlier export, before the inventory sheet existed
        return [
            {"path": "/home/user/Downloads/daily-shift (1).json", "mtime": 1000.0, "document": stale},
            {"path": "/home/user/Downloads/daily-shift.json", "mtime": 900.0, "document": stale},
            {"path": "/home/user/Downloads/daily-shift (2).json", "mtime": 1100.0, "document": book},
        ]

    result = _evaluate(exports)
    assert result.status == EvalStatus.PASS, result.message
    assert result.metadata["export_graded"] == "/home/user/Downloads/daily-shift (2).json"


def test_an_older_good_export_does_not_rescue_a_newer_incomplete_one():
    def exports(book):
        stale = copy.deepcopy(book)
        stale["sheets"] = stale["sheets"][:1]
        return [
            {"path": "/home/user/Downloads/daily-shift (1).json", "mtime": 1000.0, "document": book},
            {"path": "/home/user/Downloads/daily-shift (2).json", "mtime": 1200.0, "document": stale},
        ]

    result = _evaluate(exports)
    assert result.status == EvalStatus.FAIL
    assert result.metadata["export_graded"] == "/home/user/Downloads/daily-shift (2).json"
    assert "export.sheet_count" in result.message


def test_chrome_copy_number_breaks_mtime_ties_and_paths_are_deduplicated():
    rows = [
        {"path": "/d/daily-shift (2).json", "mtime": 5.0},
        {"path": "/d/daily-shift.json", "mtime": 5.0},
        {"path": "/d/daily-shift (10).json", "mtime": 5.0},
        {"path": "/d/daily-shift.json", "mtime": 5.0},
    ]
    assert [row["path"] for row in _newest_first(rows)] == [
        "/d/daily-shift (10).json", "/d/daily-shift (2).json", "/d/daily-shift.json"]
    # rows from an older guest script carry no mtime: the copy number still orders them
    assert _newest_first([{"path": "/d/a (1).json"}, {"path": "/d/a.json"}])[0]["path"] == "/d/a (1).json"


def test_guest_export_scan_reports_modification_times(tmp_path):
    class LocalGuest:
        def run_python_script(self, code, timeout=60):
            done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=timeout)
            return {"stdout": done.stdout}

    older, newer = tmp_path / "daily-shift.json", tmp_path / "daily-shift (1).json"
    older.write_text(json.dumps({"title": "old"}), encoding="utf-8")
    newer.write_text(json.dumps({"title": "new"}), encoding="utf-8")
    os.utime(older, (2000, 2000))
    os.utime(newer, (1000, 1000))  # the plain name was written last here
    found = OpenSheetPlantBudgetInventoryEvaluator._collect_exports(LocalGuest(), [str(tmp_path / "daily-shift*.json")])
    assert {row["path"]: row["mtime"] for row in found} == {str(older): 2000, str(newer): 1000}
    assert _newest_first(found)[0]["document"] == {"title": "old"}
