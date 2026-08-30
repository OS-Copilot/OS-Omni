"""Initializer for Android LibreOffice notes append task."""

from __future__ import annotations

import io
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
DEFAULT_WAIT_MS = 2400
DEFAULT_DOCUMENT_DIR = "/sdcard/Documents"
DEFAULT_FILENAME = "notes.odt"


def _build_notes_odt_bytes() -> bytes:
    """Build a structured multi-page ODT for appending task lines at the end."""
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
   <text:p>Weekly Operations Notes</text:p>
   <text:p>Date: 2026-04-24</text:p>
   <text:p>Owner: Mobile Team</text:p>
   <text:p>Summary: Device checks completed and baseline validated.</text:p>
   <text:p>Open questions were discussed and moved to follow-up.</text:p>
   <text:p text:style-name="PB">Section 2 - Meeting Log</text:p>
   <text:p>09:00 Standup started with all owners present.</text:p>
   <text:p>09:20 Build health and test signal reviewed.</text:p>
   <text:p>09:45 Risk register reviewed and updated.</text:p>
   <text:p>10:10 Release checklist reviewed.</text:p>
   <text:p text:style-name="PB">Section 3 - Existing Action Notes</text:p>
   <text:p>Action notes from this section are archival only.</text:p>
   <text:p>Do not modify earlier sections during this task.</text:p>
   <text:p text:style-name="PB">Section 4 - Append New Tasks Below</text:p>
   <text:p>Append your new task list at the end of this document.</text:p>
   <text:p>Existing content ends here.</text:p>
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


class LibreOfficeNotesAppendPrepInitializer(BaseInitializer):
    """Seed notes.odt and launch LibreOffice to home screen."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for LibreOffice notes initializer",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", False))
        document_dir = str(params.get("document_dir") or DEFAULT_DOCUMENT_DIR).strip().rstrip("/")
        filename = str(params.get("filename") or DEFAULT_FILENAME).strip()
        remote_path = f"{document_dir}/{filename}"

        if not app_package or not app_activity or not filename:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package, app_activity, and filename",
            )

        try:
            ensure_app_installed(controller, app_package, label="LibreOffice")
            remove_path(controller, remote_path)
            payload = _build_notes_odt_bytes()
            push_bytes(controller, remote_path, payload)
            scan_media_paths(controller, [remote_path])

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
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare LibreOffice notes task: {type(exc).__name__}: {exc}",
                metadata={"remote_path": remote_path, "app_package": app_package},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="notes.odt seeded and LibreOffice launched",
            metadata={
                "remote_path": remote_path,
                "filename": filename,
                "document_dir": document_dir,
                "app_package": app_package,
            },
        )
