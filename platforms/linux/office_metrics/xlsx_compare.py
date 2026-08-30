"""XLSX sheet value comparison for OSWorld-style Calc tasks."""

from __future__ import annotations

import logging
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)


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
) -> tuple[int, dict[str, Any] | None]:
    """Compare one sheet's cell values between two workbooks.

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

    for r in range(1, max_row + 1):
        for c in range(1, max_col + 1):
            v1 = ws1.cell(r, c).value
            v2 = ws2.cell(r, c).value
            n1 = _norm_value(v1)
            n2 = _norm_value(v2)
            if n1 == n2:
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
