"""Initializer for resetting Thunderbird calendar state on Windows."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class ThunderbirdCalendarInitializer(BaseInitializer):
    """Remove Thunderbird profile data so calendar tasks start from a clean state."""

    DEFAULT_WAIT_MS = 6000

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_powershell_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_powershell_script is required")

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)

        reset_script = r"""
$ErrorActionPreference = "Stop"
$logPath = Join-Path $env:TEMP "helloworld_thunderbird_calendar_init.log"
Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue

function Write-InitLog {
  param([string]$Message)
  $line = "$(Get-Date -Format o) $Message"
  Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
  Write-Output $line
}

trap {
  Write-InitLog ("ERROR: " + $_.Exception.Message)
  Write-InitLog ("ERROR_POSITION: " + $_.InvocationInfo.PositionMessage)
  if (Test-Path $logPath) {
    Write-Output "===== helloworld_thunderbird_calendar_init.log ====="
    Get-Content -LiteralPath $logPath -ErrorAction SilentlyContinue
  }
  exit 1
}

Write-InitLog "begin thunderbird calendar reset"

Get-Process -Name "thunderbird" -ErrorAction SilentlyContinue |
  Stop-Process -Force -ErrorAction SilentlyContinue
for ($i = 0; $i -lt 30; $i++) {
  if (-not (Get-Process -Name "thunderbird" -ErrorAction SilentlyContinue)) {
    break
  }
  Start-Sleep -Milliseconds 500
}
Write-InitLog "existing thunderbird processes stopped"

$removeTargets = @(
  "$env:APPDATA\Thunderbird\Profiles",
  "$env:APPDATA\Thunderbird\profiles.ini",
  "$env:APPDATA\Thunderbird\installs.ini",
  "$env:LOCALAPPDATA\Thunderbird\Profiles"
)

foreach ($target in $removeTargets) {
  if (Test-Path $target) {
    Write-InitLog "removing $target"
    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
  } else {
    Write-InitLog "remove target absent $target"
  }
}

function Resolve-ThunderbirdExe {
  $tbExe = $null
  try {
    $cmd = Get-Command thunderbird.exe -ErrorAction Stop | Select-Object -First 1
    if ($cmd -and $cmd.Source) {
      $tbExe = $cmd.Source
    }
  } catch {
  }

  if (-not $tbExe) {
    $tbExe = @(
      "C:\Program Files\Mozilla Thunderbird\thunderbird.exe",
      "C:\Program Files (x86)\Mozilla Thunderbird\thunderbird.exe",
      "$env:LOCALAPPDATA\Programs\Thunderbird\thunderbird.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  }

  return $tbExe
}

function Ensure-ThunderbirdInstalled {
  $tbExe = Resolve-ThunderbirdExe
  if ($tbExe) {
    return $tbExe
  }

  $installerPath = Join-Path $env:TEMP "ThunderbirdSetup.exe"
  $mirrors = @(
    "https://download-installer.cdn.mozilla.net/pub/thunderbird/releases/115.12.1/win64/en-US/Thunderbird%20Setup%20115.12.1.exe",
    "https://archive.mozilla.org/pub/thunderbird/releases/115.12.1/win64/en-US/Thunderbird%20Setup%20115.12.1.exe"
  )

  foreach ($url in $mirrors) {
    try {
      Invoke-WebRequest -Uri $url -OutFile $installerPath -UseBasicParsing
      if (Test-Path $installerPath) {
        break
      }
    } catch {
    }
  }

  if (-not (Test-Path $installerPath)) {
    throw "Thunderbird executable not found and installer download failed"
  }

  Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait
  Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2

  $tbExe = Resolve-ThunderbirdExe
  if (-not $tbExe) {
    throw "Thunderbird executable not found"
  }
  return $tbExe
}

$tbExe = Ensure-ThunderbirdInstalled
Write-InitLog "resolved thunderbird exe: $tbExe"
$tbRoot = Join-Path $env:APPDATA "Thunderbird"
New-Item -ItemType Directory -Path $tbRoot -Force | Out-Null
$profileDir = Join-Path $tbRoot "Profiles\oracle.calendar.default"
New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
Write-InitLog "profile dir ready: $profileDir"

$profilesIni = @"
[General]
StartWithLastProfile=1
Version=2

[Profile0]
Name=oracle.calendar.default
IsRelative=1
Path=Profiles/oracle.calendar.default
Default=1
"@
Set-Content -LiteralPath (Join-Path $tbRoot "profiles.ini") -Value $profilesIni -Encoding ASCII
Write-InitLog "profiles.ini written"

$userJs = @(
  'user_pref("mailnews.start_page.enabled", false);',
  'user_pref("mailnews.start_page.url", "about:blank");',
  'user_pref("mailnews.start_page.override_url", "about:blank");',
  'user_pref("mailnews.start_page.override_url.mstone", "ignore");',
  'user_pref("app.update.postupdate", false);',
  'user_pref("browser.aboutwelcome.enabled", false);',
  'user_pref("mail.provider.enabled", false);',
  'user_pref("mail.provider.suppress_dialog_on_startup", true);'
)
Set-Content -LiteralPath (Join-Path $profileDir "user.js") -Value $userJs -Encoding ASCII
Write-InitLog "user.js written"

$proc = Start-Process -FilePath $tbExe -ArgumentList @("-profile", $profileDir, "-calendar") -PassThru
Write-InitLog "started thunderbird pid=$($proc.Id)"
Start-Sleep -Seconds 8
try {
  if ($proc.HasExited) {
    Write-InitLog "thunderbird exited early exit_code=$($proc.ExitCode)"
  } else {
    Write-InitLog "thunderbird still running after launch wait"
  }
} catch {
  Write-InitLog ("unable to inspect thunderbird process: " + $_.Exception.Message)
}
Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Write-InitLog "done thunderbird calendar reset"
Write-Output "===== helloworld_thunderbird_calendar_init.log ====="
Get-Content -LiteralPath $logPath -ErrorAction SilentlyContinue
"""

        try:
            result = controller.run_powershell_script(reset_script, timeout=300)
            returncode = int(result.get("returncode", 0))
            if returncode != 0:
                raise RuntimeError(str(result.get("error") or result.get("output") or "").strip() or f"exit code {returncode}")
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to reset Thunderbird calendar state: {exc}",
                metadata={"wait_ms": wait_ms},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Reset Thunderbird calendar state and launched app",
            metadata={"wait_ms": wait_ms},
        )
