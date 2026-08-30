"""Generic external-storage truth evaluator for Android benchmark tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.android.bench_storage_support import list_directory_entries, path_status


class ExternalStoragePathStateEvaluator(BaseEvaluator):
    """Validate expected/forbidden file and directory paths on shared storage."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.execute_adb is required for filesystem evaluation",
            )

        expected_paths = list(params.get("expected_paths") or [])
        forbidden_paths = list(params.get("forbidden_paths") or [])
        exact_directory_entries = list(params.get("exact_directory_entries") or [])
        if not expected_paths and not forbidden_paths and not exact_directory_entries:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.expected_paths, forbidden_paths, or exact_directory_entries is required",
            )

        observed: dict[str, str] = {}
        missing: list[dict[str, Any]] = []
        unexpected: list[dict[str, Any]] = []
        directory_mismatches: list[dict[str, Any]] = []

        for spec in expected_paths:
            spec_map = dict(spec or {}) if isinstance(spec, Mapping) else {"path": spec}
            remote_path = str(spec_map.get("path") or "").strip()
            expected_kind = str(spec_map.get("type") or "any").strip().lower() or "any"
            if not remote_path:
                continue
            actual = path_status(controller, remote_path)
            observed[remote_path] = actual
            if actual == "missing":
                missing.append({"path": remote_path, "expected": expected_kind, "actual": actual})
                continue
            if expected_kind != "any" and actual != expected_kind:
                missing.append({"path": remote_path, "expected": expected_kind, "actual": actual})

        for spec in forbidden_paths:
            spec_map = dict(spec or {}) if isinstance(spec, Mapping) else {"path": spec}
            remote_path = str(spec_map.get("path") or "").strip()
            forbidden_kind = str(spec_map.get("type") or "any").strip().lower() or "any"
            if not remote_path:
                continue
            actual = path_status(controller, remote_path)
            observed[remote_path] = actual
            if actual == "missing":
                continue
            if forbidden_kind == "any" or actual == forbidden_kind:
                unexpected.append({"path": remote_path, "forbidden": forbidden_kind, "actual": actual})

        for spec in exact_directory_entries:
            spec_map = dict(spec or {}) if isinstance(spec, Mapping) else {"path": spec}
            remote_path = str(spec_map.get("path") or "").strip()
            if not remote_path:
                continue
            actual_status = path_status(controller, remote_path)
            observed[remote_path] = actual_status
            expected_entries = sorted(str(entry).strip() for entry in (spec_map.get("entries") or []) if str(entry).strip())
            if actual_status != "dir":
                directory_mismatches.append(
                    {
                        "path": remote_path,
                        "expected_entries": expected_entries,
                        "actual_status": actual_status,
                        "actual_entries": None,
                    }
                )
                continue
            actual_entries = list_directory_entries(controller, remote_path)
            if actual_entries != expected_entries:
                directory_mismatches.append(
                    {
                        "path": remote_path,
                        "expected_entries": expected_entries,
                        "actual_status": actual_status,
                        "actual_entries": actual_entries,
                    }
                )

        if missing or unexpected or directory_mismatches:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="External storage state did not match the expected benchmark outcome",
                metadata={
                    "missing": missing,
                    "unexpected": unexpected,
                    "directory_mismatches": directory_mismatches,
                    "observed": observed,
                },
            )

        return EvalResult(
            status=EvalStatus.PASS,
            message="External storage state matches the expected benchmark outcome",
            metadata={"observed": observed},
        )
