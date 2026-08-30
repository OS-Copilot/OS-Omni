"""Evaluate a saved LibreOffice Writer DOCX for multi-section reformatting tasks."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_FALSE_VALUES = {"0", "false", "off"}


def _doc_parts(doc_bytes: bytes) -> tuple[ET.Element, ET.Element | None]:
    with zipfile.ZipFile(io.BytesIO(doc_bytes), "r") as archive:
        document_xml = archive.read("word/document.xml")
        try:
            styles_xml = archive.read("word/styles.xml")
        except KeyError:
            styles_xml = None
    return ET.fromstring(document_xml), ET.fromstring(styles_xml) if styles_xml else None


def _paragraph_nodes(root: ET.Element) -> list[ET.Element]:
    body = root.find("w:body", _WORD_NS)
    return list(body.findall("w:p", _WORD_NS)) if body is not None else []


def _paragraph_text(para: ET.Element) -> str:
    return "".join(node.text or "" for node in para.findall(".//w:t", _WORD_NS)).strip()


def _visible_runs(para: ET.Element) -> list[ET.Element]:
    runs: list[ET.Element] = []
    for run in para.findall(".//w:r", _WORD_NS):
        text = "".join(node.text or "" for node in run.findall(".//w:t", _WORD_NS)).strip()
        if text:
            runs.append(run)
    return runs


def _run_prop(run_pr: ET.Element | None, prop_name: str) -> bool | None:
    if run_pr is None:
        return None
    node = run_pr.find(f"w:{prop_name}", _WORD_NS)
    if node is None:
        return None
    val = str(node.get(f"{{{_WORD_NS['w']}}}val") or "").strip().lower()
    return val not in _FALSE_VALUES


def _font_half_points(run_pr: ET.Element | None) -> int | None:
    if run_pr is None:
        return None
    for tag in ("sz", "szCs"):
        node = run_pr.find(f"w:{tag}", _WORD_NS)
        if node is None:
            continue
        raw = str(node.get(f"{{{_WORD_NS['w']}}}val") or "").strip()
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None


def _style_defs(styles_root: ET.Element | None) -> dict[str, dict[str, Any]]:
    if styles_root is None:
        return {}

    defs: dict[str, dict[str, Any]] = {}
    for style in styles_root.findall("w:style", _WORD_NS):
        style_id = str(style.get(f"{{{_WORD_NS['w']}}}styleId") or "").strip()
        if not style_id:
            continue

        name_node = style.find("w:name", _WORD_NS)
        based_on_node = style.find("w:basedOn", _WORD_NS)
        ppr = style.find("w:pPr", _WORD_NS)
        rpr = style.find("w:rPr", _WORD_NS)

        explicit_bold = None
        explicit_italic = None
        if rpr is not None:
            for prop_name, key in (("b", "explicit_bold"), ("i", "explicit_italic")):
                values = [node for tag in (prop_name, f"{prop_name}Cs") for node in rpr.findall(f"w:{tag}", _WORD_NS)]
                if values:
                    parsed = []
                    for node in values:
                        raw = str(node.get(f"{{{_WORD_NS['w']}}}val") or "").strip().lower()
                        parsed.append(raw not in _FALSE_VALUES)
                    if key == "explicit_bold":
                        explicit_bold = any(parsed)
                    else:
                        explicit_italic = any(parsed)

        alignment = None
        if ppr is not None:
            jc = ppr.find("w:jc", _WORD_NS)
            if jc is not None:
                alignment = str(jc.get(f"{{{_WORD_NS['w']}}}val") or "").strip().lower() or None

        defs[style_id] = {
            "name": str(name_node.get(f"{{{_WORD_NS['w']}}}val") or "").strip() if name_node is not None else "",
            "based_on": str(based_on_node.get(f"{{{_WORD_NS['w']}}}val") or "").strip() if based_on_node is not None else "",
            "explicit_bold": explicit_bold,
            "explicit_italic": explicit_italic,
            "explicit_size_half_points": _font_half_points(rpr),
            "alignment": alignment,
        }
    return defs


def _resolve_style(style_id: str, style_defs: dict[str, dict[str, Any]], cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not style_id:
        return {"style_id": "", "name": "", "bold": False, "italic": False, "size_half_points": None, "alignment": None}
    if style_id in cache:
        return cache[style_id]

    style_def = style_defs.get(style_id, {})
    based_on = str(style_def.get("based_on") or "").strip()
    parent = _resolve_style(based_on, style_defs, cache) if based_on else {"name": "", "bold": False, "italic": False, "size_half_points": None, "alignment": None}

    resolved = {
        "style_id": style_id,
        "name": str(style_def.get("name") or parent.get("name") or "").strip(),
        "bold": parent.get("bold", False) if style_def.get("explicit_bold") is None else bool(style_def.get("explicit_bold")),
        "italic": parent.get("italic", False) if style_def.get("explicit_italic") is None else bool(style_def.get("explicit_italic")),
        "size_half_points": parent.get("size_half_points") if style_def.get("explicit_size_half_points") is None else style_def.get("explicit_size_half_points"),
        "alignment": style_def.get("alignment") or parent.get("alignment"),
    }
    cache[style_id] = resolved
    return resolved


def _paragraph_style_id(para: ET.Element) -> str:
    ppr = para.find("w:pPr", _WORD_NS)
    if ppr is None:
        return ""
    style = ppr.find("w:pStyle", _WORD_NS)
    if style is None:
        return ""
    return str(style.get(f"{{{_WORD_NS['w']}}}val") or "").strip()


def _paragraph_alignment(para: ET.Element, resolved_style: Mapping[str, Any]) -> str | None:
    ppr = para.find("w:pPr", _WORD_NS)
    if ppr is not None:
        jc = ppr.find("w:jc", _WORD_NS)
        if jc is not None:
            return str(jc.get(f"{{{_WORD_NS['w']}}}val") or "").strip().lower() or None
    alignment = str(resolved_style.get("alignment") or "").strip().lower()
    return alignment or None


def _paragraph_has_page_break_before(para: ET.Element) -> bool:
    ppr = para.find("w:pPr", _WORD_NS)
    if ppr is not None:
        page_break_before = ppr.find("w:pageBreakBefore", _WORD_NS)
        if page_break_before is not None:
            raw = str(page_break_before.get(f"{{{_WORD_NS['w']}}}val") or "").strip().lower()
            return raw not in _FALSE_VALUES
    return False


def _paragraph_has_page_break_run(para: ET.Element) -> bool:
    for run in para.findall("w:r", _WORD_NS):
        for br in run.findall("w:br", _WORD_NS):
            if str(br.get(f"{{{_WORD_NS['w']}}}type") or "").strip().lower() == "page":
                return True
    return False


def _paragraph_has_numpr(para: ET.Element) -> bool:
    ppr = para.find("w:pPr", _WORD_NS)
    return ppr is not None and ppr.find("w:numPr", _WORD_NS) is not None


def _paragraph_metadata(para: ET.Element, style_defs: dict[str, dict[str, Any]], style_cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    style_id = _paragraph_style_id(para)
    resolved_style = _resolve_style(style_id, style_defs, style_cache) if style_id else {"style_id": "", "name": "", "bold": False, "italic": False, "size_half_points": None, "alignment": None}
    run_details = []
    for run in _visible_runs(para):
        text = "".join(node.text or "" for node in run.findall(".//w:t", _WORD_NS)).strip()
        run_pr = run.find("w:rPr", _WORD_NS)
        run_details.append(
            {
                "text": text,
                "bold": bool(_run_prop(run_pr, "b") or _run_prop(run_pr, "bCs")),
                "italic": bool(_run_prop(run_pr, "i") or _run_prop(run_pr, "iCs")),
                "size_half_points": _font_half_points(run_pr),
            }
        )

    effective_bold = (bool(run_details) and all(item["bold"] for item in run_details)) or bool(resolved_style.get("bold"))
    effective_italic = (bool(run_details) and all(item["italic"] for item in run_details)) or bool(resolved_style.get("italic"))
    run_sizes = [item["size_half_points"] for item in run_details if item["size_half_points"] is not None]
    effective_size = run_sizes[0] if run_sizes and all(size == run_sizes[0] for size in run_sizes) else resolved_style.get("size_half_points")

    return {
        "text": _paragraph_text(para),
        "style_id": style_id,
        "style_name": str(resolved_style.get("name") or ""),
        "alignment": _paragraph_alignment(para, resolved_style),
        "effective_bold": effective_bold,
        "effective_italic": effective_italic,
        "effective_size_half_points": effective_size,
        "has_numpr": _paragraph_has_numpr(para),
        "page_break_before": _paragraph_has_page_break_before(para),
        "page_break_run": _paragraph_has_page_break_run(para),
        "runs": run_details,
    }


def _style_matches_heading(entry: Mapping[str, Any], level: int) -> bool:
    tokens = " ".join(filter(None, [str(entry.get("style_id") or ""), str(entry.get("style_name") or "")])).lower()
    return "heading" in tokens and str(level) in tokens


def _find_entry(entries: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    return next((entry for entry in entries if entry.get("text") == text), None)


class LibreOfficeWriterReformatEvaluator(BaseEvaluator):
    DEFAULT_REMOTE_PATH = "~/Downloads/project_plan.docx"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.get_file is required for DOCX evaluation")

        remote_path = str(params.get("remote_path") or self.DEFAULT_REMOTE_PATH).strip()
        expected_title = str(params.get("expected_title") or "").strip()
        expected_sections = [str(item).strip() for item in (params.get("expected_sections") or []) if str(item).strip()]
        expected_budget_items = [str(item).strip() for item in (params.get("expected_budget_items") or []) if str(item).strip()]
        expected_footer = str(params.get("expected_footer") or "").strip()
        expected_title_size_pt = int(round(float(params.get("expected_title_size_pt", 28)) * 2))

        if not remote_path or not expected_title or not expected_footer:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation requires remote_path, expected_title, and expected_footer")

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
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Failed to parse saved DOCX: {exc}",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )

        style_defs = _style_defs(styles_root)
        style_cache: dict[str, dict[str, Any]] = {}
        paragraphs = [_paragraph_metadata(para, style_defs, style_cache) for para in _paragraph_nodes(root)]
        nonempty = [entry for entry in paragraphs if str(entry.get("text") or "").strip()]
        if not nonempty:
            return EvalResult(status=EvalStatus.FAIL, message="Saved DOCX has no readable paragraphs", metadata={"remote_path": remote_path, "local_copy": local_copy})

        title_entry = _find_entry(nonempty, expected_title)
        if title_entry is None:
            return EvalResult(status=EvalStatus.FAIL, message="Writer title paragraph is missing", metadata={"remote_path": remote_path, "local_copy": local_copy, "paragraphs": [entry["text"] for entry in nonempty[:10]]})

        if title_entry.get("alignment") != "center":
            return EvalResult(status=EvalStatus.FAIL, message="Writer title is not centered", metadata={"remote_path": remote_path, "local_copy": local_copy, "title": title_entry})

        title_size = title_entry.get("effective_size_half_points")
        if title_size != expected_title_size_pt:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Writer title font size mismatch: expected {expected_title_size_pt // 2}pt",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "title": title_entry},
            )

        if not (_style_matches_heading(title_entry, 1) or title_entry.get("effective_bold")):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Writer title is not formatted like a Heading 1",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "title": title_entry},
            )

        section_entries: list[dict[str, Any]] = []
        for section in expected_sections:
            entry = _find_entry(nonempty, section)
            if entry is None:
                return EvalResult(status=EvalStatus.FAIL, message=f"Missing section heading '{section}'", metadata={"remote_path": remote_path, "local_copy": local_copy, "paragraphs": [item['text'] for item in nonempty[:20]]})
            section_entries.append(entry)
            if not (_style_matches_heading(entry, 2) or entry.get("effective_bold")):
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Section heading '{section}' is not formatted like a Heading 2",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "section": entry},
                )

        normalized_budget_paragraphs = [entry for entry in nonempty if any(item in str(entry.get("text") or "") for item in expected_budget_items)]
        numbered_prefixes = [f"{index}." for index in range(1, len(expected_budget_items) + 1)]
        if len(normalized_budget_paragraphs) < len(expected_budget_items):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Not all budget items were found after save",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "budget_paragraphs": normalized_budget_paragraphs},
            )
        for index, item in enumerate(expected_budget_items, start=1):
            entry = next((candidate for candidate in normalized_budget_paragraphs if item in str(candidate.get("text") or "")), None)
            if entry is None:
                return EvalResult(status=EvalStatus.FAIL, message=f"Budget item '{item}' is missing", metadata={"remote_path": remote_path, "local_copy": local_copy})
            text = str(entry.get("text") or "").strip()
            style_tokens = " ".join(filter(None, [str(entry.get("style_id") or ""), str(entry.get("style_name") or "")])).lower()
            numbered_text = bool(re.match(rf"^{index}[\.\)]\s+", text))
            if not (entry.get("has_numpr") or "number" in style_tokens or numbered_text):
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Budget item '{item}' is not formatted as a numbered list",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "budget_entry": entry, "expected_prefixes": numbered_prefixes},
                )

        risks_entry = _find_entry(nonempty, "Risks")
        if risks_entry is None:
            return EvalResult(status=EvalStatus.FAIL, message="Missing Risks section", metadata={"remote_path": remote_path, "local_copy": local_copy})

        risks_index = paragraphs.index(risks_entry)
        page_break_ok = bool(risks_entry.get("page_break_before") or risks_entry.get("page_break_run"))
        if not page_break_ok and risks_index > 0:
            prev_para = paragraphs[risks_index - 1]
            page_break_ok = bool(prev_para.get("page_break_run") or prev_para.get("page_break_before"))
        if not page_break_ok:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="No page break was found before the Risks section",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "risks": risks_entry},
            )

        footer_entry = nonempty[-1]
        if footer_entry.get("text") != expected_footer:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Footer line is missing or not the last paragraph",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "last_paragraph": footer_entry},
            )
        if not footer_entry.get("effective_italic"):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Footer line is not italic",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "footer": footer_entry},
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Writer project plan saved with expected title, headings, numbering, page break, and italic footer",
            metadata={
                "remote_path": remote_path,
                "local_copy": local_copy,
                "paragraphs": [entry["text"] for entry in nonempty[:20]],
                "title": title_entry,
                "sections": section_entries,
                "footer": footer_entry,
            },
        )
