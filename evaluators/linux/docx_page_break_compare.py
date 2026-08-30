"""DOCX page break evaluator for OSWorld-style Writer tasks."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from docx import Document

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux.office_path_resolve import resolve_office_file_pair, unlink_if_temp

logger = logging.getLogger(__name__)


def count_page_breaks(file_path: str) -> int:
    """Count the number of page breaks in a docx file."""
    try:
        doc = Document(file_path)
        count = 0
        for para in doc.paragraphs:
            # Check for manual page break (text contains page break character)
            if para._element.xml:
                if "w:br" in para._element.xml and 'w:type="page"' in para._element.xml:
                    count += 1
        # Also check in section properties (page break before section)
        for section in doc.sections:
            sectPr = section._element
            if sectPr is not None and sectPr.xml:
                if "w:pageBreakBefore" in sectPr.xml:
                    count += 1
        return count
    except Exception as e:
        logger.error(f"Error counting page breaks: {e}")
        return 0


class DocxPageBreakEvaluator(BaseEvaluator):
    """Check page break count in a DOCX file."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        actual = str(params.get("actual_path") or "").strip()
        expected = str(params.get("expected_path") or "").strip()

        if not actual:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.actual_path is required",
            )

        options = params.get("options") or {}
        expected_page_break_count = options.get("expected_page_break_count", None)
        rules = options.get("rules", {})
        if not expected_page_break_count and rules:
            expected_page_break_count = rules.get("page_break_count")

        try:
            actual_path, expected_path, actual_tmp, expected_tmp = resolve_office_file_pair(
                actual,
                expected,
                controller,
                actual_prefix="helloworld_docx_actual_",
                expected_prefix="helloworld_docx_expected_",
                actual_suffix=".docx",
                expected_suffix=".docx",
            )
        except FileNotFoundError as exc:
            return EvalResult(status=EvalStatus.ERROR, message=str(exc))
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"failed to resolve DOCX paths: {exc}",
            )

        meta = {
            "actual_path": str(actual_path),
            "expected_path": str(expected_path) if expected_path else None,
            "actual_temp": actual_tmp,
            "expected_temp": expected_tmp,
        }

        try:
            actual_count = count_page_breaks(str(actual_path))
            meta["actual_page_break_count"] = actual_count

            if expected_page_break_count is not None:
                score = 1 if actual_count >= expected_page_break_count else 0
                meta["expected_page_break_count"] = expected_page_break_count
            else:
                # Compare with expected file if provided
                if expected_path:
                    expected_count = count_page_breaks(str(expected_path))
                    meta["expected_page_break_count"] = expected_count
                    score = 1 if actual_count == expected_count else 1 if actual_count > 0 else 0
                else:
                    score = 1 if actual_count > 0 else 0

        except Exception as exc:
            meta["error"] = repr(exc)
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"DOCX page break check raised: {exc}",
                metadata=meta,
            )
        finally:
            unlink_if_temp(actual_path, actual_tmp)
            unlink_if_temp(expected_path, expected_tmp)

        meta["score"] = float(score)
        if float(score) >= 1.0:
            return EvalResult(status=EvalStatus.PASS, message="DOCX page break check passed", metadata=meta)
        return EvalResult(status=EvalStatus.FAIL, message="DOCX page break check failed", metadata=meta)
