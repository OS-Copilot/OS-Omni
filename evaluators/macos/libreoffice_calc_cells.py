"""Evaluate a saved LibreOffice Calc workbook by checking XLSX sheets and cells."""

from __future__ import annotations

import io
import math
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from xml.etree import ElementTree as ET

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_XLSX_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_PKG_REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
_REL_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"



def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        xml = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml)
    strings: list[str] = []
    for item in root.findall("x:si", _XLSX_NS):
        text = "".join(node.text or "" for node in item.findall(".//x:t", _XLSX_NS))
        strings.append(text)
    return strings



def _normalize_archive_path(base_dir: str, target: str) -> str:
    combined = PurePosixPath(target.lstrip("/")) if target.startswith("/") else PurePosixPath(base_dir) / target
    normalized_parts: list[str] = []
    for part in combined.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if normalized_parts:
                normalized_parts.pop()
            continue
        normalized_parts.append(part)
    return "/".join(normalized_parts)



def _read_sheet_cells_xml(sheet_xml: bytes, shared_strings: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    root = ET.fromstring(sheet_xml)
    values: dict[str, str] = {}
    formulas: dict[str, str] = {}

    for cell in root.findall(".//x:sheetData/x:row/x:c", _XLSX_NS):
        ref = str(cell.get("r") or "").strip()
        if not ref:
            continue

        cell_type = str(cell.get("t") or "").strip()
        formula = (cell.findtext("x:f", default="", namespaces=_XLSX_NS) or "").strip()
        value = ""

        if cell_type == "s":
            raw = (cell.findtext("x:v", default="", namespaces=_XLSX_NS) or "").strip()
            if raw:
                try:
                    idx = int(raw)
                except ValueError:
                    value = raw
                else:
                    value = shared_strings[idx] if 0 <= idx < len(shared_strings) else raw
        elif cell_type == "inlineStr":
            value = "".join(node.text or "" for node in cell.findall(".//x:is/x:t", _XLSX_NS)).strip()
        else:
            value = (cell.findtext("x:v", default="", namespaces=_XLSX_NS) or "").strip()

        values[ref] = value
        if formula:
            formulas[ref] = formula

    return values, formulas



def _read_workbook(doc_bytes: bytes) -> tuple[list[str], dict[str, tuple[dict[str, str], dict[str, str]]]]:
    with zipfile.ZipFile(io.BytesIO(doc_bytes), "r") as archive:
        shared_strings = _read_shared_strings(archive)

        rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets: dict[str, str] = {}
        for relationship in rels_root.findall("r:Relationship", _PKG_REL_NS):
            rel_id = str(relationship.get("Id") or "").strip()
            target = str(relationship.get("Target") or "").strip()
            if rel_id and target:
                rel_targets[rel_id] = _normalize_archive_path("xl", target)

        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet_order: list[str] = []
        sheets: dict[str, tuple[dict[str, str], dict[str, str]]] = {}

        for sheet in workbook_root.findall("x:sheets/x:sheet", _XLSX_NS):
            sheet_name = str(sheet.get("name") or "").strip()
            rel_id = str(sheet.get(_REL_ATTR) or "").strip()
            target_path = rel_targets.get(rel_id, "")
            if not sheet_name or not target_path:
                continue
            sheet_xml = archive.read(target_path)
            sheet_order.append(sheet_name)
            sheets[sheet_name] = _read_sheet_cells_xml(sheet_xml, shared_strings)

    return sheet_order, sheets



def _normalize_text_cells(raw: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(cell).strip().upper(): str(value).strip()
        for cell, value in dict(raw or {}).items()
        if str(cell).strip()
    }



def _normalize_numeric_cells(raw: Mapping[str, Any]) -> dict[str, float]:
    return {
        str(cell).strip().upper(): float(value)
        for cell, value in dict(raw or {}).items()
        if str(cell).strip()
    }



def _normalize_formula_cells(raw: Mapping[str, Any]) -> dict[str, list[str]]:
    return {
        str(cell).strip().upper(): [
            str(item).strip()
            for item in (value if isinstance(value, list) else [value])
            if str(item).strip()
        ]
        for cell, value in dict(raw or {}).items()
        if str(cell).strip()
    }



def _normalize_sheet_checks(raw: Mapping[str, Any], normalizer: Callable[[Mapping[str, Any]], Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for sheet_name, sheet_checks in dict(raw or {}).items():
        cleaned_name = str(sheet_name).strip()
        if cleaned_name:
            normalized[cleaned_name] = normalizer(sheet_checks)
    return normalized



def _normalize_name_list(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else [raw]
    return [str(item).strip() for item in items if str(item).strip()]


class LibreOfficeCalcCellEvaluator(BaseEvaluator):
    """PASS if the saved workbook matches expected sheet names, cell values, and formulas."""

    DEFAULT_REMOTE_PATH = "~/Downloads/calc_inventory_totals_template.xlsx"
    NUMERIC_TOLERANCE = 1e-6

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.get_file is required for XLSX evaluation",
            )

        remote_path = str(params.get("remote_path") or self.DEFAULT_REMOTE_PATH).strip()
        expected_text_cells = _normalize_text_cells(params.get("expected_text_cells") or {})
        expected_numeric_cells = _normalize_numeric_cells(params.get("expected_numeric_cells") or {})
        expected_formula_substrings = _normalize_formula_cells(params.get("expected_formula_substrings") or {})
        expected_sheet_names = _normalize_name_list(params.get("expected_sheet_names") or [])
        required_sheet_names = _normalize_name_list(params.get("required_sheet_names") or [])
        forbidden_sheet_names = _normalize_name_list(params.get("forbidden_sheet_names") or [])
        per_sheet_expected_text_cells = _normalize_sheet_checks(
            params.get("per_sheet_expected_text_cells") or {},
            _normalize_text_cells,
        )
        per_sheet_expected_numeric_cells = _normalize_sheet_checks(
            params.get("per_sheet_expected_numeric_cells") or {},
            _normalize_numeric_cells,
        )
        per_sheet_expected_formula_substrings = _normalize_sheet_checks(
            params.get("per_sheet_expected_formula_substrings") or {},
            _normalize_formula_cells,
        )
        default_sheet_name = str(params.get("sheet_name") or "").strip()

        if not remote_path:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires remote_path",
            )
        if not (
            expected_text_cells
            or expected_numeric_cells
            or expected_formula_substrings
            or expected_sheet_names
            or required_sheet_names
            or forbidden_sheet_names
            or per_sheet_expected_text_cells
            or per_sheet_expected_numeric_cells
            or per_sheet_expected_formula_substrings
        ):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires at least one expected sheet or cell check",
            )

        try:
            doc_bytes = controller.get_file(remote_path)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Failed to fetch saved Calc workbook: {exc}",
                metadata={"remote_path": remote_path},
            )

        run_dir_raw = context.get("run_dir")
        local_copy = ""
        if run_dir_raw:
            try:
                eval_dir = Path(run_dir_raw) / "_evaluator"
                eval_dir.mkdir(parents=True, exist_ok=True)
                local_path = eval_dir / Path(remote_path).name
                local_path.write_bytes(doc_bytes)
                local_copy = str(local_path)
            except OSError:
                local_copy = ""

        try:
            sheet_order, workbook_sheets = _read_workbook(doc_bytes)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Failed to parse saved XLSX: {exc}",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )

        if expected_sheet_names and sheet_order != expected_sheet_names:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Calc sheet names mismatch: expected {expected_sheet_names}, got {sheet_order}",
                metadata={
                    "remote_path": remote_path,
                    "local_copy": local_copy,
                    "expected_sheet_names": expected_sheet_names,
                    "actual_sheet_names": sheet_order,
                },
            )

        if required_sheet_names:
            missing_sheet_names = [sheet for sheet in required_sheet_names if sheet not in workbook_sheets]
            if missing_sheet_names:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Calc required sheets missing: {missing_sheet_names}",
                    metadata={
                        "remote_path": remote_path,
                        "local_copy": local_copy,
                        "required_sheet_names": required_sheet_names,
                        "actual_sheet_names": sheet_order,
                    },
                )

        if forbidden_sheet_names:
            present_forbidden = [sheet for sheet in forbidden_sheet_names if sheet in workbook_sheets]
            if present_forbidden:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Calc forbidden sheets still present: {present_forbidden}",
                    metadata={
                        "remote_path": remote_path,
                        "local_copy": local_copy,
                        "forbidden_sheet_names": forbidden_sheet_names,
                        "actual_sheet_names": sheet_order,
                    },
                )

        target_sheet_name = default_sheet_name or (sheet_order[0] if sheet_order else "")
        if (expected_text_cells or expected_numeric_cells or expected_formula_substrings) and target_sheet_name not in workbook_sheets:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Calc target sheet '{target_sheet_name}' not found",
                metadata={
                    "remote_path": remote_path,
                    "local_copy": local_copy,
                    "target_sheet_name": target_sheet_name,
                    "actual_sheet_names": sheet_order,
                },
            )

        checked_sheets: set[str] = set()

        def check_sheet(
            sheet_name: str,
            *,
            text_cells: Mapping[str, str],
            numeric_cells: Mapping[str, float],
            formula_cells: Mapping[str, list[str]],
        ) -> EvalResult | None:
            values, formulas = workbook_sheets[sheet_name]

            for cell, expected in text_cells.items():
                actual = values.get(cell, "")
                if actual != expected:
                    return EvalResult(
                        status=EvalStatus.FAIL,
                        message=f"Calc text mismatch on sheet '{sheet_name}' at {cell}: expected '{expected}', got '{actual}'",
                        metadata={
                            "remote_path": remote_path,
                            "local_copy": local_copy,
                            "sheet_name": sheet_name,
                            "cell": cell,
                            "actual": actual,
                            "expected": expected,
                        },
                    )

            for cell, expected in numeric_cells.items():
                actual_raw = values.get(cell, "")
                try:
                    actual = float(actual_raw)
                except (TypeError, ValueError):
                    return EvalResult(
                        status=EvalStatus.FAIL,
                        message=f"Calc numeric cell on sheet '{sheet_name}' at {cell} is not a number: '{actual_raw}'",
                        metadata={
                            "remote_path": remote_path,
                            "local_copy": local_copy,
                            "sheet_name": sheet_name,
                            "cell": cell,
                            "actual": actual_raw,
                            "expected": expected,
                        },
                    )
                if math.fabs(actual - expected) > self.NUMERIC_TOLERANCE:
                    return EvalResult(
                        status=EvalStatus.FAIL,
                        message=f"Calc numeric mismatch on sheet '{sheet_name}' at {cell}: expected {expected:g}, got {actual:g}",
                        metadata={
                            "remote_path": remote_path,
                            "local_copy": local_copy,
                            "sheet_name": sheet_name,
                            "cell": cell,
                            "actual": actual,
                            "expected": expected,
                        },
                    )

            for cell, substrings in formula_cells.items():
                actual_formula = formulas.get(cell, "")
                lowered = actual_formula.lower()
                missing = [part for part in substrings if part.lower() not in lowered]
                if missing:
                    return EvalResult(
                        status=EvalStatus.FAIL,
                        message=f"Calc formula mismatch on sheet '{sheet_name}' at {cell}: missing {missing} in '{actual_formula}'",
                        metadata={
                            "remote_path": remote_path,
                            "local_copy": local_copy,
                            "sheet_name": sheet_name,
                            "cell": cell,
                            "actual_formula": actual_formula,
                            "expected_formula_substrings": substrings,
                        },
                    )

            return None

        if expected_text_cells or expected_numeric_cells or expected_formula_substrings:
            checked_sheets.add(target_sheet_name)
            result = check_sheet(
                target_sheet_name,
                text_cells=expected_text_cells,
                numeric_cells=expected_numeric_cells,
                formula_cells=expected_formula_substrings,
            )
            if result is not None:
                return result

        all_sheet_names = {
            *per_sheet_expected_text_cells.keys(),
            *per_sheet_expected_numeric_cells.keys(),
            *per_sheet_expected_formula_substrings.keys(),
        }
        for sheet_name in sorted(all_sheet_names):
            if sheet_name not in workbook_sheets:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Calc expected sheet '{sheet_name}' not found",
                    metadata={
                        "remote_path": remote_path,
                        "local_copy": local_copy,
                        "sheet_name": sheet_name,
                        "actual_sheet_names": sheet_order,
                    },
                )
            checked_sheets.add(sheet_name)
            result = check_sheet(
                sheet_name,
                text_cells=per_sheet_expected_text_cells.get(sheet_name, {}),
                numeric_cells=per_sheet_expected_numeric_cells.get(sheet_name, {}),
                formula_cells=per_sheet_expected_formula_substrings.get(sheet_name, {}),
            )
            if result is not None:
                return result

        preview_sheet = target_sheet_name or (sorted(checked_sheets)[0] if checked_sheets else (sheet_order[0] if sheet_order else ""))
        preview_values, preview_formulas_source = workbook_sheets.get(preview_sheet, ({}, {}))
        preview_cells = sorted(
            {
                *expected_text_cells.keys(),
                *expected_numeric_cells.keys(),
                *expected_formula_substrings.keys(),
                *per_sheet_expected_text_cells.get(preview_sheet, {}).keys(),
                *per_sheet_expected_numeric_cells.get(preview_sheet, {}).keys(),
                *per_sheet_expected_formula_substrings.get(preview_sheet, {}).keys(),
            }
        )
        preview = {cell: preview_values.get(cell, "") for cell in preview_cells[:12]}
        preview_formulas = {cell: preview_formulas_source.get(cell, "") for cell in preview_cells[:12] if preview_formulas_source.get(cell, "")}

        return EvalResult(
            status=EvalStatus.PASS,
            message="Calc workbook matches expected sheet names and cell values",
            metadata={
                "remote_path": remote_path,
                "local_copy": local_copy,
                "sheet_names": sheet_order,
                "checked_sheets": sorted(checked_sheets),
                "checked_text_cells": sorted(expected_text_cells),
                "checked_numeric_cells": sorted(expected_numeric_cells),
                "checked_formula_cells": sorted(expected_formula_substrings),
                "checked_per_sheet_text_cells": {sheet: sorted(cells) for sheet, cells in per_sheet_expected_text_cells.items()},
                "checked_per_sheet_numeric_cells": {sheet: sorted(cells) for sheet, cells in per_sheet_expected_numeric_cells.items()},
                "checked_per_sheet_formula_cells": {sheet: sorted(cells) for sheet, cells in per_sheet_expected_formula_substrings.items()},
                "preview_sheet": preview_sheet,
                "cells_preview": preview,
                "formulas_preview": preview_formulas,
            },
        )
