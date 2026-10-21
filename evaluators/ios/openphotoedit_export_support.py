"""Shared read-only checks for OpenPhotoEdit's named sample exports."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluators.cua_review.core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.cua_review.platforms.ios.containers import find_app_data_container


BUNDLE_ID = "com.killt.openphotoedit"
EXPORT_RELATIVE_PATH = Path("Documents") / "OpenPhotoEdit" / "Exports"


def validate_named_export(
    files: Sequence[tuple[str, str]],
    *,
    expected_filename: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Check this task's export while allowing prior tasks' named outputs."""
    matches = [(name, digest) for name, digest in files if name == expected_filename]
    checks = [
        {
            "label": "export.expected_filename",
            "passed": len(matches) == 1,
            "expected": expected_filename,
            "observed": [name for name, _ in matches],
        },
        {
            "label": "export.matches_source_sample",
            "passed": len(matches) == 1 and matches[0][1] == expected_sha256,
            "expected": expected_sha256,
            "observed": None if len(matches) != 1 else matches[0][1],
        },
    ]
    failures = [check["label"] for check in checks if not check["passed"]]
    return {
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": failures,
        "observed_export_files": [name for name, _ in files],
    }


class OpenPhotoEditNamedExportEvaluator(BaseEvaluator):
    """Base class whose concrete subclasses bind one sample and output name."""

    TASK_ID = ""
    SOURCE_SAMPLE = ""
    EXPORT_FILENAME = ""
    SOURCE_SHA256 = ""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        expected_params = {
            "bundle_id": BUNDLE_ID,
            "export_filename": self.EXPORT_FILENAME,
            "source_sample": self.SOURCE_SAMPLE,
            "source_sample_sha256": self.SOURCE_SHA256,
        }
        binding_failures = [
            {"field": key, "expected": value, "observed": params.get(key)}
            for key, value in expected_params.items()
            if params.get(key) != value
        ]
        if binding_failures:
            return EvalResult(
                EvalStatus.ERROR,
                "OpenPhotoEdit task binding mismatch",
                {"status": "ERROR", "task_id": self.TASK_ID, "failures": binding_failures},
            )

        udid = str(params.get("udid") or "").strip()
        if not udid:
            return EvalResult(
                EvalStatus.ERROR,
                "OpenPhotoEdit simulator binding is missing",
                {"status": "ERROR", "task_id": self.TASK_ID, "failures": ["missing udid"]},
            )
        try:
            data_container = find_app_data_container(udid, BUNDLE_ID)
            export_dir = data_container / EXPORT_RELATIVE_PATH
            paths = sorted(path for path in export_dir.iterdir() if path.is_file()) if export_dir.is_dir() else []
            files = [(path.name, hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths]
        except Exception as exc:
            return EvalResult(
                EvalStatus.ERROR,
                f"OpenPhotoEdit export inspection failed: {type(exc).__name__}: {exc}",
                {"status": "ERROR", "task_id": self.TASK_ID, "exception": type(exc).__name__, "message": str(exc)},
            )

        evidence = validate_named_export(
            files,
            expected_filename=self.EXPORT_FILENAME,
            expected_sha256=self.SOURCE_SHA256,
        )
        evidence.update(
            {
                "task_id": self.TASK_ID,
                "source_sample": self.SOURCE_SAMPLE,
                "source_sample_sha256": self.SOURCE_SHA256,
                "export_directory": str(export_dir),
            }
        )
        passed = evidence["status"] == "PASS"
        return EvalResult(
            EvalStatus.PASS if passed else EvalStatus.FAIL,
            "OpenPhotoEdit sample export matches its named source" if passed else "OpenPhotoEdit export is missing, misnamed, or differs from its source sample",
            evidence,
        )
