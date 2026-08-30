"""Evaluate macOS GIMP image export tasks."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageChops

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


def _resolve_local_path(raw_path: str, *, task: Any, run_dir: Any) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()

    task_source = getattr(task, "source_file", None)
    if task_source:
        candidate = (Path(task_source).expanduser().resolve().parent / path).resolve()
        if candidate.exists():
            return candidate

    if run_dir is not None:
        candidate = (Path(run_dir) / path).resolve()
        if candidate.exists():
            return candidate

    return (Path.cwd() / path).resolve()


class GimpFileEvaluator(BaseEvaluator):
    """Validate exported GIMP image files with optional exact pixel comparison."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        task = context.get("task")
        run_dir = context.get("run_dir")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.get_file is required")

        actual_path = str(params.get("actual_path") or params.get("output_path") or "").strip()
        if not actual_path:
            return EvalResult(status=EvalStatus.ERROR, message="GIMP evaluation requires actual_path")

        expected_image_raw = str(params.get("expected_image_path") or "").strip()
        expected_width = params.get("expected_width")
        expected_height = params.get("expected_height")
        expected_mode = str(params.get("expected_mode") or "").strip() or None
        expected_format = str(params.get("expected_format") or "").strip().upper() or None
        pixel_tolerance = int(params.get("pixel_tolerance", 0) or 0)

        try:
            actual_bytes = controller.get_file(actual_path)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"failed to fetch actual image file: {exc}",
                metadata={"actual_path": actual_path},
            )

        try:
            actual_image = Image.open(BytesIO(actual_bytes))
            actual_format = str(actual_image.format or "UNKNOWN").upper()
            actual_image.load()
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"failed to parse actual image: {exc}")

        metadata = {
            "actual_path": actual_path,
            "actual_width": actual_image.width,
            "actual_height": actual_image.height,
            "actual_mode": actual_image.mode,
            "actual_format": actual_format,
        }

        if expected_width is not None and actual_image.width != int(expected_width):
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"expected image width {int(expected_width)}, got {actual_image.width}",
                metadata=metadata,
            )
        if expected_height is not None and actual_image.height != int(expected_height):
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"expected image height {int(expected_height)}, got {actual_image.height}",
                metadata=metadata,
            )
        if expected_mode is not None and actual_image.mode != expected_mode:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"expected image mode {expected_mode!r}, got {actual_image.mode!r}",
                metadata=metadata,
            )
        if expected_format is not None and actual_format != expected_format:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"expected image format {expected_format!r}, got {actual_format!r}",
                metadata=metadata,
            )

        if expected_image_raw:
            expected_path = _resolve_local_path(expected_image_raw, task=task, run_dir=run_dir)
            if not expected_path.exists() or not expected_path.is_file():
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"expected image fixture missing: {expected_path}",
                    metadata=metadata,
                )
            try:
                expected_image = Image.open(expected_path)
                expected_format_observed = str(expected_image.format or expected_format or "UNKNOWN").upper()
                expected_image.load()
            except Exception as exc:
                return EvalResult(status=EvalStatus.ERROR, message=f"failed to parse expected image: {exc}")

            metadata.update(
                {
                    "expected_image_path": str(expected_path),
                    "expected_width": expected_image.width,
                    "expected_height": expected_image.height,
                    "expected_mode": expected_image.mode,
                    "expected_format": expected_format_observed,
                }
            )

            if actual_image.size != expected_image.size:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=(
                        "expected image size "
                        f"{expected_image.width}x{expected_image.height}, got {actual_image.width}x{actual_image.height}"
                    ),
                    metadata=metadata,
                )

            actual_rgba = actual_image.convert("RGBA")
            expected_rgba = expected_image.convert("RGBA")
            diff = ImageChops.difference(actual_rgba, expected_rgba)
            extrema = diff.getextrema()
            max_channel_delta = max(channel_max for _, channel_max in extrema)
            channel_boxes = [channel.getbbox() for channel in diff.split()]
            non_empty_boxes = [box for box in channel_boxes if box is not None]
            bbox = None
            if non_empty_boxes:
                bbox = (
                    min(box[0] for box in non_empty_boxes),
                    min(box[1] for box in non_empty_boxes),
                    max(box[2] for box in non_empty_boxes),
                    max(box[3] for box in non_empty_boxes),
                )
            if bbox is not None:
                metadata.update({"difference_bbox": bbox, "max_channel_delta": max_channel_delta})
            if max_channel_delta > pixel_tolerance:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=(
                        "exported image does not match expected pixels "
                        f"(bbox={bbox}, max_channel_delta={max_channel_delta}, tolerance={pixel_tolerance})"
                    ),
                    metadata=metadata,
                )

        return EvalResult(
            status=EvalStatus.PASS,
            message="GIMP file evaluation passed",
            metadata=metadata,
        )
