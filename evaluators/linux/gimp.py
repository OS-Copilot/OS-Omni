"""File-based evaluator for GIMP image editing tasks on Linux."""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class GimpFileEvaluator(BaseEvaluator):
    """Validate an output image file produced by the benchmark agent through GIMP."""

    DEFAULT_TIMEOUT = 20

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "run_bash_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_bash_script is required")

        params = dict(context.get("params") or {})
        output_path = str(params.get("output_path") or "").strip()
        if not output_path:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.output_path is required")

        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)

        expectations: dict[str, Any] = {}
        if params.get("expected_width") is not None:
            expectations["width"] = int(params["expected_width"])
        if params.get("expected_height") is not None:
            expectations["height"] = int(params["expected_height"])
        if params.get("expected_mode") is not None:
            expectations["mode"] = str(params["expected_mode"])
        if params.get("expected_format") is not None:
            expectations["format"] = str(params["expected_format"]).upper()

        script = f"""python3 - <<'PY'
import json
import sys

try:
    from PIL import Image
except ImportError:
    print(json.dumps({{"error": "pillow_missing"}}))
    sys.exit(0)

path = {json.dumps(output_path, ensure_ascii=False)}
try:
    img = Image.open(path)
    fmt = img.format
    img.verify()
    img = Image.open(path)
    result = {{
        "width": img.width,
        "height": img.height,
        "mode": img.mode,
        "format": fmt or "UNKNOWN",
    }}
    print(json.dumps(result))
except FileNotFoundError:
    print(json.dumps({{"error": "file_not_found", "path": path}}))
except Exception as exc:
    print(json.dumps({{"error": str(exc)}}))
PY"""

        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        output = str(result.get("output", "")).strip()

        if returncode != 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=output or f"guest command failed with exit code {returncode}",
            )

        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"GIMP evaluator returned invalid JSON: {exc}: {output}",
            )

        error = str(payload.get("error") or "")
        if error == "file_not_found":
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"output file not found: {output_path}",
                metadata=payload,
            )
        if error == "pillow_missing":
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Pillow is not installed on the guest; run: pip3 install Pillow",
                metadata=payload,
            )
        if error:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"GIMP evaluator error: {error}",
                metadata=payload,
            )

        if "width" in expectations and payload.get("width") != expectations["width"]:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"expected image width {expectations['width']}, got {payload.get('width')}",
                metadata=payload,
            )
        if "height" in expectations and payload.get("height") != expectations["height"]:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"expected image height {expectations['height']}, got {payload.get('height')}",
                metadata=payload,
            )
        if "mode" in expectations and payload.get("mode") != expectations["mode"]:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"expected image mode {expectations['mode']!r}, got {payload.get('mode')!r}",
                metadata=payload,
            )
        if "format" in expectations and str(payload.get("format") or "").upper() != expectations["format"]:
            return EvalResult(
                status=EvalStatus.FAIL,
                message=f"expected image format {expectations['format']!r}, got {str(payload.get('format') or '').upper()!r}",
                metadata=payload,
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="GIMP file evaluation passed",
            metadata=payload,
        )
