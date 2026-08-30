"""PPTX comparison evaluator for Linux office tasks."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux.office_path_resolve import resolve_office_file_pair, unlink_if_temp
from platforms.linux.office_metrics.slides import compare_pptx_files


class PptxCompareEvaluator(BaseEvaluator):
    """Compare generated pptx against expected pptx using OSWorld-style checks."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        controller = context.get("controller")
        actual = str(params.get("actual_path") or "").strip()
        expected = str(params.get("expected_path") or "").strip()
        if not actual or not expected:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.actual_path and expected_path are required",
            )

        options = params.get("options") or {}
        if not isinstance(options, Mapping):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.options must be an object")
        text_artifacts = params.get("text_artifacts") or []
        if text_artifacts and not isinstance(text_artifacts, list):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.text_artifacts must be a list")
        image_count_rules = params.get("image_count_rules") or []
        if image_count_rules and not isinstance(image_count_rules, list):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.image_count_rules must be a list")
        picture_alt_rules = params.get("picture_alt_rules") or []
        if picture_alt_rules and not isinstance(picture_alt_rules, list):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.picture_alt_rules must be a list")

        try:
            actual_path, expected_path, actual_tmp, expected_tmp = resolve_office_file_pair(
                actual,
                expected,
                controller,
                actual_prefix="helloworld_pptx_actual_",
                expected_prefix="helloworld_pptx_expected_",
                actual_suffix=".pptx",
                expected_suffix=".pptx",
            )
        except FileNotFoundError as exc:
            return EvalResult(status=EvalStatus.ERROR, message=str(exc))
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"failed to resolve PPTX paths for comparison: {exc}",
            )

        meta: dict[str, Any] = {
            "actual_path": str(actual_path),
            "expected_path": str(expected_path),
            "actual_temp": actual_tmp,
            "expected_temp": expected_tmp,
        }
        try:
            score = compare_pptx_files(str(actual_path), str(expected_path), **dict(options))
        except Exception as exc:
            meta["error"] = repr(exc)
            unlink_if_temp(actual_path, actual_tmp)
            unlink_if_temp(expected_path, expected_tmp)
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"PPTX comparison raised: {exc}",
                metadata=meta,
            )

        meta["score"] = float(score)
        if float(score) < 1.0:
            unlink_if_temp(actual_path, actual_tmp)
            unlink_if_temp(expected_path, expected_tmp)
            return EvalResult(status=EvalStatus.FAIL, message="PPTX comparison failed", metadata=meta)

        if image_count_rules:
            try:
                image_meta = self._validate_image_counts(actual_path, image_count_rules)
            except AssertionError as exc:
                meta["image_count_rules"] = getattr(exc, "metadata", None)
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=meta)
            except Exception as exc:
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.ERROR, message=f"image count validation failed: {exc}", metadata=meta)
            meta["image_count_rules"] = image_meta

        if picture_alt_rules:
            try:
                alt_meta = self._validate_picture_alt_text(actual_path, picture_alt_rules)
            except AssertionError as exc:
                meta["picture_alt_rules"] = getattr(exc, "metadata", None)
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=meta)
            except Exception as exc:
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.ERROR, message=f"picture alt-text validation failed: {exc}", metadata=meta)
            meta["picture_alt_rules"] = alt_meta

        if text_artifacts:
            if controller is None or not hasattr(controller, "run_bash_script"):
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required for text_artifacts")
            try:
                artifact_meta = self._validate_text_artifacts(controller, text_artifacts)
            except AssertionError as exc:
                meta["text_artifacts"] = getattr(exc, "metadata", None)
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=meta)
            except Exception as exc:
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.ERROR, message=f"text artifact validation failed: {exc}", metadata=meta)
            meta["text_artifacts"] = artifact_meta

        unlink_if_temp(actual_path, actual_tmp)
        unlink_if_temp(expected_path, expected_tmp)
        return EvalResult(status=EvalStatus.PASS, message="PPTX comparison passed", metadata=meta)

    @staticmethod
    def _validate_image_counts(pptx_path: Any, rules: list[Any]) -> dict[str, Any]:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        presentation = Presentation(str(pptx_path))
        observed = []
        for slide_index, slide in enumerate(presentation.slides, start=1):
            count = sum(1 for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
            observed.append({"slide_index": slide_index, "picture_count": count})
        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            slide_index = int(rule.get("slide_index") or 0)
            expected_count = int(rule.get("picture_count") or 0)
            actual = next((item for item in observed if item["slide_index"] == slide_index), None)
            assert actual is not None, f"missing slide {slide_index} for image count validation"
            assert actual["picture_count"] == expected_count, (
                f"expected slide {slide_index} to contain {expected_count} pictures, "
                f"got {actual['picture_count']}"
            )
        return {"slides": observed}

    @staticmethod
    def _validate_picture_alt_text(pptx_path: Any, rules: list[Any]) -> dict[str, Any]:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        presentation = Presentation(str(pptx_path))
        observed: list[dict[str, Any]] = []
        by_slide: dict[int, list[dict[str, Any]]] = {}
        for slide_index, slide in enumerate(presentation.slides, start=1):
            pictures = []
            for picture_index, shape in enumerate(
                [item for item in slide.shapes if item.shape_type == MSO_SHAPE_TYPE.PICTURE],
                start=1,
            ):
                c_nv_pr = shape._element.nvPicPr.cNvPr
                entry = {
                    "slide_index": slide_index,
                    "picture_index": picture_index,
                    "name": c_nv_pr.get("name") or "",
                    "descr": c_nv_pr.get("descr") or "",
                }
                pictures.append(entry)
                observed.append(entry)
            by_slide[slide_index] = pictures

        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            slide_index = int(rule.get("slide_index") or 0)
            picture_index = int(rule.get("picture_index") or 1)
            expected_descr = str(rule.get("descr") or "")
            expected_name = rule.get("name")
            pictures = by_slide.get(slide_index) or []
            assert picture_index <= len(pictures), (
                f"missing picture {picture_index} on slide {slide_index} "
                f"for alt-text validation"
            )
            actual = pictures[picture_index - 1]
            assert actual["descr"] == expected_descr, (
                f"expected slide {slide_index} picture {picture_index} alt text "
                f"{expected_descr!r}, got {actual['descr']!r}"
            )
            if expected_name is not None:
                assert actual["name"] == str(expected_name), (
                    f"expected slide {slide_index} picture {picture_index} name "
                    f"{expected_name!r}, got {actual['name']!r}"
                )
        return {"pictures": observed}

    @staticmethod
    def _validate_text_artifacts(controller: Any, artifacts: list[Any]) -> dict[str, Any]:
        script = f"""python3 - <<'PY'
import json
from pathlib import Path

artifacts = json.loads({json.dumps(json.dumps(artifacts, ensure_ascii=False), ensure_ascii=False)})
results = []
for item in artifacts:
    path = Path(str(item.get("path") or ""))
    entry = {{"path": str(path), "exists": path.exists()}}
    if path.exists():
        entry["content"] = path.read_text(encoding="utf-8")
    results.append(entry)
print(json.dumps({{"results": results}}, ensure_ascii=False))
PY"""
        result = controller.run_bash_script(script, timeout=30)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()
        if returncode != 0:
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        payload = json.loads(output)
        by_path = {str(item.get("path") or ""): dict(item) for item in payload.get("results") or []}
        for item in artifacts:
            if not isinstance(item, Mapping):
                continue
            path = str(item.get("path") or "")
            actual = by_path.get(path)
            assert actual is not None, f"missing text artifact payload for {path}"
            assert bool(actual.get("exists")), f"expected text artifact to exist: {path}"
            content = str(actual.get("content") or "")
            if "equals" in item:
                expected = str(item.get("equals") or "")
                assert content == expected, f"text artifact mismatch for {path}"
            if "contains" in item:
                needle = str(item.get("contains") or "")
                assert needle in content, f"expected text artifact {path} to contain {needle!r}"
        return payload
