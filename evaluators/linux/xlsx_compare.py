"""XLSX sheet comparison evaluator for Linux office tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux.office_path_resolve import resolve_office_file_pair, unlink_if_temp
from platforms.linux.office_metrics.xlsx_compare import compare_xlsx_sheet


def _fail_message(detail: dict[str, Any] | None) -> str:
    if not detail:
        return "XLSX sheet comparison failed"
    reason = detail.get("reason")
    if reason == "cell_mismatch":
        addr = detail.get("address", "?")
        return (
            f"XLSX mismatch at {addr}: expected {detail.get('raw_expected')!r}, "
            f"got {detail.get('raw_actual')!r}"
        )
    if reason == "sheet_missing":
        return f"XLSX sheet missing: {detail.get('sheet')!r}"
    return "XLSX sheet comparison failed"


class XlsxCompareEvaluator(BaseEvaluator):
    """Compare one worksheet's cell values against a gold xlsx (OSWorld-style)."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        actual = str(params.get("actual_path") or "").strip()
        expected = str(params.get("expected_path") or "").strip()
        if not actual or not expected:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.actual_path and expected_path are required",
            )

        sheet = params.get("sheet", 0)
        if not (isinstance(sheet, int) or isinstance(sheet, str)):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.sheet must be int or str")

        try:
            numeric_tolerance = float(params.get("numeric_tolerance", 1e-4))
        except (TypeError, ValueError):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.numeric_tolerance must be a number",
            )

        try:
            actual_path, expected_path, actual_tmp, expected_tmp = resolve_office_file_pair(
                actual,
                expected,
                controller,
                actual_prefix="helloworld_xlsx_actual_",
                expected_prefix="helloworld_xlsx_expected_",
                actual_suffix=".xlsx",
                expected_suffix=".xlsx",
            )
        except FileNotFoundError as exc:
            return EvalResult(status=EvalStatus.ERROR, message=str(exc))
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"failed to resolve XLSX paths for comparison: {exc}",
            )

        # A pivot data-field caption ("Count - Civil Status") only names the field the author
        # counted; tasks whose brief asks for the pivot's figures, not its caption, opt out of
        # comparing it (values, row labels and layout are still compared).
        ignore_pivot_data_captions = bool(params.get("ignore_pivot_data_captions", False))

        meta: dict[str, Any] = {
            "actual_path": str(actual_path),
            "expected_path": str(expected_path),
            "actual_temp": actual_tmp,
            "expected_temp": expected_tmp,
            "sheet": sheet,
            "numeric_tolerance": numeric_tolerance,
            "ignore_pivot_data_captions": ignore_pivot_data_captions,
        }
        try:
            score, detail = compare_xlsx_sheet(
                str(actual_path),
                str(expected_path),
                sheet=sheet,
                numeric_tolerance=numeric_tolerance,
                ignore_pivot_data_captions=ignore_pivot_data_captions,
            )
        except Exception as exc:
            meta["error"] = repr(exc)
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"XLSX comparison raised: {exc}",
                metadata=meta,
            )
        finally:
            unlink_if_temp(actual_path, actual_tmp)
            unlink_if_temp(expected_path, expected_tmp)

        meta["score"] = float(score)
        if detail is not None:
            meta["mismatch"] = detail

        if float(score) >= 1.0:
            return EvalResult(status=EvalStatus.PASS, message="XLSX sheet comparison passed", metadata=meta)
        return EvalResult(status=EvalStatus.FAIL, message=_fail_message(detail), metadata=meta)
