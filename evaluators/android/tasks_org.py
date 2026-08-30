"""Evaluators for Tasks.org Android benchmark tasks."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any, Mapping

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # Python 3.8 test environment fallback.
    class ZoneInfoNotFoundError(Exception):
        pass

    def ZoneInfo(_name: str) -> dt.tzinfo:
        return dt.timezone.utc

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from platforms.android.tasks_org_support import (
    DEFAULT_APP_PACKAGE,
    DEFAULT_DATABASE_PATH,
    read_database_state,
)


def _normalize_note(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


class _BaseTasksOrgEvaluator(BaseEvaluator):

    DEFAULT_TIMEOUT_SECONDS = 10.0
    DEFAULT_POLL_INTERVAL_SECONDS = 1.0

    def _evaluate(
        self,
        context: Mapping[str, Any],
        *,
        validator,
        fail_message: str,
        success_message: str,
    ) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.execute_adb is required for Tasks.org evaluation",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        database_path = str(params.get("database_path") or DEFAULT_DATABASE_PATH).strip()
        timeout_seconds = float(params.get("timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS) or 0.0)
        poll_interval_seconds = float(
            params.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS) or 0.0
        )

        deadline = time.time() + max(timeout_seconds, 0.0)
        attempts = 0
        last_state: dict[str, list[dict[str, Any]]] = {"tasks": [], "lists": []}
        last_validation: dict[str, Any] = {}

        while True:
            attempts += 1
            try:
                last_state = read_database_state(
                    controller,
                    app_package=app_package,
                    database_path=database_path,
                )
                device_now = self._device_now(controller)
            except Exception as exc:
                return EvalResult(
                    status=EvalStatus.ERROR,
                    message=f"Failed to inspect Tasks.org state: {type(exc).__name__}: {exc}",
                    metadata={
                        "app_package": app_package,
                        "database_path": database_path,
                        "attempts": attempts,
                    },
                )

            matched, details = validator(last_state, params, device_now)
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
            last_validation = details

            if time.time() >= deadline:
                return EvalResult(
                    status=EvalStatus.FAIL,
                    message=fail_message,
                    metadata={
                        "attempts": attempts,
                        "database_path": database_path,
                        "validation": last_validation,
                        "tasks_seen": last_state.get("tasks", [])[:10],
                        "lists_seen": last_state.get("lists", [])[:5],
                    },
                )
            if poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)

    @staticmethod
    def _device_now(controller: Any) -> dt.datetime:
        epoch_seconds = int(str(controller.execute_adb(["shell", "date", "+%s"]) or "0").strip() or 0)
        timezone_name = str(
            controller.execute_adb(["shell", "getprop", "persist.sys.timezone"]) or "UTC"
        ).strip() or "UTC"
        try:
            tzinfo = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            tzinfo = dt.timezone.utc
        return dt.datetime.fromtimestamp(epoch_seconds, tz=tzinfo)

    @staticmethod
    def _active_tasks(state: Mapping[str, Any]) -> list[dict[str, Any]]:
        tasks = state.get("tasks") or []
        return [task for task in tasks if int(task.get("deleted") or 0) == 0]

    @staticmethod
    def _task_due_matches(task: Mapping[str, Any], *, expected_day: dt.date | None, timezone: dt.tzinfo) -> bool:
        due_value = int(task.get("dueDate") or 0)
        if expected_day is None:
            return due_value == 0
        if due_value <= 0:
            return False
        due_day = dt.datetime.fromtimestamp(due_value / 1000.0, tz=timezone).date()
        return due_day == expected_day

    def _task_matches_spec(
        self,
        task: Mapping[str, Any],
        spec: Mapping[str, Any],
        *,
        device_now: dt.datetime,
    ) -> bool:
        title = str(spec.get("title") or "").strip()
        if title and str(task.get("title") or "").strip() != title:
            return False
        if "note" in spec and _normalize_note(str(task.get("notes") or "")) != _normalize_note(str(spec.get("note") or "")):
            return False
        expected_completed = int(spec.get("completed", 0) or 0)
        if int(task.get("completed") or 0) != expected_completed:
            return False
        if "due_day_offset" in spec:
            raw_offset = spec.get("due_day_offset")
            expected_day = None
            if raw_offset not in (None, ""):
                expected_day = (device_now + dt.timedelta(days=int(raw_offset))).date()
            if not self._task_due_matches(task, expected_day=expected_day, timezone=device_now.tzinfo):
                return False
        return True

    def _match_expected_top_level_specs(
        self,
        top_level_tasks: list[dict[str, Any]],
        specs: list[Mapping[str, Any]],
        *,
        device_now: dt.datetime,
    ) -> tuple[bool, dict[str, Any]]:
        unmatched = list(top_level_tasks)
        matched: list[dict[str, Any]] = []
        missing: list[Mapping[str, Any]] = []
        for spec in specs:
            match_index = next(
                (
                    index
                    for index, task in enumerate(unmatched)
                    if self._task_matches_spec(task, spec, device_now=device_now)
                ),
                None,
            )
            if match_index is None:
                missing.append(dict(spec))
                continue
            matched.append(unmatched.pop(match_index))
        return not missing and not unmatched, {
            "expected_top_level_specs": [dict(spec) for spec in specs],
            "matched_top_level_tasks": matched,
            "missing_top_level_specs": missing,
            "unexpected_top_level_tasks": unmatched,
        }


class TasksOrgTaskWithNoteEvaluator(_BaseTasksOrgEvaluator):
    """Check that a single top-level task with a fixed note was created."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        title = str(params.get("title") or "").strip()
        note = str(params.get("note") or "").strip()
        preserved_top_level_tasks = [
            dict(item)
            for item in (params.get("preserved_top_level_tasks") or [])
            if isinstance(item, Mapping) and str(item.get("title") or "").strip()
        ]
        forbidden_top_level_titles = {
            str(item).strip()
            for item in (params.get("forbidden_top_level_titles") or [])
            if str(item).strip()
        }
        if not title or not note:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params title and note are required",
            )

        def _validator(state, _params, device_now):
            active_tasks = self._active_tasks(state)
            top_level_tasks = [task for task in active_tasks if int(task.get("parent") or 0) == 0]
            child_tasks = [task for task in active_tasks if int(task.get("parent") or 0) != 0]
            forbidden_matches = [
                task
                for task in top_level_tasks
                if str(task.get("title") or "").strip() in forbidden_top_level_titles
            ]
            matches = [
                task
                for task in top_level_tasks
                if str(task.get("title") or "").strip() == title
                and _normalize_note(str(task.get("notes") or "")) == _normalize_note(note)
                and int(task.get("completed") or 0) == 0
                and self._task_due_matches(task, expected_day=None, timezone=device_now.tzinfo)
            ]
            expected_specs = [
                {
                    "title": title,
                    "note": note,
                    "completed": 0,
                },
                *preserved_top_level_tasks,
            ]
            top_level_match, top_level_details = self._match_expected_top_level_specs(
                top_level_tasks,
                expected_specs,
                device_now=device_now,
            )
            strict_match = len(matches) == 1 and top_level_match and not child_tasks and not forbidden_matches
            return strict_match, {
                "expected": {
                    "title": title,
                    "note": note,
                    "preserved_top_level_tasks": preserved_top_level_tasks,
                    "forbidden_top_level_titles": sorted(forbidden_top_level_titles),
                },
                "matched_task": matches[0] if matches else None,
                "match_count": len(matches),
                "top_level_count": len(top_level_tasks),
                "child_count": len(child_tasks),
                "forbidden_matches": forbidden_matches,
                "top_level_titles": [str(task.get("title") or "").strip() for task in top_level_tasks],
                **top_level_details,
            }

        return self._evaluate(
            context,
            validator=_validator,
            success_message="Expected Tasks.org note task was created",
            fail_message="Expected Tasks.org note task was not found",
        )


class TasksOrgTaskWithDueDateEvaluator(_BaseTasksOrgEvaluator):
    """Check that a single top-level task with a note and tomorrow due date exists."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        title = str(params.get("title") or "").strip()
        note = str(params.get("note") or "").strip()
        due_day_offset = int(params.get("due_day_offset", 1))
        preserved_top_level_tasks = [
            dict(item)
            for item in (params.get("preserved_top_level_tasks") or [])
            if isinstance(item, Mapping) and str(item.get("title") or "").strip()
        ]
        forbidden_top_level_titles = {
            str(item).strip()
            for item in (params.get("forbidden_top_level_titles") or [])
            if str(item).strip()
        }
        if not title or not note:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params title and note are required",
            )

        def _validator(state, _params, device_now):
            expected_day = (device_now + dt.timedelta(days=due_day_offset)).date()
            active_tasks = self._active_tasks(state)
            top_level_tasks = [task for task in active_tasks if int(task.get("parent") or 0) == 0]
            child_tasks = [task for task in active_tasks if int(task.get("parent") or 0) != 0]
            forbidden_matches = [
                task
                for task in top_level_tasks
                if str(task.get("title") or "").strip() in forbidden_top_level_titles
            ]
            matches = [
                task
                for task in top_level_tasks
                if str(task.get("title") or "").strip() == title
                and _normalize_note(str(task.get("notes") or "")) == _normalize_note(note)
                and int(task.get("completed") or 0) == 0
                and self._task_due_matches(task, expected_day=expected_day, timezone=device_now.tzinfo)
            ]
            expected_specs = [
                {
                    "title": title,
                    "note": note,
                    "due_day_offset": due_day_offset,
                    "completed": 0,
                },
                *preserved_top_level_tasks,
            ]
            top_level_match, top_level_details = self._match_expected_top_level_specs(
                top_level_tasks,
                expected_specs,
                device_now=device_now,
            )
            strict_match = len(matches) == 1 and top_level_match and not child_tasks and not forbidden_matches
            return strict_match, {
                "expected": {
                    "title": title,
                    "note": note,
                    "due_day": expected_day.isoformat(),
                    "preserved_top_level_tasks": preserved_top_level_tasks,
                    "forbidden_top_level_titles": sorted(forbidden_top_level_titles),
                },
                "matched_task": matches[0] if matches else None,
                "match_count": len(matches),
                "top_level_count": len(top_level_tasks),
                "child_count": len(child_tasks),
                "forbidden_matches": forbidden_matches,
                "top_level_titles": [str(task.get("title") or "").strip() for task in top_level_tasks],
                **top_level_details,
            }

        return self._evaluate(
            context,
            validator=_validator,
            success_message="Expected Tasks.org due-date task was created",
            fail_message="Expected Tasks.org due-date task was not found",
        )


class TasksOrgTaskWithSubtasksEvaluator(_BaseTasksOrgEvaluator):
    """Check that a parent task plus the required subtasks were created."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        parent_title = str(params.get("parent_title") or "").strip()
        parent_note = str(params.get("parent_note") or "").strip()
        due_day_offset = int(params.get("due_day_offset", 1))
        expected_subtasks = [str(item).strip() for item in (params.get("subtasks") or []) if str(item).strip()]
        preserved_top_level_tasks = [
            dict(item)
            for item in (params.get("preserved_top_level_tasks") or [])
            if isinstance(item, Mapping) and str(item.get("title") or "").strip()
        ]
        forbidden_top_level_titles = {
            str(item).strip()
            for item in (params.get("forbidden_top_level_titles") or [])
            if str(item).strip()
        }
        if not parent_title or not parent_note or not expected_subtasks:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params parent_title, parent_note, and subtasks are required",
            )

        def _validator(state, _params, device_now):
            expected_day = (device_now + dt.timedelta(days=due_day_offset)).date()
            active_tasks = self._active_tasks(state)
            top_level_tasks = [task for task in active_tasks if int(task.get("parent") or 0) == 0]
            all_child_tasks = [task for task in active_tasks if int(task.get("parent") or 0) != 0]
            forbidden_matches = [
                task
                for task in top_level_tasks
                if str(task.get("title") or "").strip() in forbidden_top_level_titles
            ]
            parent_matches = [
                task
                for task in top_level_tasks
                if str(task.get("title") or "").strip() == parent_title
                and _normalize_note(str(task.get("notes") or "")) == _normalize_note(parent_note)
                and int(task.get("completed") or 0) == 0
                and self._task_due_matches(task, expected_day=expected_day, timezone=device_now.tzinfo)
            ]
            if not parent_matches:
                return False, {
                    "expected_parent": {
                        "title": parent_title,
                        "note": parent_note,
                        "due_day": expected_day.isoformat(),
                    },
                    "expected_subtasks": expected_subtasks,
                    "matched_parent": None,
                    "matched_subtasks": [],
                    "top_level_count": len(top_level_tasks),
                    "child_count": len(all_child_tasks),
                    "forbidden_matches": forbidden_matches,
                }

            parent = parent_matches[0]
            parent_id = int(parent.get("id") or 0)
            matched_child_tasks = [
                task for task in active_tasks if int(task.get("parent") or 0) == parent_id
            ]
            ordered_child_tasks = sorted(
                matched_child_tasks,
                key=lambda task: (int(task.get("order") or 0), int(task.get("id") or 0)),
            )
            child_titles = [str(task.get("title") or "").strip() for task in ordered_child_tasks]
            expected_specs = [
                {
                    "title": parent_title,
                    "note": parent_note,
                    "due_day_offset": due_day_offset,
                    "completed": 0,
                },
                *preserved_top_level_tasks,
            ]
            top_level_match, top_level_details = self._match_expected_top_level_specs(
                top_level_tasks,
                expected_specs,
                device_now=device_now,
            )
            strict_match = (
                len(parent_matches) == 1
                and top_level_match
                and len(matched_child_tasks) == len(expected_subtasks)
                and len(all_child_tasks) == len(expected_subtasks)
                and expected_subtasks == child_titles
                and all(int(task.get("completed") or 0) == 0 for task in matched_child_tasks)
                and not forbidden_matches
            )
            return strict_match, {
                "expected_parent": {
                    "title": parent_title,
                    "note": parent_note,
                    "due_day": expected_day.isoformat(),
                    "preserved_top_level_tasks": preserved_top_level_tasks,
                    "forbidden_top_level_titles": sorted(forbidden_top_level_titles),
                },
                "expected_subtasks": expected_subtasks,
                "matched_parent": parent,
                "matched_subtasks": ordered_child_tasks,
                "matched_subtask_titles": child_titles,
                "forbidden_matches": forbidden_matches,
                "top_level_count": len(top_level_tasks),
                "child_count": len(all_child_tasks),
                **top_level_details,
            }

        return self._evaluate(
            context,
            validator=_validator,
            success_message="Expected Tasks.org parent task and subtasks were created",
            fail_message="Expected Tasks.org parent task plus subtasks were not found",
        )
