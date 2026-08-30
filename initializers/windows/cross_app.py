"""Initializers for Windows cross-application tasks."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from .openshop import OpenShopInitializer
from .thunderbird_calendar import ThunderbirdCalendarInitializer


class OfficeThunderbirdInitializer(BaseInitializer):
    """Prepare a Writer document plus a configured Thunderbird compose window."""

    DEFAULT_TO = "bench-review@example.com"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "run_powershell_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_powershell_script is required")

        doc_name = str(params.get("doc_name") or "Bench_Status_Update.docx").strip()
        subject = str(params.get("subject") or "Bench PDF Review").strip()
        to_address = str(params.get("to") or self.DEFAULT_TO).strip()
        title = str(params.get("title") or "Bench Status Update").strip()
        body = params.get("body")
        if not isinstance(body, list) or not body:
            body = [
                "Prepared for the benchmark review.",
                "Please export and send the requested attachment.",
            ]

        try:
            script = self._build_script(
                doc_name=doc_name,
                subject=subject,
                to_address=to_address,
                title=title,
                body=[str(item) for item in body],
            )
            result = controller.run_powershell_script(script, timeout=180)
            returncode = int(result.get("returncode", -1)) if isinstance(result, Mapping) else -1
            if returncode != 0:
                output = str(result.get("output", "") if isinstance(result, Mapping) else "")
                return InitResult(status=InitStatus.ERROR, message=output or "Office/Thunderbird setup failed")
            time.sleep(float(params.get("final_wait_seconds", 5) or 0))
        except Exception as exc:
            return InitResult(status=InitStatus.ERROR, message=f"Failed to prepare Office/Thunderbird state: {exc}")

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Writer document and Thunderbird compose window",
            metadata={"doc_name": doc_name, "subject": subject, "to": to_address},
        )

    @staticmethod
    def _ps_single(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _build_script(self, *, doc_name: str, subject: str, to_address: str, title: str, body: list[str]) -> str:
        body_literal = "@(" + ",".join(self._ps_single(item) for item in body) + ")"
        return f"""
$ErrorActionPreference = "Stop"

Get-Process thunderbird,soffice,soffice.bin,msedge -ErrorAction SilentlyContinue |
  Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800

$smtpScriptPath = "$env:USERPROFILE\\fake_smtp_server.py"
$smtpLogDir = "$env:USERPROFILE\\fake_smtp_messages"
$smtpPidPath = "$env:USERPROFILE\\fake_smtp_server.pid"
if (Test-Path $smtpPidPath) {{
  $oldPid = (Get-Content -LiteralPath $smtpPidPath -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
  if ($oldPid -match '^\\d+$') {{ Stop-Process -Id ([int]$oldPid) -Force -ErrorAction SilentlyContinue }}
  Remove-Item -LiteralPath $smtpPidPath -Force -ErrorAction SilentlyContinue
}}
if (Test-Path $smtpLogDir) {{ Remove-Item -LiteralPath $smtpLogDir -Recurse -Force }}
New-Item -ItemType Directory -Path $smtpLogDir -Force | Out-Null

$smtpScript = @'
import asyncore
import pathlib
import smtpd
import time

OUTPUT_DIR = pathlib.Path.home() / "fake_smtp_messages"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

class RecordingServer(smtpd.SMTPServer):
    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        timestamp = int(time.time() * 1000)
        eml_path = OUTPUT_DIR / f"message_{{timestamp}}.eml"
        if isinstance(data, bytes):
            eml_path.write_bytes(data)
        else:
            eml_path.write_text(data, encoding="utf-8", errors="ignore")
        with (OUTPUT_DIR / "events.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{{timestamp}}\\t{{mailfrom}}\\t{{','.join(rcpttos)}}\\n")
        return None

server = RecordingServer(("127.0.0.1", 1025), None, decode_data=False)
asyncore.loop()
'@
Set-Content -LiteralPath $smtpScriptPath -Value $smtpScript -Encoding ASCII
$smtpProcess = Start-Process -FilePath "py" -ArgumentList @("-3", $smtpScriptPath) -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $smtpPidPath -Value $smtpProcess.Id -Encoding ASCII

$smtpReady = $false
for ($i = 0; $i -lt 20; $i++) {{
  try {{
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect("127.0.0.1", 1025)
    $client.Close()
    $smtpReady = $true
    break
  }} catch {{ Start-Sleep -Milliseconds 500 }}
}}
if (-not $smtpReady) {{ throw "Local fake SMTP server did not start" }}

$desktop = [Environment]::GetFolderPath("Desktop")
$docPath = Join-Path $desktop {self._ps_single(doc_name)}
$title = {self._ps_single(title)}
$bodyLines = {body_literal}

$createDoc = @'
import os
import subprocess
import sys
try:
    from docx import Document
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document
doc_path = os.environ["BENCH_DOC_PATH"]
title = os.environ["BENCH_DOC_TITLE"]
body = os.environ["BENCH_DOC_BODY"].split("\\n")
doc = Document()
doc.add_heading(title, level=1)
for line in body:
    doc.add_paragraph(line)
doc.save(doc_path)
print("DOC_CREATED", doc_path)
'@
$env:BENCH_DOC_PATH = $docPath
$env:BENCH_DOC_TITLE = $title
$env:BENCH_DOC_BODY = ($bodyLines -join "`n")
$createDoc | py -3 -W ignore -

$loUser = Join-Path $env:APPDATA "LibreOffice\\4\\user"
New-Item -ItemType Directory -Path $loUser -Force | Out-Null
@'
<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <item oor:path="/org.openoffice.Setup/Office">
    <prop oor:name="ooSetupInstCompleted" oor:op="fuse"><value>true</value></prop>
  </item>
</oor:items>
'@ | Set-Content -LiteralPath (Join-Path $loUser "registrymodifications.xcu") -Encoding UTF8

$tbRoot = Join-Path $env:APPDATA "Thunderbird"
if (Test-Path $tbRoot) {{ Remove-Item -LiteralPath $tbRoot -Recurse -Force }}
New-Item -ItemType Directory -Path $tbRoot -Force | Out-Null
$profileLeaf = "crossapp.default-release"
$profileDir = Join-Path $tbRoot $profileLeaf
New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
@"
[Profile0]
Name=default-release
IsRelative=1
Path=$profileLeaf
Default=1

[General]
StartWithLastProfile=1
Version=2
"@ | Set-Content -LiteralPath (Join-Path $tbRoot "profiles.ini") -Encoding ASCII
Set-Content -LiteralPath (Join-Path $tbRoot "installs.ini") -Value "" -Encoding ASCII

$localFoldersDir = Join-Path $profileDir "Mail\\Local Folders"
New-Item -ItemType Directory -Path $localFoldersDir -Force | Out-Null
foreach ($mailboxName in @("Drafts", "Sent", "Unsent Messages")) {{
  Set-Content -LiteralPath (Join-Path $localFoldersDir $mailboxName) -Value "" -Encoding UTF8
}}

@(
  'user_pref("app.update.auto", false);',
  'user_pref("app.update.enabled", false);',
  'user_pref("browser.shell.checkDefaultBrowser", false);',
  'user_pref("mail.account.account1.identities", "id1");',
  'user_pref("mail.account.account1.server", "server1");',
  'user_pref("mail.account.account2.server", "server2");',
  'user_pref("mail.account.lastKey", 2);',
  'user_pref("mail.accountmanager.accounts", "account1,account2");',
  'user_pref("mail.accountmanager.defaultaccount", "account1");',
  'user_pref("mail.accountmanager.localfoldersserver", "server2");',
  'user_pref("mail.identity.id1.fullName", "Helloworld");',
  'user_pref("mail.identity.id1.useremail", "Helloworld@outlook.com");',
  'user_pref("mail.identity.id1.smtpServer", "smtp1");',
  'user_pref("mail.identity.id1.valid", true);',
  'user_pref("mail.identity.id1.fcc", false);',
  'user_pref("mail.identity.id1.fcc_folder", "mailbox://nobody@Local%20Folders/Sent");',
  'user_pref("mail.identity.id1.draft_folder", "mailbox://nobody@Local%20Folders/Drafts");',
  'user_pref("mail.server.server1.hostname", "outlook.office365.com");',
  'user_pref("mail.server.server1.name", "Helloworld@outlook.com");',
  'user_pref("mail.server.server1.type", "imap");',
  'user_pref("mail.server.server1.userName", "Helloworld@outlook.com");',
  'user_pref("mail.server.server2.directory-rel", "[ProfD]Mail/Local Folders");',
  'user_pref("mail.server.server2.hostname", "Local Folders");',
  'user_pref("mail.server.server2.name", "Local Folders");',
  'user_pref("mail.server.server2.type", "none");',
  'user_pref("mail.smtp.defaultserver", "smtp1");',
  'user_pref("mail.smtpserver.smtp1.authMethod", 0);',
  'user_pref("mail.smtpserver.smtp1.hostname", "127.0.0.1");',
  'user_pref("mail.smtpserver.smtp1.port", 1025);',
  'user_pref("mail.smtpserver.smtp1.try_ssl", 0);',
  'user_pref("mail.smtpservers", "smtp1");',
  'user_pref("mail.compose.autosave", false);',
  'user_pref("mailnews.start_page.enabled", false);',
  'user_pref("mailnews.database.global.indexer.enabled", false);'
) | Set-Content -LiteralPath (Join-Path $profileDir "prefs.js") -Encoding ASCII

$loCandidates = @(
  "C:\\Program Files\\LibreOffice\\program\\soffice.exe",
  "C:\\Program Files (x86)\\LibreOffice\\program\\soffice.exe",
  "C:\\Program Files\\LibreOffice 26\\program\\soffice.exe"
)
$loExe = $loCandidates | Where-Object {{ Test-Path $_ }} | Select-Object -First 1
if (-not $loExe) {{
  $cmd = Get-Command soffice.exe -ErrorAction SilentlyContinue
  if ($cmd) {{ $loExe = $cmd.Source }}
}}
if ($loExe) {{
  Start-Process -FilePath $loExe -ArgumentList @("--writer", $docPath) | Out-Null
}} else {{
  Start-Process -FilePath $docPath | Out-Null
}}
Start-Sleep -Seconds 4

$composeSpec = "to='{to_address}',subject='{subject}'"
Start-Process -FilePath "thunderbird.exe" -ArgumentList @("-profile", $profileDir, "-compose", $composeSpec) | Out-Null
Start-Sleep -Seconds 6
try {{
  $wshell = New-Object -ComObject WScript.Shell
  $writerProc = Get-Process soffice.bin,soffice -ErrorAction SilentlyContinue |
    Where-Object {{ $_.MainWindowHandle -ne 0 }} |
    Sort-Object StartTime -Descending |
    Select-Object -First 1
  if ($writerProc) {{
    [void]$wshell.AppActivate($writerProc.Id)
  }}
}} catch {{}}
Write-Output "INIT_OK doc=$docPath subject={subject}"
"""


class ShoppingCalendarInitializer(BaseInitializer):
    """Prepare OpenShop state and an empty Thunderbird Calendar window."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        params = dict(context.get("params") or {})
        openshop_params = params.get("openshop") if isinstance(params.get("openshop"), Mapping) else {}
        calendar_params = params.get("calendar") if isinstance(params.get("calendar"), Mapping) else {}

        openshop_result = OpenShopInitializer().initialize({**context, "params": openshop_params})
        if openshop_result.status != InitStatus.PASS:
            return openshop_result

        calendar_result = ThunderbirdCalendarInitializer().initialize({**context, "params": calendar_params})
        if calendar_result.status != InitStatus.PASS:
            return calendar_result

        controller = context.get("controller")
        if controller is not None and hasattr(controller, "run_powershell_script"):
            controller.run_powershell_script(
                r"""
$ErrorActionPreference = "SilentlyContinue"
$wshell = New-Object -ComObject WScript.Shell
$proc = Get-Process -Name OpenShop,openshop |
  Where-Object { $_.MainWindowHandle -ne 0 } |
  Sort-Object StartTime -Descending |
  Select-Object -First 1
if ($proc) {
  [void]$wshell.AppActivate($proc.Id)
}
""",
                timeout=15,
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared OpenShop and Thunderbird Calendar",
            metadata={"openshop": openshop_result.metadata, "calendar": calendar_result.metadata},
        )
