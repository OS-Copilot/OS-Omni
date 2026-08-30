"""Initializer for Android LibreOffice status-report edit task."""

from __future__ import annotations

import io
import json
from pathlib import Path
import time
import zipfile
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.android.bench_storage_support import (
    allow_manage_external_storage,
    clear_and_launch_app,
    ensure_app_installed,
    grant_permissions,
    push_bytes,
    remove_path,
    scan_media_paths,
)

DEFAULT_APP_PACKAGE = "org.documentfoundation.libreoffice"
DEFAULT_APP_ACTIVITY = "org.libreoffice.ui.LibreOfficeUIActivity"
DEFAULT_WAIT_MS = 2200
DEFAULT_DOCUMENT_DIR = "/sdcard/Documents"
DEFAULT_FILENAME = "status_report.odt"
_DEBUG_LOG_PATH = Path("debug-9381fa.log")
_DEBUG_SESSION_ID = "9381fa"


def _debug_log(*, run_id: str, hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    payload = {
        "sessionId": _DEBUG_SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _build_status_report_odt_bytes() -> bytes:
    """Build a minimal multi-page ODT with one editable pending-status line."""
    mimetype = "application/vnd.oasis.opendocument.text"
    content_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
 office:version="1.2">
 <office:automatic-styles>
  <style:style style:name="PB" style:family="paragraph">
   <style:paragraph-properties fo:break-before="page"/>
  </style:style>
 </office:automatic-styles>
 <office:body>
  <office:text>
   <text:p>System Status Report</text:p>
   <text:p>Date: 2026-04-23</text:p>
   <text:p>Owner: Ops Team</text:p>
   <text:p>Section A summary: baseline checks complete.</text:p>
   <text:p>Section A status: Monitoring</text:p>
   <text:p text:style-name="PB">Page 2 - KPI Snapshot</text:p>
   <text:p>CPU Utilization: 58%</text:p>
   <text:p>Memory Utilization: 67%</text:p>
   <text:p>Open Incidents: 2</text:p>
   <text:p>Escalations: 0</text:p>
   <text:p text:style-name="PB">Page 3 - Actions</text:p>
   <text:p>1. Verify rollback plan.</text:p>
   <text:p>2. Confirm service owner handoff.</text:p>
   <text:p>3. Re-check dependency service health.</text:p>
   <text:p text:style-name="PB">Page 4 - Final Decision</text:p>
   <text:p>Ticket: SR-2026-04-23</text:p>
   <text:p>Status: Pending</text:p>
   <text:p>Approval is waiting for the final validation checklist.</text:p>
  </office:text>
 </office:body>
</office:document-content>
"""
    styles_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 office:version="1.2">
 <office:styles/>
 <office:automatic-styles/>
 <office:master-styles/>
</office:document-styles>
"""
    meta_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
 office:version="1.2">
 <office:meta>
  <meta:generator>HelloWorld Bench</meta:generator>
 </office:meta>
</office:document-meta>
"""
    settings_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-settings xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 office:version="1.2">
 <office:settings/>
</office:document-settings>
"""
    manifest_xml = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
 manifest:version="1.2">
 <manifest:file-entry manifest:media-type="application/vnd.oasis.opendocument.text" manifest:full-path="/"/>
 <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>
 <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="styles.xml"/>
 <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="meta.xml"/>
 <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="settings.xml"/>
</manifest:manifest>
"""

    buff = io.BytesIO()
    with zipfile.ZipFile(buff, mode="w") as zf:
        zf.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("styles.xml", styles_xml, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("meta.xml", meta_xml, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("settings.xml", settings_xml, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("META-INF/manifest.xml", manifest_xml, compress_type=zipfile.ZIP_DEFLATED)
    return buff.getvalue()


class LibreOfficeStatusReportPrepInitializer(BaseInitializer):
    """Seed status_report.odt and launch LibreOffice on the app home page."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for LibreOffice status-report initializer",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", False))
        document_dir = str(params.get("document_dir") or DEFAULT_DOCUMENT_DIR).strip().rstrip("/")
        filename = str(params.get("filename") or DEFAULT_FILENAME).strip()
        remote_path = f"{document_dir}/{filename}"
        run_id = str(params.get("debug_run_id") or f"init-{int(time.time() * 1000)}")

        if not app_package or not app_activity or not filename:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package, app_activity, and filename",
            )

        try:
            ensure_app_installed(controller, app_package, label="LibreOffice")
            remove_path(controller, remote_path)
            payload = _build_status_report_odt_bytes()
            # region agent log
            _debug_log(
                run_id=run_id,
                hypothesis_id="H1",
                location="initializers/android/libreoffice_status_report_prep.py:initialize",
                message="Built ODT payload, validating embedded content.xml markers",
                data={
                    "payload_size": len(payload),
                    "contains_pending_in_payload": b"Status: Pending" in payload,
                    "contains_completed_in_payload": b"Status: Completed" in payload,
                },
            )
            # endregion
            push_bytes(controller, remote_path, payload)
            scan_media_paths(controller, [remote_path])
            ls_output = str(controller.execute_adb(["shell", "ls", "-l", remote_path]) or "").strip()
            # region agent log
            _debug_log(
                run_id=run_id,
                hypothesis_id="H2",
                location="initializers/android/libreoffice_status_report_prep.py:initialize",
                message="Pushed seeded status report to device",
                data={
                    "remote_path": remote_path,
                    "ls_output": ls_output,
                },
            )
            # endregion

            grant_permissions(
                controller,
                app_package,
                [
                    "android.permission.READ_EXTERNAL_STORAGE",
                    "android.permission.WRITE_EXTERNAL_STORAGE",
                ],
            )
            allow_manage_external_storage(controller, app_package)

            clear_and_launch_app(
                controller,
                app_package=app_package,
                app_activity=app_activity,
                clear_app_data=clear_app_data,
                wait_ms=wait_ms,
            )
            focus = str(
                controller.execute_adb(
                    ["shell", "sh", "-c", "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"]
                )
                or ""
            )
            # region agent log
            _debug_log(
                run_id=run_id,
                hypothesis_id="H2",
                location="initializers/android/libreoffice_status_report_prep.py:initialize",
                message="Launched LibreOffice after seeding",
                data={
                    "app_package": app_package,
                    "focus_output": focus,
                    "clear_app_data": clear_app_data,
                },
            )
            # endregion
        except Exception as exc:
            # region agent log
            _debug_log(
                run_id=run_id,
                hypothesis_id="H2",
                location="initializers/android/libreoffice_status_report_prep.py:initialize",
                message="Initializer exception",
                data={
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                    "remote_path": remote_path,
                },
            )
            # endregion
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare LibreOffice status report task: {type(exc).__name__}: {exc}",
                metadata={"remote_path": remote_path, "app_package": app_package},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="status_report.odt seeded and LibreOffice launched",
            metadata={
                "remote_path": remote_path,
                "filename": filename,
                "document_dir": document_dir,
                "app_package": app_package,
            },
        )
