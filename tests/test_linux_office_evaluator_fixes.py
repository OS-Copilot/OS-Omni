"""Linux LibreOffice evaluators grade what the briefs ask (pivot captions, merged cells, sizes, picture boxes)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from platforms.linux.office_metrics import xlsx_compare
from platforms.linux.office_metrics.xlsx_compare import compare_xlsx_sheet, pivot_data_caption_cells
from evaluators.linux.pptx_compare import PptxCompareEvaluator
from evaluators.linux.xlsx_rule_compare import compare_xlsx_rules


# --------------------------------------------------------------------------- pivot data captions


def _pivot(ref: str, *names: str, col_fields=()):
    return SimpleNamespace(
        location=SimpleNamespace(ref=ref, firstHeaderRow=1, firstDataRow=1, firstDataCol=1),
        dataFields=[SimpleNamespace(name=name) for name in names],
        colFields=[SimpleNamespace(x=x) for x in col_fields],
    )


def _pivot_sheet(caption: str, field_name: str) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet2"
    for row in (["Civil Status", caption], ["Married", 0.275], ["Single", 0.3], ["Total Result", 1]):
        ws.append(row)
    ws._pivots = [_pivot("A1:B4", field_name)]
    return wb


def test_caption_cells_come_from_the_pivot_header_over_the_data_column() -> None:
    ws = _pivot_sheet("Count - Civil Status", "Count - Civil Status*").active
    assert pivot_data_caption_cells(ws) == {(1, 2): "Count - Civil Status"}

    # The row-field label (A1) and the values are never captions.
    ws.cell(1, 1).value = "Count - Civil Status"
    assert set(pivot_data_caption_cells(ws)) == {(1, 2)}


def test_caption_cells_need_a_pivot() -> None:
    wb = Workbook()
    wb.active.append(["Civil Status", "Count - Civil Status"])
    assert pivot_data_caption_cells(wb.active) == {}


def _save(tmp_path, name: str, wb: Workbook) -> str:
    for ws in wb.worksheets:
        ws._pivots = []  # the stand-in pivots above cannot be written
    path = tmp_path / name
    wb.save(path)
    return str(path)


def _patch_captions(monkeypatch, captions_by_text) -> None:
    """Pivot parts do not survive an openpyxl save; recognise the captions by their text instead."""

    def fake(ws):
        return {
            (cell.row, cell.column): cell.value
            for row in ws.iter_rows()
            for cell in row
            if cell.value in captions_by_text
        }

    monkeypatch.setattr(xlsx_compare, "pivot_data_caption_cells", fake)


def test_pivot_caption_is_ignored_only_when_asked_and_both_sides_hold_one(tmp_path, monkeypatch) -> None:
    actual = _save(tmp_path, "actual.xlsx", _pivot_sheet("Count - Respondents", "Count - Respondents"))
    expected = _save(tmp_path, "expected.xlsx", _pivot_sheet("Count - Civil Status", "Count - Civil Status*"))
    _patch_captions(monkeypatch, {"Count - Respondents", "Count - Civil Status"})

    score, detail = compare_xlsx_sheet(actual, expected, sheet="Sheet2")
    assert score == 0 and detail["address"] == "B1"
    assert compare_xlsx_sheet(actual, expected, sheet="Sheet2", ignore_pivot_data_captions=True) == (1, None)

    # A static header that is not a pivot caption is still compared.
    _patch_captions(monkeypatch, {"Count - Civil Status"})
    score, detail = compare_xlsx_sheet(actual, expected, sheet="Sheet2", ignore_pivot_data_captions=True)
    assert score == 0 and detail["address"] == "B1"


def test_pivot_values_are_still_compared(tmp_path, monkeypatch) -> None:
    wrong = _pivot_sheet("Count - Respondents", "Count - Respondents")
    wrong.active["B2"] = 0.5
    actual = _save(tmp_path, "actual.xlsx", wrong)
    expected = _save(tmp_path, "expected.xlsx", _pivot_sheet("Count - Civil Status", "Count - Civil Status*"))
    _patch_captions(monkeypatch, {"Count - Respondents", "Count - Civil Status"})

    score, detail = compare_xlsx_sheet(actual, expected, sheet="Sheet2", ignore_pivot_data_captions=True)
    assert score == 0 and detail["address"] == "B2"


# --------------------------------------------------------------------------- xlsx rules


def _header_book(row_height: float) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Month / Item"
    ws.merge_cells("A1:B1")
    ws["C1"] = "Jan"
    for coordinate in ("A1", "C1"):
        cell = ws[coordinate]
        cell.font = Font(bold=True, color="FF9C6500")
        cell.fill = PatternFill(fill_type="solid", start_color="FFFFF2CC", end_color="FFFFF2CC")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = row_height
    ws.column_dimensions["A"].width = 17.99
    ws["A2"] = 1.5
    return wb


HEADER_PROPS = {
    "font_bold": {"method": "eq", "ref": True},
    "bgcolor": {"method": "eq", "ref": "FFF2CC"},
    "font_color": {"method": "eq", "ref": "9C6500"},
    "alignment_horizontal": {"method": "eq", "ref": "center"},
    "alignment_vertical": {"method": "eq", "ref": "center"},
}


def test_cell_covered_by_a_merge_is_read_from_its_anchor(tmp_path) -> None:
    path = _save(tmp_path, "book.xlsx", _header_book(24))
    rule = {"type": "check_cell", "sheet_idx": 0, "coordinate": "B1", "props": HEADER_PROPS}
    assert compare_xlsx_rules(path, path, rules=[rule]) == 1

    plain = _header_book(24)
    plain.active["A1"].font = Font(bold=False)
    path = _save(tmp_path, "plain.xlsx", plain)
    assert compare_xlsx_rules(path, path, rules=[rule]) == 0


def test_row_height_and_column_width_tolerance(tmp_path) -> None:
    path = _save(tmp_path, "book.xlsx", _header_book(23.8))
    height = {"type": "row_height", "sheet_idx": 0, "row": 1, "method": "eq", "ref": 24}
    width = {"type": "column_width", "sheet_idx": 0, "column": "A", "method": "eq", "ref": 18}
    assert compare_xlsx_rules(path, path, rules=[height]) == 0
    assert compare_xlsx_rules(path, path, rules=[{**height, "tolerance": 0.5}]) == 1
    assert compare_xlsx_rules(path, path, rules=[{**width, "tolerance": 0.1}]) == 1
    assert compare_xlsx_rules(path, path, rules=[{**width, "ref": 22, "tolerance": 0.1}]) == 0

    far = _save(tmp_path, "far.xlsx", _header_book(23.0))
    assert compare_xlsx_rules(far, far, rules=[{**height, "tolerance": 0.5}]) == 0


def test_sheet_data_rule_does_not_need_pandas(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pandas", None)  # import pandas -> ImportError
    path = _save(tmp_path, "book.xlsx", _header_book(24))
    assert compare_xlsx_rules(path, path, rules=[{"type": "sheet_data", "sheet_idx0": 0, "sheet_idx1": "EI0"}]) == 1


# --------------------------------------------------------------------------- pptx picture boxes


def _deck(tmp_path, boxes) -> str:
    from PIL import Image
    from pptx import Presentation

    image = tmp_path / "pic.png"
    Image.new("RGB", (40, 30), (200, 60, 60)).save(image)
    prs = Presentation()
    for box in boxes:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        if box is not None:
            slide.shapes.add_picture(str(image), *box)
    path = tmp_path / "deck.pptx"
    prs.save(path)
    return str(path)


BOX = (1_000_000, 800_000, 4_000_000, 3_000_000)
RULE = [{"reference_slide": 1, "slides": [2, 3], "picture_index": 1, "tolerance": 0.005}]


def test_pictures_share_slide_one_box(tmp_path) -> None:
    meta = PptxCompareEvaluator._validate_picture_boxes(_deck(tmp_path, [BOX, BOX, BOX]), RULE)
    assert meta["pictures"][3] == [dict(zip(("left", "top", "width", "height"), BOX))]

    # Any size is fine as long as every slide uses it.
    other = (0, 0, 6_000_000, 4_500_000)
    PptxCompareEvaluator._validate_picture_boxes(_deck(tmp_path, [other, other, other]), RULE)


def test_a_moved_resized_or_missing_picture_fails(tmp_path) -> None:
    import pytest

    moved = (BOX[0] + 500_000, *BOX[1:])
    for boxes in ([BOX, moved, BOX], [BOX, BOX, (*BOX[:2], 3_000_000, 2_250_000)], [BOX, None, BOX]):
        with pytest.raises(AssertionError):
            PptxCompareEvaluator._validate_picture_boxes(_deck(tmp_path, boxes), RULE)
