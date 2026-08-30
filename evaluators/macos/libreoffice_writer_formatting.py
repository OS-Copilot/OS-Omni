"""Evaluate a saved LibreOffice Writer document for title formatting and body integrity."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _doc_root(doc_bytes: bytes) -> ET.Element:
    with zipfile.ZipFile(io.BytesIO(doc_bytes), "r") as archive:
        xml = archive.read("word/document.xml")
    return ET.fromstring(xml)


def _paragraph_nodes(root: ET.Element) -> list[ET.Element]:
    return list(root.findall(".//w:body/w:p", _WORD_NS))


def _paragraph_text(para: ET.Element) -> str:
    return "".join(node.text or "" for node in para.findall(".//w:t", _WORD_NS)).strip()


def _visible_runs(para: ET.Element) -> list[ET.Element]:
    runs: list[ET.Element] = []
    for run in para.findall(".//w:r", _WORD_NS):
        text = "".join(node.text or "" for node in run.findall(".//w:t", _WORD_NS)).strip()
        if text:
            runs.append(run)
    return runs


def _is_on(run_pr: ET.Element | None, prop_name: str) -> bool:
    if run_pr is None:
        return False
    prop = run_pr.find(f"w:{prop_name}", _WORD_NS)
    if prop is None:
        return False
    val = str(prop.get(f"{{{_WORD_NS['w']}}}val") or "").strip().lower()
    return val not in {"0", "false", "off"}


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


class LibreOfficeWriterFormattingEvaluator(BaseEvaluator):
    """PASS if the saved DOCX keeps body text and formats the title as requested."""

    DEFAULT_REMOTE_PATH = "~/Downloads/writer_format_title_template.docx"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.get_file is required for DOCX evaluation")

        remote_path = str(params.get("remote_path") or self.DEFAULT_REMOTE_PATH).strip()
        expected_title = str(params.get("expected_title") or "").strip()
        expected_body = [str(item).strip() for item in (params.get("expected_body_paragraphs") or []) if str(item).strip()]
        expected_bold = bool(params.get("expected_title_bold", False))
        expected_size_pt_raw = params.get("expected_title_size_pt")
        expected_size_half_points = None
        if expected_size_pt_raw not in (None, ""):
            expected_size_half_points = int(round(float(expected_size_pt_raw) * 2))

        if not remote_path or not expected_title:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation requires remote_path and expected_title")

        try:
            doc_bytes = controller.get_file(remote_path)
        except Exception as exc:
            return EvalResult(status=EvalStatus.FAIL, message=f"Failed to fetch saved Writer document: {exc}", metadata={"remote_path": remote_path})

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
            root = _doc_root(doc_bytes)
            paragraphs = _paragraph_nodes(root)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Failed to parse saved DOCX: {exc}",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )

        text_paragraphs = [_paragraph_text(para) for para in paragraphs if _paragraph_text(para)]
        if not text_paragraphs:
            return EvalResult(status=EvalStatus.FAIL, message="Saved DOCX has no readable paragraphs", metadata={"remote_path": remote_path, "local_copy": local_copy})

        actual_title = text_paragraphs[0]
        if actual_title != expected_title:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Writer title mismatch: expected '{expected_title}', got '{actual_title}'",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "paragraphs": text_paragraphs[:5]},
            )

        if len(text_paragraphs) < 1 + len(expected_body):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Saved DOCX is missing expected body paragraphs",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "paragraphs": text_paragraphs[:5], "expected_body_paragraphs": expected_body},
            )

        actual_body = text_paragraphs[1 : 1 + len(expected_body)]
        for expected, actual in zip(expected_body, actual_body):
            if actual != expected:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Writer body paragraph mismatch: expected '{expected}', got '{actual}'",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "paragraphs": text_paragraphs[:5]},
                )

        first_nonempty_para = next((para for para in paragraphs if _paragraph_text(para)), None)
        if first_nonempty_para is None:
            return EvalResult(status=EvalStatus.FAIL, message="Could not locate title paragraph", metadata={"remote_path": remote_path, "local_copy": local_copy})

        runs = _visible_runs(first_nonempty_para)
        if not runs:
            return EvalResult(status=EvalStatus.FAIL, message="Title paragraph has no readable runs", metadata={"remote_path": remote_path, "local_copy": local_copy})

        run_details = []
        for run in runs:
            text = "".join(node.text or "" for node in run.findall(".//w:t", _WORD_NS)).strip()
            run_pr = run.find("w:rPr", _WORD_NS)
            is_bold = _is_on(run_pr, "b") or _is_on(run_pr, "bCs")
            size_half_points = _font_half_points(run_pr)
            run_details.append({"text": text, "bold": is_bold, "size_half_points": size_half_points})

        if expected_bold and not all(item["bold"] for item in run_details):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Writer title is not fully bold",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "title_runs": run_details},
            )

        if expected_size_half_points is not None:
            sizes = [item["size_half_points"] for item in run_details]
            if any(size != expected_size_half_points for size in sizes):
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Writer title font size mismatch: expected {expected_size_half_points // 2}pt",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "title_runs": run_details},
                )

        return EvalResult(
            status=EvalStatus.PASS,
            message=f"Writer document saved with expected title formatting for '{expected_title}'",
            metadata={
                "remote_path": remote_path,
                "local_copy": local_copy,
                "paragraph_count": len(text_paragraphs),
                "paragraphs_preview": text_paragraphs[:5],
                "title_runs": run_details,
            },
        )
