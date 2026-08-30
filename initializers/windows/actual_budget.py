"""Initializer for preparing a deterministic Actual Budget state on Windows."""

from __future__ import annotations

import time
from pathlib import Path
from textwrap import dedent
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class ActualBudgetInitializer(BaseInitializer):
    """Restore a clean local budget before opening the already-installed app."""

    DEFAULT_WAIT_MS = 5000
    DEFAULT_TEMPLATE_ARCHIVE = "files/actual/blank-budget-template.zip"
    DEFAULT_GLOBAL_STORE_TEMPLATE = "files/actual/global-store.blank.json"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        task = context.get("task")

        if controller is None or not hasattr(controller, "run_powershell_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_powershell_script is required")

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        timeout = int(params.get("timeout", 120) or 120)
        template_archive = str(params.get("template_archive_path") or self.DEFAULT_TEMPLATE_ARCHIVE).strip()
        global_store_template = str(params.get("global_store_template_path") or self.DEFAULT_GLOBAL_STORE_TEMPLATE).strip()

        archive_local = self._resolve_local_path(template_archive, task=task)
        global_store_local = self._resolve_local_path(global_store_template, task=task)
        used_template_restore = archive_local.exists() and global_store_local.exists()

        if used_template_restore:
            remote_archive = r"C:\Users\User\AppData\Local\Temp\actual-blank-budget-template.zip"
            remote_global_store = r"C:\Users\User\AppData\Local\Temp\actual-global-store.blank.json"
            try:
                controller.upload_file(str(archive_local), remote_archive)
                controller.upload_file(str(global_store_local), remote_global_store)
            except Exception as exc:
                return InitResult(status=InitStatus.ERROR, message=f"Failed to upload Actual template: {exc}")
            reset_script = self._build_template_restore_script(
                remote_archive=remote_archive,
                remote_global_store=remote_global_store,
            )
        else:
            reset_script = self._build_profile_reset_script()

        try:
            result = controller.run_powershell_script(reset_script, timeout=timeout)
            returncode = int(result.get("returncode", 0))
            if returncode != 0:
                raise RuntimeError(str(result.get("error") or result.get("output") or "").strip() or f"exit code {returncode}")
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Actual Budget state: {exc}",
                metadata={
                    "wait_ms": wait_ms,
                    "used_template_restore": used_template_restore,
                    "template_archive": str(archive_local) if archive_local.exists() else None,
                    "global_store_template": str(global_store_local) if global_store_local.exists() else None,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Actual Budget clean baseline and launched app",
            metadata={
                "wait_ms": wait_ms,
                "used_template_restore": used_template_restore,
                "template_archive": str(archive_local) if archive_local.exists() else None,
                "global_store_template": str(global_store_local) if global_store_local.exists() else None,
            },
        )

    @staticmethod
    def _resolve_local_path(raw_path: str, *, task: Any) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        task_source = getattr(task, "source_file", None)
        if task_source:
            candidate = (Path(task_source).expanduser().resolve().parent / path).resolve()
            if candidate.exists():
                return candidate
        return (Path.cwd() / path).resolve()

    @staticmethod
    def _build_template_restore_script(*, remote_archive: str, remote_global_store: str) -> str:
        return dedent(
            f"""
            $ErrorActionPreference = "Stop"

            Get-Process -Name "Actual Budget","Actual","actual-server" -ErrorAction SilentlyContinue |
              Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 1200

            $documentRoot = Join-Path $env:USERPROFILE "Documents\\Actual"
            $stateRoots = @(
              "$env:APPDATA\\Actual",
              "$env:LOCALAPPDATA\\actual",
              "$env:APPDATA\\actual"
            )

            foreach ($path in @($documentRoot) + $stateRoots) {{
              if (Test-Path $path) {{
                Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
              }}
            }}

            New-Item -ItemType Directory -Force -Path $documentRoot | Out-Null
            foreach ($stateRoot in $stateRoots) {{
              New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
            }}

            Expand-Archive -LiteralPath "{remote_archive}" -DestinationPath $documentRoot -Force
            Copy-Item -LiteralPath "{remote_global_store}" -Destination (Join-Path $env:APPDATA "Actual\\global-store.json") -Force

            $candidates = @(
              "$env:LOCALAPPDATA\\Programs\\Actual\\Actual.exe",
              "$env:LOCALAPPDATA\\Programs\\actual\\Actual.exe",
              "$env:LOCALAPPDATA\\Programs\\desktop-electron\\Actual.exe",
              "$env:LOCALAPPDATA\\Programs\\actual\\Actual Budget.exe",
              "$env:LOCALAPPDATA\\actual\\Actual Budget.exe",
              "C:\\Program Files\\Actual\\Actual.exe",
              "C:\\Program Files\\Actual Budget\\Actual Budget.exe",
              "$env:USERPROFILE\\Tools\\actualbudget.exe",
              "C:\\Tools\\actualbudget.exe",
              "C:\\Tools\\Actual-windows-x64.exe"
            )

            $exe = $candidates | Where-Object {{ Test-Path $_ }} | Select-Object -First 1
            if (-not $exe) {{
              throw "Actual Budget executable not found; app must be preinstalled in storage."
            }}

            Start-Process $exe
            Write-Output "ACTUAL_TEMPLATE_RESTORE_OK=True"
            """
        ).strip()

    @staticmethod
    def _build_profile_reset_script() -> str:
        return r"""
$ErrorActionPreference = "Stop"

Get-Process -Name "Actual Budget","Actual","actual-server" -ErrorAction SilentlyContinue |
  Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 1200

$paths = @(
  "$env:APPDATA\Actual",
  "$env:LOCALAPPDATA\actual",
  "$env:APPDATA\actual",
  "$env:USERPROFILE\Documents\Actual"
)

foreach ($path in $paths) {
  if (Test-Path $path) {
    Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$candidates = @(
  "$env:LOCALAPPDATA\Programs\Actual\Actual.exe",
  "$env:LOCALAPPDATA\Programs\actual\Actual.exe",
  "$env:LOCALAPPDATA\Programs\desktop-electron\Actual.exe",
  "$env:LOCALAPPDATA\Programs\actual\Actual Budget.exe",
  "$env:LOCALAPPDATA\actual\Actual Budget.exe",
  "C:\Program Files\Actual\Actual.exe",
  "C:\Program Files\Actual Budget\Actual Budget.exe",
  "$env:USERPROFILE\Tools\actualbudget.exe",
  "C:\Tools\actualbudget.exe",
  "C:\Tools\Actual-windows-x64.exe"
)

$exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $exe) {
  throw "Actual Budget executable not found; app must be preinstalled in storage."
}

Start-Process $exe
Write-Output "ACTUAL_PROFILE_RESET_FALLBACK=True"
"""
