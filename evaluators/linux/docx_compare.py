"""DOCX comparison evaluator for Linux office tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux.office_path_resolve import resolve_office_file_pair, unlink_if_temp
from platforms.linux.office_metrics.docx_compare import compare_docx_files


class DocxCompareEvaluator(BaseEvaluator):
    """Compare generated docx against expected docx (OSWorld-style structural check)."""

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
                message=f"failed to resolve DOCX paths for comparison: {exc}",
            )

        meta: dict[str, Any] = {
            "actual_path": str(actual_path),
            "expected_path": str(expected_path),
            "actual_temp": actual_tmp,
            "expected_temp": expected_tmp,
        }
        try:
            score = compare_docx_files(str(actual_path), str(expected_path), **dict(options))
        except Exception as exc:
            meta["error"] = repr(exc)
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"DOCX comparison raised: {exc}",
                metadata=meta,
            )
        finally:
            unlink_if_temp(actual_path, actual_tmp)
            unlink_if_temp(expected_path, expected_tmp)

        meta["score"] = float(score)
        if float(score) >= 1.0:
            return EvalResult(status=EvalStatus.PASS, message="DOCX comparison passed", metadata=meta)
        return EvalResult(status=EvalStatus.FAIL, message="DOCX comparison failed", metadata=meta)
