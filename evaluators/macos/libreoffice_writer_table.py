"""Evaluate a saved LibreOffice Writer DOCX for roster-table insertion tasks."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _doc_parts(doc_bytes: bytes) -> tuple[ET.Element, ET.Element | None]:
    with zipfile.ZipFile(io.BytesIO(doc_bytes), "r") as archive:
        document_xml = archive.read("word/document.xml")
        try:
            styles_xml = archive.read("word/styles.xml")
        except KeyError:
            styles_xml = None
    return ET.fromstring(document_xml), ET.fromstring(styles_xml) if styles_xml else None


def _body_children(root: ET.Element) -> list[ET.Element]:
    body = root.find("w:body", _WORD_NS)
    return list(body) if body is not None else []


def _text_from_para(para: ET.Element) -> str:
    return "".join(node.text or "" for node in para.findall(".//w:t", _WORD_NS)).strip()


def _is_run_bold(run: ET.Element) -> bool:
    run_pr = run.find("w:rPr", _WORD_NS)
    if run_pr is None:
        return False
    for tag in ("b", "bCs"):
        node = run_pr.find(f"w:{tag}", _WORD_NS)
        if node is not None:
            val = str(node.get(f"{{{_WORD_NS['w']}}}val") or "").strip().lower()
            return val not in {"0", "false", "off"}
    return False


def _cell_text(cell: ET.Element) -> str:
    return "\n".join(
        text for text in (_text_from_para(para) for para in cell.findall("w:p", _WORD_NS)) if text
    ).strip()


def _style_defs(styles_root: ET.Element | None) -> dict[str, dict[str, Any]]:
    if styles_root is None:
        return {}

    defs: dict[str, dict[str, Any]] = {}
    for style in styles_root.findall("w:style", _WORD_NS):
        style_id = str(style.get(f"{{{_WORD_NS['w']}}}styleId") or "").strip()
        if not style_id:
            continue
        based_on_node = style.find("w:basedOn", _WORD_NS)
        based_on = str(based_on_node.get(f"{{{_WORD_NS['w']}}}val") or "").strip() if based_on_node is not None else ""
        rpr = style.find("w:rPr", _WORD_NS)
        explicit_bold: bool | None = None
        if rpr is not None:
            bold_nodes = [node for tag in ("b", "bCs") for node in rpr.findall(f"w:{tag}", _WORD_NS)]
            if bold_nodes:
                values = []
                for node in bold_nodes:
                    raw = str(node.get(f"{{{_WORD_NS['w']}}}val") or "").strip().lower()
                    values.append(raw)
                explicit_bold = any(value not in {"0", "false", "off"} for value in values)
        defs[style_id] = {"based_on": based_on, "explicit_bold": explicit_bold}
    return defs


def _style_is_bold(
    style_id: str,
    style_defs: dict[str, dict[str, Any]],
    cache: dict[str, bool],
) -> bool:
    if not style_id:
        return False
    if style_id in cache:
        return cache[style_id]

    style_def = style_defs.get(style_id)
    if not style_def:
        cache[style_id] = False
        return False

    explicit_bold = style_def.get("explicit_bold")
    if explicit_bold is not None:
        cache[style_id] = bool(explicit_bold)
        return cache[style_id]

    based_on = str(style_def.get("based_on") or "").strip()
    cache[style_id] = _style_is_bold(based_on, style_defs, cache) if based_on else False
    return cache[style_id]


def _paragraph_style_id(para: ET.Element) -> str:
    ppr = para.find("w:pPr", _WORD_NS)
    if ppr is None:
        return ""
    style = ppr.find("w:pStyle", _WORD_NS)
    if style is None:
        return ""
    return str(style.get(f"{{{_WORD_NS['w']}}}val") or "").strip()


class LibreOfficeWriterTableEvaluator(BaseEvaluator):
    DEFAULT_REMOTE_PATH = "~/Downloads/team_roster.docx"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.get_file is required for DOCX evaluation")

        remote_path = str(params.get("remote_path") or self.DEFAULT_REMOTE_PATH).strip()
        expected_title = str(params.get("expected_title") or "").strip()
        expected_body = str(params.get("expected_body") or "").strip()
        expected_headers = [str(item).strip() for item in (params.get("expected_headers") or [])]
        expected_rows = [
            [str(cell).strip() for cell in row]
            for row in (params.get("expected_rows") or [])
            if isinstance(row, list)
        ]

        if not remote_path or not expected_title or not expected_body:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation requires remote_path, expected_title, and expected_body")

        try:
            doc_bytes = controller.get_file(remote_path)
        except Exception as exc:
            return EvalResult(status=EvalStatus.FAIL, message=f"Failed to fetch saved Writer document: {exc}")

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
            root, styles_root = _doc_parts(doc_bytes)
            body_children = _body_children(root)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Failed to parse saved DOCX: {exc}",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )
        style_defs = _style_defs(styles_root)
        style_bold_cache: dict[str, bool] = {}

        top_level_paras = [node for node in body_children if node.tag == f"{{{_WORD_NS['w']}}}p"]
        top_level_text = [_text_from_para(para) for para in top_level_paras if _text_from_para(para)]
        if len(top_level_text) < 2:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Saved DOCX is missing required top-level paragraphs",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "paragraphs": top_level_text},
            )

        if top_level_text[0] != expected_title:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Writer title mismatch: expected '{expected_title}', got '{top_level_text[0]}'",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "paragraphs": top_level_text[:6]},
            )

        if top_level_text[1] != expected_body:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Writer body paragraph mismatch",
                metadata={
                    "remote_path": remote_path,
                    "local_copy": local_copy,
                    "expected_body": expected_body,
                    "actual_body": top_level_text[1],
                },
            )

        tables = [node for node in body_children if node.tag == f"{{{_WORD_NS['w']}}}tbl"]
        if not tables:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Writer document has no table",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )

        table = tables[0]
        rows = table.findall("w:tr", _WORD_NS)
        if len(rows) != 1 + len(expected_rows):
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Writer table row count mismatch: expected {1 + len(expected_rows)}, got {len(rows)}",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )

        parsed_rows: list[list[str]] = []
        header_bold_details: list[dict[str, Any]] = []
        header_bold_flags: list[bool] = []
        for row_idx, row in enumerate(rows):
            cells = row.findall("w:tc", _WORD_NS)
            parsed = [_cell_text(cell) for cell in cells]
            parsed_rows.append(parsed)
            if row_idx == 0:
                for cell_idx, cell in enumerate(cells):
                    visible_runs = []
                    for run in cell.findall(".//w:r", _WORD_NS):
                        run_text = "".join(node.text or "" for node in run.findall(".//w:t", _WORD_NS)).strip()
                        if run_text:
                            visible_runs.append({"text": run_text, "bold": _is_run_bold(run)})
                    paragraph_styles = []
                    paragraph_style_bold = False
                    for para in cell.findall("w:p", _WORD_NS):
                        style_id = _paragraph_style_id(para)
                        if not style_id:
                            continue
                        style_bold = _style_is_bold(style_id, style_defs, style_bold_cache)
                        paragraph_styles.append({"style_id": style_id, "bold": style_bold})
                        paragraph_style_bold = paragraph_style_bold or style_bold
                    header_bold_details.append(
                        {
                            "cell_index": cell_idx,
                            "runs": visible_runs,
                            "paragraph_styles": paragraph_styles,
                        }
                    )
                    runs_all_bold = bool(visible_runs) and all(run["bold"] for run in visible_runs)
                    header_bold_flags.append(runs_all_bold or paragraph_style_bold)

        if expected_headers and parsed_rows[0] != expected_headers:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Writer table header mismatch: expected {expected_headers}, got {parsed_rows[0]}",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "table_rows": parsed_rows},
            )

        for idx, expected in enumerate(expected_rows, start=1):
            actual = parsed_rows[idx] if idx < len(parsed_rows) else []
            if actual != expected:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Writer table row {idx} mismatch: expected {expected}, got {actual}",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "table_rows": parsed_rows},
                )

        if expected_headers:
            if not all(header_bold_flags):
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message="Writer table header is not fully bold",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "header_runs": header_bold_details},
                )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Writer roster table saved with expected content and bold header",
            metadata={
                "remote_path": remote_path,
                "local_copy": local_copy,
                "paragraphs": top_level_text[:6],
                "table_rows": parsed_rows,
                "header_runs": header_bold_details,
            },
        )
