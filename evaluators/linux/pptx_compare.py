"""PPTX comparison evaluator for Linux office tasks."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import PurePosixPath
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux.office_path_resolve import resolve_office_file_pair, resolve_office_file_path, unlink_if_temp
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
        picture_box_rules = params.get("picture_box_rules") or []
        if picture_box_rules and not isinstance(picture_box_rules, list):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.picture_box_rules must be a list")
        picture_image_rules = params.get("picture_image_rules") or []
        if picture_image_rules and not isinstance(picture_image_rules, list):
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.picture_image_rules must be a list")

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

        if picture_box_rules:
            try:
                box_meta = self._validate_picture_boxes(actual_path, picture_box_rules)
            except AssertionError as exc:
                meta["picture_box_rules"] = getattr(exc, "metadata", None)
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=meta)
            except Exception as exc:
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.ERROR, message=f"picture box validation failed: {exc}", metadata=meta)
            meta["picture_box_rules"] = box_meta

        if picture_image_rules:
            try:
                image_meta = self._validate_picture_images(actual_path, picture_image_rules, controller)
            except AssertionError as exc:
                meta["picture_image_rules"] = getattr(exc, "metadata", None)
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=meta)
            except Exception as exc:
                unlink_if_temp(actual_path, actual_tmp)
                unlink_if_temp(expected_path, expected_tmp)
                return EvalResult(status=EvalStatus.ERROR, message=f"picture image validation failed: {exc}", metadata=meta)
            meta["picture_image_rules"] = image_meta

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
    def _validate_picture_boxes(pptx_path: Any, rules: list[Any]) -> dict[str, Any]:
        """Require pictures on several slides to share one box (left, top, width, height).

        Each rule names a ``reference_slide`` and the ``slides`` whose picture number
        ``picture_index`` (1-based, default 1) must sit in the reference picture's box, within
        ``tolerance`` (a fraction of the slide width for left/width and of the slide height for
        top/height, default 0.005). The reference picture must have a positive size. This grades
        "the same placement and fitted size" across slides without a hidden target geometry.
        """
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        presentation = Presentation(str(pptx_path))
        slide_width = int(presentation.slide_width or 0)
        slide_height = int(presentation.slide_height or 0)
        by_slide: dict[int, list[dict[str, int]]] = {}
        for slide_index, slide in enumerate(presentation.slides, start=1):
            by_slide[slide_index] = [
                {
                    "left": int(shape.left or 0),
                    "top": int(shape.top or 0),
                    "width": int(shape.width or 0),
                    "height": int(shape.height or 0),
                }
                for shape in slide.shapes
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
            ]
        observed = {"slide_width": slide_width, "slide_height": slide_height, "pictures": by_slide}

        def picture(slide_index: int, picture_index: int) -> dict[str, int]:
            pictures = by_slide.get(slide_index) or []
            if picture_index > len(pictures):
                error = AssertionError(f"missing picture {picture_index} on slide {slide_index} for box validation")
                error.metadata = observed  # type: ignore[attr-defined]
                raise error
            return pictures[picture_index - 1]

        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            reference_slide = int(rule.get("reference_slide") or 1)
            picture_index = int(rule.get("picture_index") or 1)
            tolerance = float(rule.get("tolerance", 0.005))
            reference = picture(reference_slide, picture_index)
            if reference["width"] <= 0 or reference["height"] <= 0:
                error = AssertionError(f"slide {reference_slide} picture {picture_index} has no size")
                error.metadata = observed  # type: ignore[attr-defined]
                raise error
            limits = {
                "left": tolerance * slide_width,
                "width": tolerance * slide_width,
                "top": tolerance * slide_height,
                "height": tolerance * slide_height,
            }
            for slide_index in rule.get("slides") or []:
                box = picture(int(slide_index), picture_index)
                off = [key for key, limit in limits.items() if abs(box[key] - reference[key]) > limit]
                if off:
                    error = AssertionError(
                        f"slide {int(slide_index)} picture {picture_index} {'/'.join(off)} differs from "
                        f"slide {reference_slide}: {box} vs {reference}"
                    )
                    error.metadata = observed  # type: ignore[attr-defined]
                    raise error
        return observed

    # Mean absolute per-channel difference (0-255) between 96x72 RGB thumbnails. Re-encoding the
    # six kiosk PNGs as JPEG stays under 2 at quality 60 and half size and under 3 at quality 30;
    # the closest pair of those images (pic2/pic3, same red template) is 5.5 apart, and a picture
    # must also be closer to its own source than to any other source in the rules.
    PICTURE_MAX_MEAN_DIFF = 4.0
    _THUMB_SIZE = (96, 72)

    @classmethod
    def _thumbnail(cls, data: bytes):
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        image.load()
        if image.mode in ("RGBA", "LA", "P", "PA"):
            image = image.convert("RGBA")
            backdrop = Image.new("RGBA", image.size, (255, 255, 255, 255))
            backdrop.alpha_composite(image)
            image = backdrop
        return image.convert("RGB").resize(cls._THUMB_SIZE, Image.BILINEAR)

    @staticmethod
    def _mean_diff(left: Any, right: Any) -> float:
        from PIL import ImageChops, ImageStat

        return float(sum(ImageStat.Stat(ImageChops.difference(left, right)).mean) / 3.0)

    @classmethod
    def _validate_picture_images(cls, pptx_path: Any, rules: list[Any], controller: Any) -> dict[str, Any]:
        """Require picture ``picture_index`` (1-based) on ``slide_index`` to show ``source_path``.

        Opt-in per task. The embedded media is accepted when its bytes equal the source file, or,
        if the office suite re-encoded it, when its decoded pixels are within ``max_mean_diff``
        (default ``PICTURE_MAX_MEAN_DIFF``) of the source and closer to it than to any other
        source named in the rules. A picture that is only linked (no embedded media) is accepted
        when the link target has the source's file name. Source paths under /tmp or /home/user are
        read from the guest.
        """
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        from pptx.opc.constants import RELATIONSHIP_TYPE as RT
        from pptx.oxml.ns import qn

        sources: dict[str, bytes] = {}
        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            source = str(rule.get("source_path") or "").strip()
            if not source:
                raise ValueError("picture_image_rules entries need source_path")
            if source in sources:
                continue
            local, is_temp = resolve_office_file_path(
                source, controller, temp_prefix="helloworld_pptx_source_", default_suffix=PurePosixPath(source).suffix
            )
            try:
                sources[source] = local.read_bytes()
            finally:
                unlink_if_temp(local, is_temp)
        source_hashes = {path: hashlib.sha256(data).hexdigest() for path, data in sources.items()}
        thumbnails: dict[str, Any] = {}

        def source_thumbnail(path: str) -> Any:
            if path not in thumbnails:
                thumbnails[path] = cls._thumbnail(sources[path])
            return thumbnails[path]

        presentation = Presentation(str(pptx_path))
        by_slide = {
            index: [shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE]
            for index, slide in enumerate(presentation.slides, start=1)
        }
        observed: list[dict[str, Any]] = []

        def fail(message: str) -> None:
            error = AssertionError(message)
            error.metadata = {"pictures": observed}  # type: ignore[attr-defined]
            raise error

        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            slide_index = int(rule.get("slide_index") or 0)
            picture_index = int(rule.get("picture_index") or 1)
            source = str(rule.get("source_path") or "").strip()
            limit = float(rule.get("max_mean_diff", cls.PICTURE_MAX_MEAN_DIFF))
            entry: dict[str, Any] = {
                "slide_index": slide_index,
                "picture_index": picture_index,
                "source_path": source,
                "match": None,
            }
            observed.append(entry)
            pictures = by_slide.get(slide_index) or []
            if picture_index > len(pictures):
                fail(f"missing picture {picture_index} on slide {slide_index} for image validation")
            shape = pictures[picture_index - 1]
            blip = shape._element.blipFill.blip if shape._element.blipFill is not None else None
            embed_rid = blip.rEmbed if blip is not None else None
            if not embed_rid:
                link_rid = blip.get(qn("r:link")) if blip is not None else None
                target = ""
                if link_rid and link_rid in shape.part.rels:
                    relation = shape.part.rels[link_rid]
                    if relation.reltype == RT.IMAGE and relation.is_external:
                        target = str(relation.target_ref)
                entry["linked_target"] = target
                if target and PurePosixPath(target.replace("\\", "/")).name == PurePosixPath(source).name:
                    entry["match"] = "linked"
                    continue
                fail(f"slide {slide_index} picture {picture_index} has no embedded image matching {source}")
            blob = shape.image.blob
            digest = hashlib.sha256(blob).hexdigest()
            entry["sha256"] = digest
            if digest == source_hashes[source]:
                entry["match"] = "exact"
                continue
            try:
                picture_thumbnail = cls._thumbnail(blob)
            except Exception as exc:  # e.g. a vector or unreadable blob
                entry["decode_error"] = repr(exc)
                fail(f"slide {slide_index} picture {picture_index} is not {source} (cannot decode embedded image)")
            distances = {path: cls._mean_diff(picture_thumbnail, source_thumbnail(path)) for path in sources}
            entry["mean_diff"] = {path: round(value, 3) for path, value in distances.items()}
            nearest = min(distances, key=distances.get)
            others = [value for path, value in distances.items() if path != source]
            if distances[source] <= limit and (not others or distances[source] < min(others)):
                entry["match"] = "pixels"
                continue
            fail(
                f"slide {slide_index} picture {picture_index} is not {source}: mean pixel difference "
                f"{distances[source]:.2f} (limit {limit}), closest source {nearest}"
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
