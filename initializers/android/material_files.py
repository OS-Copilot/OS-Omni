"""Android initializers for Material Files benchmark tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.android.bench_storage_support import (
    allow_manage_external_storage,
    clear_and_launch_app,
    ensure_app_installed,
    grant_post_notifications,
    push_text,
    remove_path,
    tap_material_files_entry,
    wait_for_breadcrumb,
)
from platforms.android.bootstrap import AndroidBootstrapDriver


DEFAULT_APP_PACKAGE = "me.zhanghai.android.files"
DEFAULT_APP_ACTIVITY = ".filelist.FileListActivity"
DEFAULT_WAIT_MS = 1200
DEFAULT_WORKSPACE_ROOT = "/sdcard/Documents/bench_files_lab"
DEFAULT_SEED_TEXT = "seed_note\n"


class _BaseMaterialFilesInitializer(BaseInitializer):
    ERROR_TASK_LABEL = "material-files"
    SUCCESS_MESSAGE = "Material Files opened at the benchmark workspace root"

    def _prepare_common(self, context: Mapping[str, Any]) -> tuple[Any, dict[str, Any]] | InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Material Files initialization",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", True))
        workspace_root = str(params.get("workspace_root") or DEFAULT_WORKSPACE_ROOT).strip()
        source_dir = str(params.get("source_dir") or f"{workspace_root}/incoming").strip()
        archive_dir = str(params.get("archive_dir") or f"{workspace_root}/archive").strip()
        seed_file = str(params.get("seed_file") or f"{source_dir}/seed_note.txt").strip()
        seed_text = str(params.get("seed_text") or DEFAULT_SEED_TEXT)
        extra_seed_files = [
            dict(item)
            for item in (params.get("extra_seed_files") or [])
            if isinstance(item, Mapping) and str(item.get("path") or "").strip()
        ]

        if not app_package or not app_activity or not workspace_root:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package, app_activity, and workspace_root",
            )

        params.update(
            {
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "clear_app_data": clear_app_data,
                "workspace_root": workspace_root,
                "source_dir": source_dir,
                "archive_dir": archive_dir,
                "seed_file": seed_file,
                "seed_text": seed_text,
                "extra_seed_files": extra_seed_files,
            }
        )
        return controller, params

    @staticmethod
    def _seed_workspace(controller: Any, params: Mapping[str, Any]) -> None:
        workspace_root = str(params["workspace_root"])
        source_dir = str(params["source_dir"])
        archive_dir = str(params["archive_dir"])
        seed_file = str(params["seed_file"])
        seed_text = str(params["seed_text"])

        remove_path(controller, workspace_root)
        controller.execute_adb(["shell", f"mkdir -p {source_dir} {archive_dir}"])
        push_text(controller, seed_file, seed_text)
        for item in params.get("extra_seed_files") or []:
            remote_path = str(item.get("path") or "").strip()
            text = str(item.get("text") or DEFAULT_SEED_TEXT)
            if remote_path:
                push_text(controller, remote_path, text)

    @staticmethod
    def _launch_and_open_workspace(controller: Any, params: Mapping[str, Any]) -> None:
        app_package = str(params["app_package"])
        app_activity = str(params["app_activity"])
        clear_app_data = bool(params.get("clear_app_data", True))
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)

        ensure_app_installed(controller, app_package, label="Material Files")
        clear_and_launch_app(
            controller,
            app_package=app_package,
            app_activity=app_activity,
            clear_app_data=clear_app_data,
            wait_ms=wait_ms,
        )
        allow_manage_external_storage(controller, app_package)
        grant_post_notifications(controller, app_package)
        # Relaunch after permissions/appops so the initial view is stable.
        clear_and_launch_app(
            controller,
            app_package=app_package,
            app_activity=app_activity,
            clear_app_data=False,
            wait_ms=wait_ms,
        )

        driver = AndroidBootstrapDriver(controller, expected_package=app_package, settle_delay_seconds=0.4)
        search_node = driver.wait_for_node(
            {"resource_id": "me.zhanghai.android.files:id/action_search"},
            timeout_seconds=12.0,
            raise_on_timeout=False,
        )
        if search_node is None:
            clear_and_launch_app(
                controller,
                app_package=app_package,
                app_activity=app_activity,
                clear_app_data=False,
                wait_ms=max(wait_ms, 2000),
            )
            search_node = driver.wait_for_node(
                {"resource_id": "me.zhanghai.android.files:id/action_search"},
                timeout_seconds=18.0,
                raise_on_timeout=False,
            )
        if search_node is None:
            driver.wait_for_node({"resource_id": "me.zhanghai.android.files:id/action_search"}, timeout_seconds=1.0)
        tap_material_files_entry(driver, "Documents", timeout_seconds=10.0)
        tap_material_files_entry(driver, "bench_files_lab", timeout_seconds=10.0)
        wait_for_breadcrumb(driver, "bench_files_lab", timeout_seconds=10.0)

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        prepared = self._prepare_common(context)
        if isinstance(prepared, InitResult):
            return prepared
        controller, params = prepared

        try:
            self._seed_workspace(controller, params)
            self._launch_and_open_workspace(controller, params)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=(
                    f"Failed to prepare Material Files {self.ERROR_TASK_LABEL} task: "
                    f"{type(exc).__name__}: {exc}"
                ),
                metadata=params,
            )

        return InitResult(
            status=InitStatus.PASS,
            message=self.SUCCESS_MESSAGE,
            metadata=params,
        )


class MaterialFilesCreateFolderInitializer(_BaseMaterialFilesInitializer):
    """Seed the workspace and open Material Files at the benchmark root folder."""
    ERROR_TASK_LABEL = "create-folder"


class MaterialFilesRenameFileInitializer(_BaseMaterialFilesInitializer):
    """Seed the workspace and open Material Files at the benchmark root for the rename task."""
    ERROR_TASK_LABEL = "rename"
    SUCCESS_MESSAGE = "Material Files opened at the benchmark workspace root for the rename task"


class MaterialFilesOrganizeFileInitializer(_BaseMaterialFilesInitializer):
    """Seed the workspace and open Material Files at the benchmark root folder."""
    ERROR_TASK_LABEL = "organize-file"
    SUCCESS_MESSAGE = "Material Files opened at the benchmark workspace root for file organization"
