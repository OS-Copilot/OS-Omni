"""Additional evaluators for Android Oinkoin benchmark tasks."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, Tuple

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.android.oinkoin_support import DEFAULT_APP_PACKAGE, default_database_path, read_database_state


Validator = Callable[[Dict[str, List[Dict[str, Any]]], Dict[str, Any], float], Tuple[bool, Dict[str, Any]]]


class _BaseOinkoinEvaluator(BaseEvaluator):
    DEFAULT_TIMEOUT_SECONDS = 10.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0
    DEFAULT_VALUE_TOLERANCE = 1e-3

    def _evaluate_with_validator(
        self,
        context: Mapping[str, Any],
        *,
        validator: Validator,
        success_message: str,
        fail_message: str,
    ) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.execute_adb is required for Oinkoin evaluation",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        database_path = str(
            params.get("database_path") or default_database_path(app_package)
        ).strip()
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )
        value_tolerance = float(params.get("value_tolerance", self.DEFAULT_VALUE_TOLERANCE) or 0.0)

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_state: dict[str, list[dict[str, Any]]] = {"records": [], "categories": []}
        last_details: dict[str, Any] = {}

        while True:
            attempts += 1
            try:
                last_state = read_database_state(
                    controller,
                    app_package=app_package,
                    database_path=database_path,
                )
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to inspect Oinkoin database: {type(exc).__name__}: {exc}",
                    metadata={
                        "app_package": app_package,
                        "database_path": database_path,
                        "attempts": attempts,
                    },
                )

            matched, details = validator(last_state, params, value_tolerance)
            if matched:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message=success_message,
                    metadata={
                        "attempts": attempts,
                        "database_path": database_path,
                        **details,
                    },
                )

            last_details = details
            if time.time() >= deadline:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=fail_message,
                    metadata={
                        "attempts": attempts,
                        "database_path": database_path,
                        "validation": last_details,
                        "rows_seen": last_state.get("records", [])[:5],
                        "categories_seen": last_state.get("categories", [])[:8],
                    },
                )
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

    @staticmethod
    def _matching_records(
        records: list[dict[str, Any]],
        *,
        title: str,
        note: str,
        category_name: str,
        category_type: int,
        expected_value: float,
        value_tolerance: float,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for row in records:
            if str(row.get("title") or "").strip() != title:
                continue
            if str(row.get("description") or "").strip() != note:
                continue
            if str(row.get("category_name") or "").strip() != category_name:
                continue
            row_category_type = row.get("category_type")
            if int(-1 if row_category_type is None else row_category_type) != category_type:
                continue
            actual_value = float(row.get("value") or 0.0)
            if abs(actual_value - expected_value) > value_tolerance:
                continue
            matches.append(row)
        return matches


class OinkoinCreateIncomeEvaluator(_BaseOinkoinEvaluator):
    DEFAULT_CATEGORY_TYPE = 1

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        title = str(params.get("title") or "").strip()
        note = str(params.get("note") or "").strip()
        category_name = str(params.get("category_name") or "").strip()
        amount = float(params.get("amount") or 0.0)
        category_type = int(params.get("category_type", self.DEFAULT_CATEGORY_TYPE))

        if not title or not note or not category_name or amount <= 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params title, note, category_name, and positive amount are required",
            )

        expected_value = abs(amount)

        def _validator(
            state: dict[str, list[dict[str, Any]]],
            _params: dict[str, Any],
            value_tolerance: float,
        ) -> tuple[bool, dict[str, Any]]:
            matches = self._matching_records(
                state.get("records", []),
                title=title,
                note=note,
                category_name=category_name,
                category_type=category_type,
                expected_value=expected_value,
                value_tolerance=value_tolerance,
            )
            return bool(matches), {
                "expected": {
                    "title": title,
                    "note": note,
                    "category_name": category_name,
                    "category_type": category_type,
                    "expected_value": expected_value,
                },
                "matched_row": matches[0] if matches else None,
                "matching_count": len(matches),
            }

        return self._evaluate_with_validator(
            context,
            validator=_validator,
            success_message="Expected Oinkoin income record was persisted",
            fail_message="Expected Oinkoin income record was not found in the local database",
        )


class OinkoinEditExpenseEvaluator(_BaseOinkoinEvaluator):
    DEFAULT_CATEGORY_TYPE = 0
    DEFAULT_OLD_AMOUNT = 12.34
    DEFAULT_OLD_TITLE = "Coffee"
    DEFAULT_OLD_NOTE = "old_note"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        new_title = str(params.get("new_title") or "").strip()
        new_note = str(params.get("new_note") or "").strip()
        category_name = str(params.get("category_name") or "").strip()
        new_amount = float(params.get("new_amount") or 0.0)
        category_type = int(params.get("category_type", self.DEFAULT_CATEGORY_TYPE))
        old_title = str(params.get("old_title") or self.DEFAULT_OLD_TITLE).strip()
        old_note = str(params.get("old_note") or self.DEFAULT_OLD_NOTE).strip()
        old_amount = float(params.get("old_amount") or self.DEFAULT_OLD_AMOUNT)

        if not new_title or not new_note or not category_name or new_amount <= 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=(
                    "evaluation.params new_title, new_note, category_name, and positive new_amount "
                    "are required"
                ),
            )

        expected_new_value = -abs(new_amount)
        expected_old_value = -abs(old_amount)

        def _validator(
            state: dict[str, list[dict[str, Any]]],
            _params: dict[str, Any],
            value_tolerance: float,
        ) -> tuple[bool, dict[str, Any]]:
            records = state.get("records", [])
            new_matches = self._matching_records(
                records,
                title=new_title,
                note=new_note,
                category_name=category_name,
                category_type=category_type,
                expected_value=expected_new_value,
                value_tolerance=value_tolerance,
            )
            old_matches = self._matching_records(
                records,
                title=old_title,
                note=old_note,
                category_name=category_name,
                category_type=category_type,
                expected_value=expected_old_value,
                value_tolerance=value_tolerance,
            )
            matched = bool(new_matches) and not old_matches and len(records) == 1
            return matched, {
                "expected": {
                    "old_title": old_title,
                    "old_note": old_note,
                    "old_value": expected_old_value,
                    "new_title": new_title,
                    "new_note": new_note,
                    "new_value": expected_new_value,
                    "category_name": category_name,
                    "category_type": category_type,
                },
                "matched_row": new_matches[0] if new_matches else None,
                "new_match_count": len(new_matches),
                "old_match_count": len(old_matches),
                "record_count": len(records),
            }

        return self._evaluate_with_validator(
            context,
            validator=_validator,
            success_message="Expected Oinkoin expense edit was persisted",
            fail_message="Edited Oinkoin expense state was not found in the local database",
        )


class OinkoinDeleteExpenseEvaluator(_BaseOinkoinEvaluator):
    DEFAULT_CATEGORY_TYPE = 0
    DEFAULT_TITLE = "Tea"
    DEFAULT_NOTE = "bench_delete_me"
    DEFAULT_AMOUNT = 9.99

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        title = str(params.get("title") or self.DEFAULT_TITLE).strip()
        note = str(params.get("note") or self.DEFAULT_NOTE).strip()
        category_name = str(params.get("category_name") or "").strip()
        amount = float(params.get("amount") or self.DEFAULT_AMOUNT)
        category_type = int(params.get("category_type", self.DEFAULT_CATEGORY_TYPE))

        if not title or not note or not category_name or amount <= 0:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params title, note, category_name, and positive amount are required",
            )

        expected_value = -abs(amount)

        def _validator(
            state: dict[str, list[dict[str, Any]]],
            _params: dict[str, Any],
            value_tolerance: float,
        ) -> tuple[bool, dict[str, Any]]:
            records = state.get("records", [])
            old_matches = self._matching_records(
                records,
                title=title,
                note=note,
                category_name=category_name,
                category_type=category_type,
                expected_value=expected_value,
                value_tolerance=value_tolerance,
            )
            matched = not old_matches and not records
            return matched, {
                "expected": {
                    "title": title,
                    "note": note,
                    "category_name": category_name,
                    "category_type": category_type,
                    "expected_value": expected_value,
                },
                "deleted_match_count": len(old_matches),
                "record_count": len(records),
            }

        return self._evaluate_with_validator(
            context,
            validator=_validator,
            success_message="Expected Oinkoin expense was deleted",
            fail_message="Seeded Oinkoin expense still exists in the local database",
        )


class OinkoinCreateCustomCategoryAndUseItEvaluator(_BaseOinkoinEvaluator):
    DEFAULT_CATEGORY_TYPE = 0

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        category_name = str(params.get("category_name") or "").strip()
        initial_title = str(params.get("initial_title") or "").strip()
        initial_note = str(params.get("initial_note") or "").strip()
        initial_amount = float(params.get("initial_amount") or 0.0)
        final_title = str(params.get("final_title") or "").strip()
        final_note = str(params.get("final_note") or "").strip()
        final_amount = float(params.get("final_amount") or 0.0)
        category_type = int(params.get("category_type", self.DEFAULT_CATEGORY_TYPE))
        expected_records = [
            dict(item)
            for item in (params.get("expected_records") or [])
            if isinstance(item, Mapping) and str(item.get("title") or "").strip()
        ]
        expected_category_names = {
            str(item).strip()
            for item in (params.get("expected_category_names") or [])
            if str(item).strip()
        }
        forbidden_category_names = {
            str(item).strip()
            for item in (params.get("forbidden_category_names") or [])
            if str(item).strip()
        }

        if (
            not category_name
            or not initial_title
            or not initial_note
            or initial_amount <= 0
            or not final_title
            or not final_note
            or final_amount <= 0
        ):
            return EvalResult(
                status=EvalStatus.ERROR,
                message=(
                    "evaluation.params category_name, initial_* values, and final_* values are required"
                ),
            )

        expected_initial_value = -abs(initial_amount)
        expected_final_value = -abs(final_amount)

        def _validator(
            state: dict[str, list[dict[str, Any]]],
            _params: dict[str, Any],
            value_tolerance: float,
        ) -> tuple[bool, dict[str, Any]]:
            categories = state.get("categories", [])
            category_matches = [
                category
                for category in categories
                if str(category.get("name") or "").strip() == category_name
                and int(-1 if category.get("category_type") is None else category.get("category_type")) == category_type
            ]
            final_record_matches = self._matching_records(
                state.get("records", []),
                title=final_title,
                note=final_note,
                category_name=category_name,
                category_type=category_type,
                expected_value=expected_final_value,
                value_tolerance=value_tolerance,
            )
            initial_record_matches = self._matching_records(
                state.get("records", []),
                title=initial_title,
                note=initial_note,
                category_name=category_name,
                category_type=category_type,
                expected_value=expected_initial_value,
                value_tolerance=value_tolerance,
            )
            records = state.get("records", [])
            record_count = len(records)
            expected_record_details = expected_records or [
                {
                    "title": final_title,
                    "note": final_note,
                    "category_name": category_name,
                    "category_type": category_type,
                    "amount": final_amount,
                }
            ]
            unmatched_records = list(records)
            missing_expected_records: list[dict[str, Any]] = []
            matched_expected_records: list[dict[str, Any]] = []
            for spec in expected_record_details:
                spec_title = str(spec.get("title") or "").strip()
                spec_note = str(spec.get("note") or spec.get("description") or "").strip()
                spec_category = str(spec.get("category_name") or spec.get("category") or "").strip()
                spec_type = int(spec.get("category_type", category_type) or 0)
                spec_value = -abs(float(spec.get("amount") or 0.0)) if spec_type == 0 else abs(float(spec.get("amount") or 0.0))
                match_index = next(
                    (
                        index
                        for index, row in enumerate(unmatched_records)
                        if str(row.get("title") or "").strip() == spec_title
                        and str(row.get("description") or "").strip() == spec_note
                        and str(row.get("category_name") or "").strip() == spec_category
                        and int(-1 if row.get("category_type") is None else row.get("category_type")) == spec_type
                        and abs(float(row.get("value") or 0.0) - spec_value) <= value_tolerance
                    ),
                    None,
                )
                if match_index is None:
                    missing_expected_records.append(dict(spec))
                    continue
                matched_expected_records.append(unmatched_records.pop(match_index))
            category_names_present = {
                str(category.get("name") or "").strip()
                for category in categories
                if int(-1 if category.get("category_type") is None else category.get("category_type")) == category_type
            }
            required_category_names = set(expected_category_names)
            required_category_names.add(category_name)
            forbidden_category_matches = sorted(category_names_present & forbidden_category_names)
            matched = (
                bool(category_matches)
                and bool(final_record_matches)
                and not initial_record_matches
                and not missing_expected_records
                and not unmatched_records
                and required_category_names.issubset(category_names_present)
                and not forbidden_category_matches
            )
            return matched, {
                "expected": {
                    "category_name": category_name,
                    "category_type": category_type,
                    "initial_title": initial_title,
                    "initial_note": initial_note,
                    "initial_expected_value": expected_initial_value,
                    "final_title": final_title,
                    "final_note": final_note,
                    "final_expected_value": expected_final_value,
                    "expected_records": expected_record_details,
                    "expected_category_names": sorted(required_category_names),
                    "forbidden_category_names": sorted(forbidden_category_names),
                },
                "matched_category": category_matches[0] if category_matches else None,
                "matched_row": final_record_matches[0] if final_record_matches else None,
                "category_match_count": len(category_matches),
                "final_record_match_count": len(final_record_matches),
                "initial_record_match_count": len(initial_record_matches),
                "record_count": record_count,
                "matched_expected_records": matched_expected_records,
                "missing_expected_records": missing_expected_records,
                "unexpected_records": unmatched_records,
                "category_names_present": sorted(category_names_present),
                "forbidden_category_matches": forbidden_category_matches,
            }

        return self._evaluate_with_validator(
            context,
            validator=_validator,
            success_message="Expected Oinkoin custom category lifecycle state was persisted",
            fail_message="Expected edited Oinkoin custom category lifecycle state was not found in the local database",
        )
