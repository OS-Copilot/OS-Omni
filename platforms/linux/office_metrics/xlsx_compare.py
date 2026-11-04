"""XLSX sheet value comparison for OSWorld-style Calc tasks."""

from __future__ import annotations

import logging
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries

logger = logging.getLogger(__name__)


def pivot_data_caption_cells(ws: Any) -> dict[tuple[int, int], str]:
    """Return ``{(row, col): caption}`` for the data-field caption cells of ``ws``'s pivot tables.

    A pivot data field's caption ("Count - Sex", "Sum of Amount") is the label LibreOffice/Excel
    write above the data column; it names the source field and aggregate the author picked, not a
    value the table shows. A cell counts as a caption when it lies in the header rows of a pivot
    table's ``location`` (above ``firstDataRow``), over its data columns (from ``firstDataCol``),
    and holds one of that pivot's data-field names (LibreOffice stores them with a trailing ``*``),
    or, for a pivot with one data field and no column fields, sits where that caption goes.
    """
    cells: dict[tuple[int, int], str] = {}
    for pivot in getattr(ws, "_pivots", None) or []:
        location = getattr(pivot, "location", None)
        ref = getattr(location, "ref", None)
        if not ref:
            continue
        try:
            min_col, min_row, max_col, max_row = range_boundaries(str(ref))
        except (TypeError, ValueError):
            continue
        data_fields = list(getattr(pivot, "dataFields", None) or [])
        names = {str(field.name).rstrip("*").strip() for field in data_fields if getattr(field, "name", None)}
        names.discard("")
        first_data_row = int(getattr(location, "firstDataRow", 0) or 0)
        first_data_col = int(getattr(location, "firstDataCol", 0) or 0)
        header_last_row = min(max_row, min_row + max(first_data_row, 1) - 1)
        data_first_col = min_col + first_data_col
        for r in range(min_row, header_last_row + 1):
            for c in range(data_first_col, max_col + 1):
                value = ws.cell(r, c).value
                if isinstance(value, str) and value.strip() in names:
                    cells[(r, c)] = value.strip()
        column_fields = [item for item in (getattr(pivot, "colFields", None) or []) if getattr(item, "x", None) != -2]
        if len(data_fields) == 1 and not column_fields and data_first_col <= max_col:
            value = ws.cell(min_row, data_first_col).value
            if isinstance(value, str) and value.strip():
                cells.setdefault((min_row, data_first_col), value.strip())
    return cells


def _norm_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float):
        if abs(v) < 1e-15:
            return 0.0
        return float(v)
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return v


def _close_float(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def compare_xlsx_sheet(
    file1_path: str,
    file2_path: str,
    *,
    sheet: int | str = 0,
    numeric_tolerance: float = 1e-4,
    ignore_pivot_data_captions: bool = False,
) -> tuple[int, dict[str, Any] | None]:
    """Compare one sheet's cell values between two workbooks.

    With ``ignore_pivot_data_captions`` a cell that is a pivot data-field caption in *both*
    workbooks (see :func:`pivot_data_caption_cells`) is not compared by text: the caption names the
    field the author counted, which a brief asking only for the table's figures does not fix. Every
    other cell, including the pivots' row labels and values, is still compared, and a caption cell
    the actual sheet does not hold as a pivot caption (e.g. a static table) is compared as usual.

    Returns ``(1, None)`` on match, or ``(0, detail)`` with the first mismatch (or sheet error).
    """
    wb1 = load_workbook(file1_path, data_only=True)
    wb2 = load_workbook(file2_path, data_only=True)

    if isinstance(sheet, int):
        ws1 = wb1.worksheets[sheet]
        ws2 = wb2.worksheets[sheet]
    else:
        if sheet not in wb1.sheetnames or sheet not in wb2.sheetnames:
            logger.debug("xlsx: sheet %r missing in one workbook", sheet)
            return 0, {"reason": "sheet_missing", "sheet": sheet}
        ws1 = wb1[sheet]
        ws2 = wb2[sheet]

    max_row = max(ws1.max_row or 1, ws2.max_row or 1)
    max_col = max(ws1.max_column or 1, ws2.max_column or 1)

    caption_cells: set[tuple[int, int]] = set()
    if ignore_pivot_data_captions:
        caption_cells = set(pivot_data_caption_cells(ws1)) & set(pivot_data_caption_cells(ws2))

    for r in range(1, max_row + 1):
        for c in range(1, max_col + 1):
            v1 = ws1.cell(r, c).value
            v2 = ws2.cell(r, c).value
            n1 = _norm_value(v1)
            n2 = _norm_value(v2)
            if n1 == n2:
                continue
            if (r, c) in caption_cells:
                continue
            if isinstance(n1, float) and isinstance(n2, float):
                if _close_float(n1, n2, numeric_tolerance):
                    continue
            if isinstance(n1, (int, float)) and isinstance(n2, (int, float)):
                try:
                    f1 = float(n1)
                    f2 = float(n2)
                    if _close_float(f1, f2, numeric_tolerance):
                        continue
                except (TypeError, ValueError):
                    pass
            logger.debug("xlsx: mismatch at (%s,%s): %r vs %r", r, c, v1, v2)
            addr = f"{get_column_letter(c)}{r}"
            return 0, {
                "reason": "cell_mismatch",
                "row": r,
                "column": c,
                "address": addr,
                "raw_actual": v1,
                "raw_expected": v2,
                "norm_actual": n1,
                "norm_expected": n2,
            }
    return 1, None
