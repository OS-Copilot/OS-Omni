"""Initializers for Android K-9 + document-editor cross-app tasks."""

from __future__ import annotations

import io
import zipfile
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.k9_seed_inbox_open import K9SeedInboxOpenInitializer
from initializers.android.mail_app_utils import launch_mail_or_chat_app, reset_k9_account_if_requested
from platforms.android.bench_storage_support import (
    allow_manage_external_storage,
    clear_and_launch_app,
    ensure_app_installed,
    grant_permissions,
    push_bytes,
    remove_path,
    scan_media_paths,
)


DEFAULT_K9_PACKAGE = "com.fsck.k9"
DEFAULT_K9_ACTIVITY = "net.thunderbird.app.common.MainActivity"
DEFAULT_LIBREOFFICE_PACKAGE = "org.documentfoundation.libreoffice"
DEFAULT_LIBREOFFICE_ACTIVITY = "org.libreoffice.ui.LibreOfficeUIActivity"
DEFAULT_MARKOR_PACKAGE = "net.gsantner.markor"
DEFAULT_MARKOR_ACTIVITY = "net.gsantner.markor.activity.MainActivity"
DEFAULT_DOCUMENT_DIR = "/sdcard/Documents"
DEFAULT_MARKOR_DOCUMENT_DIR = "/sdcard/Documents/markor"
DEFAULT_SMTP_HOST = "127.0.0.1"
DEFAULT_SMTP_PORT = 3025
DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"


class EmailOfficeCrossAppInitializer(BaseInitializer):
    """Seed GreenMail plus a document file, then open the requested app."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Email+Office initialization",
            )

        api_base_url = str(params.get("api_base_url") or DEFAULT_API_BASE_URL).rstrip("/")
        k9_package = str(params.get("k9_package") or DEFAULT_K9_PACKAGE).strip()
        k9_activity = str(params.get("k9_activity") or DEFAULT_K9_ACTIVITY).strip()
        office_package = str(params.get("office_package") or DEFAULT_LIBREOFFICE_PACKAGE).strip()
        office_activity = str(params.get("office_activity") or DEFAULT_LIBREOFFICE_ACTIVITY).strip()
        markor_package = str(params.get("markor_package") or DEFAULT_MARKOR_PACKAGE).strip()
        markor_activity = str(params.get("markor_activity") or DEFAULT_MARKOR_ACTIVITY).strip()
        document_format = str(params.get("document_format") or "odt").strip().lower()
        default_document_dir = DEFAULT_MARKOR_DOCUMENT_DIR if document_format in {"text", "markdown", "md"} else DEFAULT_DOCUMENT_DIR
        document_dir = str(params.get("document_dir") or default_document_dir).strip().rstrip("/")
        filename = str(params.get("filename") or "bench_cross_app.odt").strip()
        remote_path = f"{document_dir}/{filename}"
        open_app = str(params.get("open_app") or "k9").strip().lower()
        wait_ms = int(params.get("wait_ms", 1800) or 0)
        purge_greenmail = bool(params.get("purge_greenmail", True))
        clear_office_data = bool(params.get("clear_office_data", False))

        seed_messages = params.get("seed_messages") or []
        if not isinstance(seed_messages, list):
            return InitResult(status=InitStatus.FAIL, message="seed_messages must be a list")

        try:
            self._ensure_mail_reverse(controller)
            K9SeedInboxOpenInitializer._ensure_greenmail_ready(api_base_url)
            reset_k9_account_if_requested(
                controller,
                params,
                api_base_url=api_base_url,
            )
            if purge_greenmail:
                K9SeedInboxOpenInitializer._purge_greenmail(api_base_url)

            ensure_app_installed(controller, k9_package, label="K-9 Mail")
            if document_format in {"text", "markdown", "md"} or open_app == "markor":
                ensure_app_installed(controller, markor_package, label="Markor")
            else:
                ensure_app_installed(controller, office_package, label="LibreOffice")

            for item in seed_messages:
                if not isinstance(item, Mapping):
                    continue
                K9SeedInboxOpenInitializer._send_seed_email(
                    smtp_host=str(item.get("smtp_host") or DEFAULT_SMTP_HOST),
                    smtp_port=int(item.get("smtp_port") or DEFAULT_SMTP_PORT),
                    sender_email=str(item.get("sender_email") or "").strip(),
                    sender_password=str(item.get("sender_password") or "").strip(),
                    recipient_email=str(item.get("recipient_email") or "benchsender@example.test").strip(),
                    subject=str(item.get("subject") or "").strip(),
                    body=str(item.get("body") or ""),
                )

            remove_path(controller, remote_path)
            if document_format in {"text", "markdown", "md"}:
                payload = _build_text_bytes(params.get("document_lines") or [])
            else:
                payload = _build_odt_bytes(
                    params.get("document_lines") or [],
                    font_size_pt=params.get("font_size_pt", 24),
                )
            push_bytes(controller, remote_path, payload)
            scan_media_paths(controller, [remote_path])

            editor_package = markor_package if document_format in {"text", "markdown", "md"} else office_package
            grant_permissions(
                controller,
                editor_package,
                [
                    "android.permission.READ_EXTERNAL_STORAGE",
                    "android.permission.WRITE_EXTERNAL_STORAGE",
                ],
            )
            allow_manage_external_storage(controller, editor_package)

            if open_app in {"office", "libreoffice"}:
                clear_and_launch_app(
                    controller,
                    app_package=office_package,
                    app_activity=office_activity,
                    clear_app_data=clear_office_data,
                    wait_ms=wait_ms,
                )
            elif open_app == "markor":
                clear_and_launch_app(
                    controller,
                    app_package=markor_package,
                    app_activity=markor_activity,
                    clear_app_data=bool(params.get("clear_markor_data", False)),
                    wait_ms=wait_ms,
                )
            else:
                ok, focus_output = launch_mail_or_chat_app(
                    controller,
                    app_package=k9_package,
                    app_activity=k9_activity,
                    label="K-9 Mail",
                    wait_ms=wait_ms,
                )
                if not ok:
                    raise RuntimeError(
                        f"K-9 did not become the foreground app: {focus_output or 'no focus output'}"
                    )
                if bool(params.get("refresh_k9_inbox", True)):
                    K9SeedInboxOpenInitializer._refresh_k9_inbox(
                        controller=controller,
                        attempts=int(params.get("refresh_attempts", 2) or 0),
                        pause_ms=int(params.get("refresh_pause_ms", 1200) or 0),
                    )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Email+Office task: {type(exc).__name__}: {exc}",
                metadata={"remote_path": remote_path, "open_app": open_app},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="GreenMail and document file prepared",
            metadata={
                "api_base_url": api_base_url,
                "remote_path": remote_path,
                "seed_message_count": len(seed_messages),
                "open_app": open_app,
                "document_format": document_format,
                "reset_k9_app_data": bool(params.get("reset_app_data", False)),
            },
        )

    @staticmethod
    def _ensure_mail_reverse(controller: Any) -> None:
        for port in ("3143", "3025"):
            controller.execute_adb(["reverse", f"tcp:{port}", f"tcp:{port}"])


def _build_odt_bytes(raw_lines: Any, *, font_size_pt: Any = 24) -> bytes:
    lines = [str(line) for line in raw_lines if str(line).strip()] if isinstance(raw_lines, list) else []
    if not lines:
        lines = ["HelloWorld Email Office Benchmark"]

    try:
        resolved_font_size = min(max(int(font_size_pt), 12), 48)
    except (TypeError, ValueError):
        resolved_font_size = 24

    escaped = [_xml_escape(line) for line in lines]
    paragraphs = "\n".join(f'   <text:p text:style-name="BMKLarge">{line}</text:p>' for line in escaped)
    mimetype = "application/vnd.oasis.opendocument.text"
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
 office:version="1.2">
 <office:automatic-styles>
  <style:style style:name="BMKLarge" style:family="paragraph">
   <style:text-properties fo:font-size="{resolved_font_size}pt"/>
  </style:style>
 </office:automatic-styles>
 <office:body>
  <office:text>
{paragraphs}
  </office:text>
 </office:body>
</office:document-content>
"""
    manifest_xml = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
 manifest:version="1.2">
 <manifest:file-entry manifest:media-type="application/vnd.oasis.opendocument.text" manifest:full-path="/"/>
 <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>
</manifest:manifest>
"""
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, mode="w") as zf:
        zf.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("META-INF/manifest.xml", manifest_xml, compress_type=zipfile.ZIP_DEFLATED)
    return buff.getvalue()


def _build_text_bytes(raw_lines: Any) -> bytes:
    lines = [str(line) for line in raw_lines if str(line).strip()] if isinstance(raw_lines, list) else []
    if not lines:
        lines = ["HelloWorld Email Document Benchmark"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
