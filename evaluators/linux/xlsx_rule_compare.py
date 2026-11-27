"""XLSX rule-based evaluator for OSWorld-style Calc tasks (zoom, freeze, etc.)."""

from __future__ import annotations

import functools
import json
import logging
from numbers import Number
from typing import Any, Callable, Mapping, Union, cast, Tuple, List

from openpyxl import Workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux.office_path_resolve import resolve_office_file_pair, unlink_if_temp

logger = logging.getLogger(__name__)

BOOK = Union[any, Workbook, str]


def _match_value_to_rule(value: Any, rule: dict) -> bool:
    """Match a value against a rule with method and ref."""
    method = rule.get("method", "eq")
    ref = rule.get("ref")
    if method == "eq":
        return value == ref
    elif method == "lt":
        return value < ref
    elif method == "gt":
        return value > ref
    elif method == "le":
        return value <= ref
    elif method == "ge":
        return value >= ref
    elif method == "ne":
        return value != ref
    return False


def _match_dimension_to_rule(value: Any, rule: dict) -> bool:
    """Match a row height / column width, allowing the rule's optional absolute ``tolerance``.

    LibreOffice keeps row heights and column widths in its own units and the GUI rounds the
    entered value to the dialog's precision (e.g. "24pt" is stored as 0.84 cm and saved as
    ht="23.8"), so a saved xlsx rarely holds the exact figure the brief names. ``tolerance``
    only widens ``eq``/``ne``; without it the comparison is the plain rule match.
    """
    tolerance = rule.get("tolerance")
    method = rule.get("method", "eq")
    if tolerance is None or method not in ("eq", "ne"):
        return _match_value_to_rule(value, rule)
    try:
        close = value is not None and abs(float(value) - float(rule.get("ref"))) <= float(tolerance)
    except (TypeError, ValueError):
        close = False
    return close if method == "eq" else not close


def _merge_anchor(ws: Worksheet, coordinate: str) -> Any:
    """Return the cell whose format a coordinate shows: itself, or its merge range's top-left cell.

    A cell covered by a merged range (B1 in A1:B1) has no format of its own once saved; the
    merged cell is displayed with the anchor's font, fill and alignment.
    """
    cell = ws[coordinate]
    if isinstance(cell, MergedCell):
        for merged in ws.merged_cells.ranges:
            if cell.coordinate in merged:
                return ws.cell(merged.min_row, merged.min_col)
    return cell


def _freeze_compare_key(sheet: Worksheet) -> Tuple[Any, ...]:
    """Build a scroll-stable key for comparing freeze panes."""
    pane = sheet.sheet_view.pane
    if pane is None:
        return ("none",)
    state = (pane.state or "").lower()
    xs = int(pane.xSplit) if pane.xSplit is not None else 0
    ys = int(pane.ySplit) if pane.ySplit is not None else 0
    if state in ("frozen", "frozensplit"):
        return ("frozen", xs, ys)
    return ("other", xs, ys, pane.topLeftCell)


def _parse_sheet_idx(
    sheet_idx: Union[int, str],
    result: BOOK,
    expected: BOOK,
    result_sheet_names: List[str],
    expected_sheet_names: List[str],
) -> Tuple[BOOK, str]:
    if isinstance(sheet_idx, int):
        index = result_sheet_names[sheet_idx] if result_sheet_names and sheet_idx < len(result_sheet_names) else ""
        book = result
    elif sheet_idx.startswith("RI"):
        try:
            index = result_sheet_names[int(sheet_idx[2:])]
        except:
            index = ""
        book = result
    elif sheet_idx.startswith("RN"):
        index = sheet_idx[2:]
        book = result
    elif sheet_idx.startswith("EI"):
        try:
            index = expected_sheet_names[int(sheet_idx[2:])]
        except:
            index = ""
        book = expected
    elif sheet_idx.startswith("EN"):
        index = sheet_idx[2:]
        book = expected
    else:
        logger.error("Unrecognized sheet index")
        raise ValueError(f"Unrecognized sheet index: {sheet_idx}")
    return book, index


def _load_sheet(book: BOOK, index: str) -> Worksheet:
    if isinstance(book, Workbook):
        return book[index]
    return None


def compare_xlsx_rules(
    file1_path: str,
    file2_path: str,
    **options: Any,
) -> int:
    """Compare xlsx files using OSWorld-style rules.

    Supports: zoom, freeze, sheet_data, pivot_table, check_cell
    Returns 1 if all rules pass, 0 otherwise.
    """
    rules = options.get("rules", [])

    xlworkbook1 = Workbook()
    xlworkbook2 = Workbook()
    sheet1_names = []
    sheet2_names = []

    try:
        xlworkbook1 = Workbook()
        xlworkbook2 = Workbook()
        from openpyxl import load_workbook
        xlworkbook1 = load_workbook(file1_path)
        xlworkbook2 = load_workbook(file2_path)
        sheet1_names = xlworkbook1.sheetnames
        sheet2_names = xlworkbook2.sheetnames
    except Exception as e:
        logger.error(f"Failed to load xlsx files: {e}")
        return 0

    parse_idx: Callable = functools.partial(
        _parse_sheet_idx,
        result_sheet_names=sheet1_names,
        expected_sheet_names=sheet2_names,
    )

    passes = True

    for r in rules:
        if r["type"] == "zoom":
            # Check Zooming
            # sheet_idx: 0 | "RI0" | "RNSheet1" | "EI0" | "ENSheet1"
            # method: lt | gt | eq | le | ge | ne
            # ref: reference value
            sheet: Worksheet = _load_sheet(*parse_idx(r["sheet_idx"], xlworkbook1, xlworkbook2))
            if sheet is None:
                passes = False
                break
            zoom_scale = sheet.sheet_view.zoomScale or 100.0
            metric = _match_value_to_rule(zoom_scale, r)
            logger.debug(
                "Assertion: zoom(%.1f) %s %.1f - %s",
                zoom_scale, r.get("method"), r.get("ref"), metric
            )
            passes = passes and metric

        elif r["type"] == "freeze":
            # Compare Freezing
            # sheet_idx0: result sheet index
            # sheet_idx1: expected sheet index
            sheet1 = _load_sheet(*parse_idx(r["sheet_idx0"], xlworkbook1, xlworkbook2))
            sheet2 = _load_sheet(*parse_idx(r["sheet_idx1"], xlworkbook1, xlworkbook2))
            if sheet1 is None or sheet2 is None:
                passes = False
                break
            key1 = _freeze_compare_key(sheet1)
            key2 = _freeze_compare_key(sheet2)
            metric = key1 == key2
            logger.debug(
                "Assertion: freeze_key%s == freeze_key%s - %s", key1, key2, metric
            )
            passes = passes and metric

        elif r["type"] == "sheet_name":
            # Check the visible sheet name.
            # sheet_idx: 0 | "RI0" | "RNSheet1"
            # method/ref: same matcher semantics as check_cell.
            sheet = _load_sheet(*parse_idx(r.get("sheet_idx", 0), xlworkbook1, xlworkbook2))
            if sheet is None:
                passes = False
                break
            metric = _match_value_to_rule(sheet.title, r)
            logger.debug(
                "Assertion: sheet_name(%s) %s %s - %s",
                sheet.title,
                r.get("method", "eq"),
                r.get("ref"),
                metric,
            )
            passes = passes and metric

        elif r["type"] == "row_height":
            sheet = _load_sheet(*parse_idx(r.get("sheet_idx", 0), xlworkbook1, xlworkbook2))
            if sheet is None:
                passes = False
                break
            row_idx = int(r.get("row", 1) or 1)
            height = sheet.row_dimensions[row_idx].height
            metric = _match_dimension_to_rule(height, r)
            logger.debug(
                "Assertion: row_height(%s)=%.3f %s %s - %s",
                row_idx,
                float(height or 0),
                r.get("method", "eq"),
                r.get("ref"),
                metric,
            )
            passes = passes and metric

        elif r["type"] == "column_width":
            sheet = _load_sheet(*parse_idx(r.get("sheet_idx", 0), xlworkbook1, xlworkbook2))
            if sheet is None:
                passes = False
                break
            column = str(r.get("column") or "A").strip().upper()
            width = sheet.column_dimensions[column].width
            metric = _match_dimension_to_rule(width, r)
            logger.debug(
                "Assertion: column_width(%s)=%.3f %s %s - %s",
                column,
                float(width or 0),
                r.get("method", "eq"),
                r.get("ref"),
                metric,
            )
            passes = passes and metric

        elif r["type"] == "sheet_data":
            # Compare sheet data
            from openpyxl import load_workbook
            sheet1_wb = load_workbook(file1_path, data_only=True)
            sheet2_wb = load_workbook(file2_path, data_only=True)

            idx1 = r.get("sheet_idx0", 0)
            idx2 = r.get("sheet_idx1", 0)

            def resolve_sheet(wb, idx):
                if isinstance(idx, int):
                    return wb.worksheets[idx]
                elif idx.startswith("RN"):
                    return wb[idx[2:]]
                elif idx.startswith("EN"):
                    return wb[idx[2:]]
                elif idx.startswith("RI"):
                    return wb.worksheets[int(idx[2:])]
                elif idx.startswith("EI"):
                    return wb.worksheets[int(idx[2:])]
                return wb.worksheets[0]

            ws1 = resolve_sheet(sheet1_wb, idx1)
            ws2 = resolve_sheet(sheet2_wb, idx2)

            precision = r.get("precision", 4)
            max_row = max(ws1.max_row or 1, ws2.max_row or 1)
            max_col = max(ws1.max_column or 1, ws2.max_column or 1)

            def norm_value(v):
                if v is None:
                    return None
                import datetime as _datetime
                from openpyxl.utils.datetime import to_excel
                if isinstance(v, (_datetime.datetime, _datetime.date, _datetime.time)):
                    return round(to_excel(v), precision)
                if isinstance(v, float):
                    return round(v, precision) if abs(v) >= 1e-15 else 0.0
                if isinstance(v, int) and not isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    s = v.strip()
                    return s if s else None
                return v

            def close_float(a, b, tol):
                return abs(a - b) <= tol * max(1.0, abs(a), abs(b))

            metric = True
            for row in range(1, max_row + 1):
                for col in range(1, max_col + 1):
                    v1 = norm_value(ws1.cell(row, col).value)
                    v2 = norm_value(ws2.cell(row, col).value)
                    if v1 == v2:
                        continue
                    if isinstance(v1, float) and isinstance(v2, float):
                        if close_float(v1, v2, 10 ** -precision):
                            continue
                    metric = False
                    break
                if not metric:
                    break

            passes = passes and metric

        elif r["type"] == "pivot_table":
            # Check pivot table existence and structure
            from openpyxl import load_workbook
            sheet1_wb = load_workbook(file1_path)
            sheet2_wb = load_workbook(file2_path)

            idx1 = r.get("sheet_idx0", 0)
            idx2 = r.get("sheet_idx1", 0)

            def resolve_sheet(wb, idx):
                if isinstance(idx, int):
                    return wb.worksheets[idx]
                elif idx.startswith("RN"):
                    return wb[idx[2:]]
                elif idx.startswith("EN"):
                    return wb[idx[2:]]
                return wb.worksheets[0]

            ws1 = resolve_sheet(sheet1_wb, idx1)
            ws2 = resolve_sheet(sheet2_wb, idx2)

            pivot1 = ws1._pivots if hasattr(ws1, '_pivots') else []
            pivot2 = ws2._pivots if hasattr(ws2, '_pivots') else []

            # Basic check: both should have at least some pivot tables
            metric = len(pivot1) > 0 or len(pivot2) > 0
            passes = passes and metric

        elif r["type"] == "check_cell":
            # Check cell properties (value, bgcolor, font_color, font_bold, etc.)
            from openpyxl import load_workbook
            sheet1_wb = load_workbook(file1_path)

            idx = r.get("sheet_idx", 0)
            coordinate = r.get("coordinate", "A1")

            def resolve_sheet(wb, idx):
                if isinstance(idx, int):
                    return wb.worksheets[idx]
                elif idx.startswith("RN"):
                    return wb[idx[2:]]
                return wb.worksheets[0]

            ws = resolve_sheet(sheet1_wb, idx)
            # A coordinate covered by a merged range is shown with the anchor cell's format.
            cell = _merge_anchor(ws, coordinate)

            metric = True
            props = r.get("props", {})

            if "value" in props:
                rule = props["value"]
                val = cell.value
                metric = metric and _match_value_to_rule(val, rule)

            if "formula" in props:
                rule = props["formula"]
                val = cell.value if isinstance(cell.value, str) and cell.value.startswith("=") else None
                metric = metric and _match_value_to_rule(val, rule)

            if "number_format" in props:
                rule = props["number_format"]
                metric = metric and _match_value_to_rule(cell.number_format, rule)

            if "alignment_horizontal" in props:
                rule = props["alignment_horizontal"]
                metric = metric and _match_value_to_rule(cell.alignment.horizontal, rule)

            if "alignment_vertical" in props:
                rule = props["alignment_vertical"]
                metric = metric and _match_value_to_rule(cell.alignment.vertical, rule)

            if "bgcolor" in props:
                rule = props["bgcolor"]
                val = cell.fill.start_color.rgb if cell.fill and cell.fill.start_color else None
                if val and isinstance(val, str) and len(val) == 8:
                    val = val[2:]  # Remove alpha channel
                metric = metric and _match_value_to_rule(val, rule)

            if "font_color" in props:
                rule = props["font_color"]
                val = cell.font.color.rgb if cell.font and cell.font.color else None
                if val and isinstance(val, str) and len(val) == 8:
                    val = val[2:]
                metric = metric and _match_value_to_rule(val, rule)

            if "font_bold" in props:
                rule = props["font_bold"]
                val = cell.font.bold if cell.font else None
                metric = metric and _match_value_to_rule(val, rule)

            passes = passes and metric

        else:
            logger.warning(f"Unknown rule type: {r['type']}")
            passes = False

        if not passes:
            break

    return 1 if passes else 0


class XlsxRuleEvaluator(BaseEvaluator):
    """Evaluate xlsx files using OSWorld-style rules (zoom, freeze, sheet_data, etc.)."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        actual = str(params.get("actual_path") or "").strip()
        expected = str(params.get("expected_path") or "").strip()
        text_artifacts = params.get("text_artifacts") or []
        if text_artifacts and not isinstance(text_artifacts, list):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.text_artifacts must be a list")

        if not actual:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.actual_path is required",
            )

        # expected may be optional for some rules
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
                message=f"failed to resolve XLSX paths: {exc}",
            )

        meta = {
            "actual_path": str(actual_path),
            "expected_path": str(expected_path) if expected_path else None,
            "actual_temp": actual_tmp,
            "expected_temp": expected_tmp,
        }

        try:
            score = compare_xlsx_rules(
                str(actual_path),
                str(expected_path) if expected_path else "",
                **params,
            )
            if float(score) < 1.0:
                failed_rules = []
                for index, rule in enumerate(params.get("rules") or [], start=1):
                    try:
                        single_score = compare_xlsx_rules(
                            str(actual_path),
                            str(expected_path) if expected_path else "",
                            **{**params, "rules": [rule]},
                        )
                    except Exception as exc:
                        failed_rules.append({"index": index, "rule": rule, "error": repr(exc)})
                        continue
                    if float(single_score) < 1.0:
                        entry = {"index": index, "rule": rule}
                        if dict(rule).get("type") == "sheet_data":
                            entry["diagnostic"] = self._diagnose_sheet_data(
                                str(actual_path),
                                str(expected_path) if expected_path else "",
                                dict(rule),
                            )
                        failed_rules.append(entry)
                meta["failed_rules"] = failed_rules
        except Exception as exc:
            meta["error"] = repr(exc)
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"XLSX rule comparison raised: {exc}",
                metadata=meta,
            )
        finally:
            unlink_if_temp(actual_path, actual_tmp)
            unlink_if_temp(expected_path, expected_tmp)

        meta["score"] = float(score)
        if float(score) < 1.0:
            return EvalResult(status=EvalStatus.FAIL, message="XLSX rule check failed", metadata=meta)

        if text_artifacts:
            if controller is None or not hasattr(controller, "run_bash_script"):
                return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required for text_artifacts")
            try:
                artifact_meta = self._validate_text_artifacts(controller, text_artifacts)
            except AssertionError as exc:
                meta["text_artifacts"] = getattr(exc, "metadata", None)
                return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=meta)
            except Exception as exc:
                return EvalResult(status=EvalStatus.ERROR, message=f"text artifact validation failed: {exc}", metadata=meta)
            meta["text_artifacts"] = artifact_meta

        return EvalResult(status=EvalStatus.PASS, message="XLSX rule check passed", metadata=meta)

    @staticmethod
    def _diagnose_sheet_data(actual_path: str, expected_path: str, rule: dict[str, Any]) -> dict[str, Any]:
        from openpyxl import load_workbook

        def resolve_sheet(wb: Any, idx: Any) -> Any:
            if isinstance(idx, int):
                return wb.worksheets[idx]
            if isinstance(idx, str):
                if idx.startswith(("RN", "EN")):
                    return wb[idx[2:]]
                if idx.startswith(("RI", "EI")):
                    return wb.worksheets[int(idx[2:])]
            return wb.worksheets[0]

        def norm_value(value: Any) -> Any:
            precision = int(rule.get("precision", 4) or 4)
            if value is None:
                return None
            import datetime as _datetime
            from openpyxl.utils.datetime import to_excel
            if isinstance(value, (_datetime.datetime, _datetime.date, _datetime.time)):
                return round(to_excel(value), precision)
            if isinstance(value, float):
                return round(value, precision) if abs(value) >= 1e-15 else 0.0
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            if isinstance(value, str):
                stripped = value.strip()
                return stripped if stripped else None
            return value

        actual_wb = load_workbook(actual_path, data_only=True)
        expected_wb = load_workbook(expected_path, data_only=True)
        actual_ws = resolve_sheet(actual_wb, rule.get("sheet_idx0", 0))
        expected_ws = resolve_sheet(expected_wb, rule.get("sheet_idx1", 0))
        max_row = max(actual_ws.max_row or 1, expected_ws.max_row or 1)
        max_col = max(actual_ws.max_column or 1, expected_ws.max_column or 1)
        for row in range(1, max_row + 1):
            for col in range(1, max_col + 1):
                actual_cell = actual_ws.cell(row, col)
                expected_cell = expected_ws.cell(row, col)
                actual_value = norm_value(actual_cell.value)
                expected_value = norm_value(expected_cell.value)
                if actual_value == expected_value:
                    continue
                return {
                    "coordinate": actual_cell.coordinate,
                    "actual": repr(actual_cell.value),
                    "actual_type": type(actual_cell.value).__name__,
                    "expected": repr(expected_cell.value),
                    "expected_type": type(expected_cell.value).__name__,
                    "actual_normalized": repr(actual_value),
                    "expected_normalized": repr(expected_value),
                    "actual_dimensions": [actual_ws.max_row, actual_ws.max_column],
                    "expected_dimensions": [expected_ws.max_row, expected_ws.max_column],
                }
        return {
            "actual_dimensions": [actual_ws.max_row, actual_ws.max_column],
            "expected_dimensions": [expected_ws.max_row, expected_ws.max_column],
            "mismatch": None,
        }

    @staticmethod
    def _validate_text_artifacts(controller: Any, artifacts: list[Any]) -> dict[str, Any]:
        script = f"""python3 - <<'PY'
import json
from pathlib import Path

artifacts = json.loads({json.dumps(json.dumps(artifacts, ensure_ascii=False), ensure_ascii=False)})
results = []
for item in artifacts:
    path = Path(str(item.get("path") or ""))
    entry = {{"path": str(path), "exists": path.exists()}}
    if path.exists():
        entry["content"] = path.read_text(encoding="utf-8")
    results.append(entry)
print(json.dumps({{"results": results}}, ensure_ascii=False))
PY"""
        result = controller.run_bash_script(script, timeout=30)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        payload = json.loads(output)
        by_path = {str(item.get("path") or ""): dict(item) for item in payload.get("results") or []}
        for item in artifacts:
            if not isinstance(item, Mapping):
                continue
            path = str(item.get("path") or "")
            actual = by_path.get(path)
            assert actual is not None, f"missing text artifact payload for {path}"
            assert bool(actual.get("exists")), f"expected text artifact to exist: {path}"
            content = str(actual.get("content") or "")
            if "equals" in item:
                expected = str(item.get("equals") or "")
                assert content == expected, f"text artifact mismatch for {path}"
            if "contains" in item:
                needle = str(item.get("contains") or "")
                assert needle in content, f"expected text artifact {path} to contain {needle!r}"
        return payload
