"""DOCX structural comparison for OSWorld-style Writer tasks."""

from __future__ import annotations

import logging
from typing import Any, Iterator

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.text.paragraph import Paragraph
from docx.table import Table

logger = logging.getLogger(__name__)


def _iter_body_paragraphs(document: Document) -> Iterator[Paragraph]:
    for p in document.paragraphs:
        yield p
    for table in document.tables:
        yield from _iter_table_paragraphs(table)


def _iter_table_paragraphs(table: Table) -> Iterator[Paragraph]:
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                yield p


def _norm_tri(v: Any) -> bool:
    return v not in (None, False)


def _paragraph_has_tabstop_word_split(p: Paragraph, *, words_before_tab: int) -> bool:
    """True if paragraph contains a tab and the segment before the first tab has ``words_before_tab`` words."""
    text = p.text or ""
    if "\t" not in text:
        return False
    parts = text.split("\t", 1)
    if len(parts) != 2:
        return False
    return len(parts[0].split()) == words_before_tab


def _same_run_format(run1: Any, run2: Any, *, examine_strike_through: bool) -> bool:
    if (run1.text or "") != (run2.text or ""):
        return False
    b1 = run1.bold
    b2 = run2.bold
    if _norm_tri(b1) != _norm_tri(b2):
        return False
    i1 = run1.italic
    i2 = run2.italic
    if _norm_tri(i1) != _norm_tri(i2):
        return False
    u1 = run1.underline
    u2 = run2.underline
    if u1 != u2 and not (u1 is None and u2 is None):
        return False
    if examine_strike_through:
        s1 = getattr(run1.font, "strike", None)
        s2 = getattr(run2.font, "strike", None)
        if _norm_tri(s1) != _norm_tri(s2):
            return False
    return True


def compare_docx_files(file1_path: str, file2_path: str, **options: Any) -> int:
    """Return 1 if documents match under options, else 0."""
    examine_text = bool(options.get("examine_text", True))
    examine_strike_through = bool(options.get("examine_strike_through", True))
    examine_alignment = bool(options.get("examine_alignment", False))
    tabstop_para = options.get("examine_tabstop_paragraph")
    tabstop_words = int(options.get("tabstop_words_before_tab", 3) or 3)

    d1 = Document(file1_path)
    d2 = Document(file2_path)

    paras1 = list(_iter_body_paragraphs(d1))
    paras2 = list(_iter_body_paragraphs(d2))
    if len(paras1) != len(paras2):
        logger.debug("docx: paragraph count differs %s vs %s", len(paras1), len(paras2))
        return 0

    tabstop_pi: int | None = int(tabstop_para) if tabstop_para is not None else None

    for pi, (p1, p2) in enumerate(zip(paras1, paras2)):
        if tabstop_pi is not None and pi == tabstop_pi:
            if (p1.text or "").strip() != (p2.text or "").strip():
                logger.debug("docx: tabstop paragraph text mismatch")
                return 0
            if not _paragraph_has_tabstop_word_split(p1, words_before_tab=tabstop_words):
                logger.debug("docx: actual tabstop paragraph structure invalid")
                return 0
            if not _paragraph_has_tabstop_word_split(p2, words_before_tab=tabstop_words):
                logger.debug("docx: expected tabstop paragraph structure invalid")
                return 0
            continue

        if examine_alignment:
            a1 = p1.paragraph_format.alignment or WD_ALIGN_PARAGRAPH.LEFT
            a2 = p2.paragraph_format.alignment or WD_ALIGN_PARAGRAPH.LEFT
            if a1 != a2:
                return 0
        if examine_text:
            if (p1.text or "").strip() != (p2.text or "").strip():
                return 0
        r1 = list(p1.runs)
        r2 = list(p2.runs)
        if len(r1) != len(r2):
            logger.debug("docx: para %s run count differs", pi)
            return 0
        for run1, run2 in zip(r1, r2):
            if not _same_run_format(
                run1,
                run2,
                examine_strike_through=examine_strike_through,
            ):
                return 0
    return 1
