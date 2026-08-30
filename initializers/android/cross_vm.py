"""Android initializers for cross-VM transfer source tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.android.bench_storage_support import ensure_app_installed, push_text, remove_path


class AndroidTransferSourceInitializer(BaseInitializer):
    """Seed an Android source text file and open Markor for transfer tasks."""

    DEFAULT_APP_PACKAGE = "net.gsantner.markor"
    DEFAULT_WAIT_MS = 1200

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(status=InitStatus.ERROR, message="controller.execute_adb is required")

        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        source_path = str(params.get("source_path") or "").strip()
        source_text = str(params.get("source_text") or "")
        transfer_text = params.get("transfer_text")
        transfer_path = str(params.get("transfer_path") or "").strip()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", False))
        prepare_transfer = bool(params.get("prepare_transfer", False))

        if not app_package or not source_path or not transfer_path:
            return InitResult(
                status=InitStatus.ERROR,
                message="app_package, source_path, and transfer_path are required",
            )

        try:
            ensure_app_installed(controller, app_package, label="Markor")
            if clear_app_data:
                controller.execute_adb(["shell", "pm", "clear", app_package])
            remove_path(controller, transfer_path)
            push_text(controller, source_path, source_text)
            if transfer_text is not None:
                push_text(controller, transfer_path, str(transfer_text))
            elif prepare_transfer:
                push_text(controller, transfer_path, source_text)
            open_path = str(
                params.get("open_path") or (transfer_path if prepare_transfer else source_path)
            ).strip()
            controller.execute_adb(["shell", "am", "force-stop", app_package])
            controller.execute_adb(
                [
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    f"file://{open_path}",
                    "-t",
                    "text/plain",
                ]
            )
            if wait_ms > 0:
                import time

                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Android transfer source: {type(exc).__name__}: {exc}",
                metadata=params,
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Android transfer source prepared",
            metadata={
                **params,
                "app_package": app_package,
                "source_path": source_path,
                "transfer_path": transfer_path,
                "open_path": open_path,
            },
        )
