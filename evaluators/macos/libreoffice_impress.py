"""Evaluate saved LibreOffice Impress PPTX files for slide, text, notes, and formatting checks."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_P_NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
_A_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
_PKG_REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
_REL_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_TITLE_PLACEHOLDERS = {"title", "ctrTitle"}


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


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.findall(".//a:t", _A_NS)).strip()


def _shape_text(shape: ET.Element) -> str:
    paragraphs = [_paragraph_text(para) for para in shape.findall(".//a:p", _A_NS)]
    return "\n".join(text for text in paragraphs if text)


def _shape_placeholder_type(shape: ET.Element) -> str:
    placeholder = shape.find("p:nvSpPr/p:nvPr/p:ph", _P_NS)
    if placeholder is None:
        return ""
    return str(placeholder.get("type") or "").strip()


def _shape_runs(shape: ET.Element) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for run in shape.findall(".//a:r", _A_NS):
        text = "".join(node.text or "" for node in run.findall(".//a:t", _A_NS)).strip()
        if not text:
            continue
        run_pr = run.find("a:rPr", _A_NS)
        bold = str(run_pr.get("b") or "") == "1" if run_pr is not None else False
        runs.append({"text": text, "bold": bold})
    return runs


def _read_notes_text(archive: zipfile.ZipFile, slide_path: str) -> str:
    rels_path = str(PurePosixPath(slide_path).parent / "_rels" / (PurePosixPath(slide_path).name + ".rels"))
    try:
        rels_root = ET.fromstring(archive.read(rels_path))
    except KeyError:
        return ""

    notes_target = ""
    for relationship in rels_root.findall("r:Relationship", _PKG_REL_NS):
        rel_type = str(relationship.get("Type") or "")
        if rel_type.endswith("/notesSlide"):
            notes_target = _normalize_archive_path(str(PurePosixPath(slide_path).parent), str(relationship.get("Target") or ""))
            break
    if not notes_target:
        return ""

    try:
        notes_root = ET.fromstring(archive.read(notes_target))
    except KeyError:
        return ""

    pieces = [str(node.text or "").strip() for node in notes_root.findall(".//a:t", _A_NS)]
    return "\n".join(piece for piece in pieces if piece)


def _read_presentation(doc_bytes: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(doc_bytes), "r") as archive:
        rels_root = ET.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
        rel_targets = {
            str(relationship.get("Id") or "").strip(): _normalize_archive_path("ppt", str(relationship.get("Target") or ""))
            for relationship in rels_root.findall("r:Relationship", _PKG_REL_NS)
            if str(relationship.get("Id") or "").strip() and str(relationship.get("Target") or "").strip()
        }

        presentation_root = ET.fromstring(archive.read("ppt/presentation.xml"))
        slides: list[dict[str, Any]] = []
        for slide_ref in presentation_root.findall("p:sldIdLst/p:sldId", _P_NS):
            rel_id = str(slide_ref.get(_REL_ATTR) or "").strip()
            slide_path = rel_targets.get(rel_id, "")
            if not slide_path:
                continue
            slide_root = ET.fromstring(archive.read(slide_path))
            shapes: list[dict[str, Any]] = []
            for shape in slide_root.findall(".//p:sp", _P_NS):
                text = _shape_text(shape)
                placeholder_type = _shape_placeholder_type(shape)
                runs = _shape_runs(shape)
                if not text and not runs:
                    continue
                shapes.append(
                    {
                        "text": text,
                        "placeholder_type": placeholder_type,
                        "runs": runs,
                    }
                )

            title = ""
            for shape in shapes:
                if shape["placeholder_type"] in _TITLE_PLACEHOLDERS and shape["text"]:
                    title = shape["text"].splitlines()[0].strip()
                    break
            if not title:
                for shape in shapes:
                    if shape["text"]:
                        title = shape["text"].splitlines()[0].strip()
                        break

            all_text = "\n".join(shape["text"] for shape in shapes if shape["text"])
            slides.append(
                {
                    "title": title,
                    "all_text": all_text,
                    "shapes": shapes,
                    "notes_text": _read_notes_text(archive, slide_path),
                    "slide_path": slide_path,
                }
            )
    return slides


class LibreOfficeImpressEvaluator(BaseEvaluator):
    """PASS if the saved PPTX matches slide-order, text, notes, and boldness expectations."""

    DEFAULT_REMOTE_PATH = "~/Downloads/impress_edit_title_template.pptx"

    @staticmethod
    def _save_before_eval_if_requested(controller: Any, params: Mapping[str, Any]) -> str | None:
        if not bool(params.get("save_before_eval")):
            return None
        if not hasattr(controller, "execute_action"):
            return "controller.execute_action is required when save_before_eval=true"
        try:
            controller.execute_action({"type": "hotkey", "keys": "cmd+s"}, [])
            time.sleep(1.0)
        except Exception as exc:
            return f"Failed to save Impress presentation before evaluation: {exc}"
        return None

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.get_file is required for PPTX evaluation")

        remote_path = str(params.get("remote_path") or self.DEFAULT_REMOTE_PATH).strip()
        expected_slide_titles = [str(item).strip() for item in (params.get("expected_slide_titles") or []) if str(item).strip()]
        forbidden_slide_titles = [str(item).strip() for item in (params.get("forbidden_slide_titles") or []) if str(item).strip()]
        slides_with_all_non_title_runs_bold = [
            str(item).strip() for item in (params.get("slides_with_all_non_title_runs_bold") or []) if str(item).strip()
        ]
        per_slide_required_text = {
            str(title).strip(): [str(piece).strip() for piece in (values if isinstance(values, list) else [values]) if str(piece).strip()]
            for title, values in dict(params.get("per_slide_required_text") or {}).items()
            if str(title).strip()
        }
        per_slide_forbidden_text = {
            str(title).strip(): [str(piece).strip() for piece in (values if isinstance(values, list) else [values]) if str(piece).strip()]
            for title, values in dict(params.get("per_slide_forbidden_text") or {}).items()
            if str(title).strip()
        }
        per_slide_required_notes = {
            str(title).strip(): [str(piece).strip() for piece in (values if isinstance(values, list) else [values]) if str(piece).strip()]
            for title, values in dict(params.get("per_slide_required_notes") or {}).items()
            if str(title).strip()
        }
        per_slide_required_bold_fragments = {
            str(title).strip(): [str(piece).strip() for piece in (values if isinstance(values, list) else [values]) if str(piece).strip()]
            for title, values in dict(params.get("per_slide_required_bold_fragments") or {}).items()
            if str(title).strip()
        }
        per_slide_required_plain_fragments = {
            str(title).strip(): [str(piece).strip() for piece in (values if isinstance(values, list) else [values]) if str(piece).strip()]
            for title, values in dict(params.get("per_slide_required_plain_fragments") or {}).items()
            if str(title).strip()
        }
        expected_slide_count_raw = params.get("expected_slide_count")
        expected_slide_count = int(expected_slide_count_raw) if expected_slide_count_raw not in (None, "") else None

        if not remote_path:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation requires remote_path")
        if not any([
            expected_slide_titles,
            forbidden_slide_titles,
            slides_with_all_non_title_runs_bold,
            per_slide_required_text,
            per_slide_forbidden_text,
            per_slide_required_notes,
            per_slide_required_bold_fragments,
            per_slide_required_plain_fragments,
            expected_slide_count is not None,
        ]):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation requires at least one slide, text, notes, or formatting check")

        save_error = self._save_before_eval_if_requested(controller, params)
        if save_error:
            return EvalResult(status=EvalStatus.FAIL, message=save_error, metadata={"remote_path": remote_path})

        try:
            doc_bytes = controller.get_file(remote_path)
        except Exception as exc:
            return EvalResult(status=EvalStatus.FAIL, message=f"Failed to fetch saved Impress presentation: {exc}", metadata={"remote_path": remote_path})

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
            slides = _read_presentation(doc_bytes)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Failed to parse saved PPTX: {exc}",
                metadata={"remote_path": remote_path, "local_copy": local_copy},
            )

        slide_titles = [slide["title"] for slide in slides]
        if expected_slide_count is not None and len(slides) != expected_slide_count:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Impress slide count mismatch: expected {expected_slide_count}, got {len(slides)}",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "slide_titles": slide_titles},
            )

        if expected_slide_titles and slide_titles != expected_slide_titles:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"Impress slide order mismatch: expected {expected_slide_titles}, got {slide_titles}",
                metadata={"remote_path": remote_path, "local_copy": local_copy, "slide_titles": slide_titles},
            )

        for forbidden_title in forbidden_slide_titles:
            if forbidden_title in slide_titles:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Impress forbidden slide title still present: '{forbidden_title}'",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "slide_titles": slide_titles},
                )

        slides_by_title = {slide["title"]: slide for slide in slides if slide["title"]}

        def require_slide(title: str) -> dict[str, Any] | None:
            slide = slides_by_title.get(title)
            if slide is None:
                return None
            return slide

        for title, required_fragments in per_slide_required_text.items():
            slide = require_slide(title)
            if slide is None:
                return EvalResult(status=EvalStatus.FAIL, message=f"Impress required slide missing: '{title}'", metadata={"remote_path": remote_path, "local_copy": local_copy, "slide_titles": slide_titles})
            haystack = str(slide.get("all_text") or "")
            haystack_lower = haystack.lower()
            missing = [fragment for fragment in required_fragments if fragment.lower() not in haystack_lower]
            if missing:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Impress slide '{title}' is missing text fragments: {missing}",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "slide": slide},
                )

        for title, forbidden_fragments in per_slide_forbidden_text.items():
            slide = require_slide(title)
            if slide is None:
                return EvalResult(status=EvalStatus.FAIL, message=f"Impress required slide missing: '{title}'", metadata={"remote_path": remote_path, "local_copy": local_copy, "slide_titles": slide_titles})
            haystack = str(slide.get("all_text") or "")
            haystack_lower = haystack.lower()
            present = [fragment for fragment in forbidden_fragments if fragment.lower() in haystack_lower]
            if present:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Impress slide '{title}' still contains forbidden text: {present}",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "slide": slide},
                )

        for title, required_fragments in per_slide_required_notes.items():
            slide = require_slide(title)
            if slide is None:
                return EvalResult(status=EvalStatus.FAIL, message=f"Impress required slide missing: '{title}'", metadata={"remote_path": remote_path, "local_copy": local_copy, "slide_titles": slide_titles})
            notes_text = str(slide.get("notes_text") or "")
            notes_lower = notes_text.lower()
            missing = [fragment for fragment in required_fragments if fragment.lower() not in notes_lower]
            if missing:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Impress slide '{title}' is missing notes text fragments: {missing}",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "slide": slide},
                )

        for title, required_fragments in per_slide_required_bold_fragments.items():
            slide = require_slide(title)
            if slide is None:
                return EvalResult(status=EvalStatus.FAIL, message=f"Impress required slide missing: '{title}'", metadata={"remote_path": remote_path, "local_copy": local_copy, "slide_titles": slide_titles})
            runs = [dict(run) for shape in slide.get("shapes") or [] for run in (shape.get("runs") or [])]
            missing = [
                fragment for fragment in required_fragments
                if not any(fragment.lower() in str(run.get("text") or "").lower() and bool(run.get("bold")) for run in runs)
            ]
            if missing:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Impress slide '{title}' is missing bold text fragments: {missing}",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "slide": slide},
                )

        for title, required_fragments in per_slide_required_plain_fragments.items():
            slide = require_slide(title)
            if slide is None:
                return EvalResult(status=EvalStatus.FAIL, message=f"Impress required slide missing: '{title}'", metadata={"remote_path": remote_path, "local_copy": local_copy, "slide_titles": slide_titles})
            runs = [dict(run) for shape in slide.get("shapes") or [] for run in (shape.get("runs") or [])]
            missing = [
                fragment for fragment in required_fragments
                if not any(fragment.lower() in str(run.get("text") or "").lower() and not bool(run.get("bold")) for run in runs)
            ]
            if missing:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Impress slide '{title}' is missing non-bold text fragments: {missing}",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "slide": slide},
                )

        for title in slides_with_all_non_title_runs_bold:
            slide = require_slide(title)
            if slide is None:
                return EvalResult(status=EvalStatus.FAIL, message=f"Impress required slide missing: '{title}'", metadata={"remote_path": remote_path, "local_copy": local_copy, "slide_titles": slide_titles})
            non_title_runs = [
                run
                for shape in slide.get("shapes") or []
                if str(shape.get("placeholder_type") or "") not in _TITLE_PLACEHOLDERS
                for run in (shape.get("runs") or [])
            ]
            if not non_title_runs or not all(bool(run.get("bold")) for run in non_title_runs):
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=f"Impress slide '{title}' does not have all non-title text bold",
                    metadata={"remote_path": remote_path, "local_copy": local_copy, "slide": slide},
                )

        return EvalResult(
            status=EvalStatus.PASS,
            message="Impress presentation matches expected slide structure and content",
            metadata={
                "remote_path": remote_path,
                "local_copy": local_copy,
                "slide_titles": slide_titles,
                "slide_count": len(slides),
            },
        )
