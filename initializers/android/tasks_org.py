"""Android initializers for Tasks.org benchmark tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.android.tasks_org_support import (
    DEFAULT_APP_ACTIVITY,
    DEFAULT_APP_PACKAGE,
    DEFAULT_WAIT_MS,
    prepare_blank_task_editor,
    prepare_task_list_view,
)


class _BaseTasksOrgInitializer(BaseInitializer):
    def _prepare_common(self, context: Mapping[str, Any]) -> tuple[Any, dict[str, Any]] | InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Tasks.org initialization",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", True))

        if not app_package or not app_activity:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package and app_activity",
            )

        params.update(
            {
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "clear_app_data": clear_app_data,
            }
        )
        return controller, params

    def _prepare_editor(self, controller: Any, params: Mapping[str, Any]) -> InitResult:
        try:
            metadata = prepare_blank_task_editor(
                controller,
                app_package=str(params["app_package"]),
                app_activity=str(params["app_activity"]),
                clear_app_data=bool(params.get("clear_app_data", True)),
                wait_ms=int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0),
            )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Tasks.org task editor: {type(exc).__name__}: {exc}",
                metadata=dict(params),
            )
        return InitResult(
            status=InitStatus.PASS,
            message="Tasks.org opened at a blank task editor",
            metadata=metadata,
        )

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        prepared = self._prepare_common(context)
        if isinstance(prepared, InitResult):
            return prepared
        controller, params = prepared
        seed_tasks = [
            dict(item)
            for item in (params.get("seed_tasks") or [])
            if isinstance(item, Mapping) and str(item.get("title") or "").strip()
        ]
        open_blank_editor = bool(params.get("open_blank_editor", True))
        if seed_tasks or not open_blank_editor:
            try:
                metadata = prepare_task_list_view(
                    controller,
                    app_package=str(params["app_package"]),
                    app_activity=str(params["app_activity"]),
                    clear_app_data=bool(params.get("clear_app_data", True)),
                    wait_ms=int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0),
                    seed_tasks=seed_tasks,
                )
            except Exception as exc:
                return InitResult(
                    status=InitStatus.ERROR,
                    message=f"Failed to prepare Tasks.org seeded task list: {type(exc).__name__}: {exc}",
                    metadata=dict(params),
                )
            if not open_blank_editor:
                return InitResult(
                    status=InitStatus.PASS,
                    message="Tasks.org opened at the seeded task list",
                    metadata=metadata,
                )
        return self._prepare_editor(controller, params)


class TasksOrgCreateTaskInitializer(_BaseTasksOrgInitializer):
    """Prepare Tasks.org at a blank task editor."""
    pass


class TasksOrgCreateTaskWithDueDateInitializer(_BaseTasksOrgInitializer):
    """Prepare Tasks.org at a blank task editor."""
    pass


class TasksOrgCreateTaskWithSubtasksInitializer(_BaseTasksOrgInitializer):
    """Prepare Tasks.org at a blank task editor."""
    pass
