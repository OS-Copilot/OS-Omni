"""Evaluate a saved LibreOffice Writer document by reading the DOCX file."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _extract_docx_paragraphs(doc_bytes: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(doc_bytes), "r") as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs: list[str] = []
    for para in root.findall(".//w:body/w:p", _WORD_NS):
        text = "".join(node.text or "" for node in para.findall(".//w:t", _WORD_NS)).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


class LibreOfficeWriterTitleEvaluator(BaseEvaluator):
    """PASS if the saved DOCX has the expected title and any required body paragraphs."""

    DEFAULT_REMOTE_PATH = "~/Downloads/writer_title_draft.docx"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.get_file is required for DOCX evaluation",
            )

        remote_path = str(params.get("remote_path") or self.DEFAULT_REMOTE_PATH).strip()
        expected_title = str(params.get("expected_title") or "").strip()
        if not remote_path or not expected_title:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation requires remote_path and expected_title",
            )

        expected_body = [
            str(item).strip()
            for item in (params.get("expected_body_paragraphs") or [])
            if str(item).strip()
        ]
        forbidden_title = str(params.get("forbidden_title") or "").strip()

        try:
            doc_bytes = controller.get_file(remote_path)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Failed to fetch saved Writer document: {exc}",
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
            paragraphs = _extract_docx_paragraphs(doc_bytes)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Failed to parse saved DOCX: {exc}",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )

        if not paragraphs:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Saved DOCX has no readable paragraphs",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )

        actual_title = paragraphs[0]
        if actual_title != expected_title:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Writer title mismatch: expected '{expected_title}', got '{actual_title}'",
                metadata={
                    "remote_path": remote_path,
                    "local_copy": local_copy,
                    "paragraphs": paragraphs[:5],
                },
            )

        if forbidden_title and actual_title == forbidden_title:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Writer title still shows forbidden text '{forbidden_title}'",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )

        if len(paragraphs) < 1 + len(expected_body):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Saved DOCX is missing expected body paragraphs",
                metadata={
                    "remote_path": remote_path,
                    "local_copy": local_copy,
                    "paragraphs": paragraphs[:5],
                    "expected_body_paragraphs": expected_body,
                },
            )

        body_slice = paragraphs[1 : 1 + len(expected_body)]
        for expected, actual in zip(expected_body, body_slice):
            if actual != expected:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Writer body paragraph mismatch: expected '{expected}', got '{actual}'",
                    metadata={
                        "remote_path": remote_path,
                        "local_copy": local_copy,
                        "paragraphs": paragraphs[:5],
                    },
                )

        return EvalResult(
            status=EvalStatus.PASS,
            message=f"Writer document saved with expected title '{expected_title}'",
            metadata={
                "remote_path": remote_path,
                "local_copy": local_copy,
                "paragraph_count": len(paragraphs),
                "paragraphs_preview": paragraphs[:5],
            },
        )
