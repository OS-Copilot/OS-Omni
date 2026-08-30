$ErrorActionPreference = "Stop"

function Stop-AppProcesses {
    param(
        [string[]]$Names
    )

    foreach ($name in $Names) {
        Stop-Process -Name $name -Force -ErrorAction SilentlyContinue
    }
}

function Remove-IfExists {
    param(
        [string]$Path
    )

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Clear-DirectoryContents {
    param(
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

function Resolve-FirstExistingPath {
    param(
        [string[]]$Paths
    )

    foreach ($path in $Paths) {
        $expanded = [Environment]::ExpandEnvironmentVariables($path)
        if (Test-Path $expanded) {
            return $expanded
        }
    }
    return $null
}

function New-AppShortcut {
    param(
        [string]$ShortcutName,
        [string[]]$TargetPath,
        [string]$ShortcutFolder
    )

    $resolvedTargetPath = Resolve-FirstExistingPath -Paths $TargetPath
    if (-not $resolvedTargetPath) {
        return
    }

    New-Item -ItemType Directory -Force -Path $ShortcutFolder | Out-Null
    $shortcutPath = Join-Path $ShortcutFolder $ShortcutName
    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $resolvedTargetPath
    $shortcut.WorkingDirectory = Split-Path -Path $resolvedTargetPath -Parent
    $shortcut.IconLocation = "$resolvedTargetPath,0"
    $shortcut.Save()
}

function Remove-RegistryKeyIfExists {
    param(
        [string]$Path
    )

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Closing common user-facing apps..."
Stop-AppProcesses -Names @(
    "OpenShop",
    "spotube",
    "Time",
    "ApplicationFrameHost",
    "msedge",
    "chrome",
    "Code",
    "blender",
    "draw.io",
    "marble-qt",
    "gimp-2.10",
    "thunderbird",
    "DeltaChat",
    "vlc",
    "Wireshark",
    "zotero",
    "Zotero",
    "OneDrive",
    "swriter",
    "scalc",
    "simpress",
    "soffice",
    "soffice.bin",
    "notepad",
    "mspaint",
    "calc",
    "Actual",
    "Actual Budget",
    "actual-server"
)

Write-Host "Resetting common app user state..."
$appStatePaths = @(
    "$env:APPDATA\Blender Foundation\Blender\2.79",
    "$env:APPDATA\Code\User\globalStorage",
    "$env:APPDATA\Code\User\History",
    "$env:APPDATA\Code\User\workspaceStorage",
    "$env:APPDATA\DeltaChat",
    "$env:APPDATA\draw.io",
    "$env:APPDATA\GIMP",
    "$env:APPDATA\Mozilla",
    "$env:APPDATA\OpenShop",
    "$env:APPDATA\Thunderbird",
    "$env:APPDATA\Wireshark",
    "$env:APPDATA\Zotero",
    "$env:LOCALAPPDATA\Blender Foundation\Blender\2.79",
    "$env:LOCALAPPDATA\Code\Cache",
    "$env:LOCALAPPDATA\Code\CachedData",
    "$env:LOCALAPPDATA\Code\CachedExtensionVSIXs",
    "$env:LOCALAPPDATA\Code\CachedProfilesData",
    "$env:LOCALAPPDATA\Code\Crashpad",
    "$env:LOCALAPPDATA\Code\GPUCache",
    "$env:LOCALAPPDATA\Code\logs",
    "$env:LOCALAPPDATA\DeltaChat",
    "$env:LOCALAPPDATA\draw.io",
    "$env:LOCALAPPDATA\GIMP",
    "$env:LOCALAPPDATA\Google\Chrome\User Data",
    "$env:LOCALAPPDATA\Mozilla",
    "$env:LOCALAPPDATA\Microsoft\Edge\User Data",
    "$env:LOCALAPPDATA\OpenShop",
    "$env:LOCALAPPDATA\Thunderbird",
    "$env:USERPROFILE\.gimp-2.10",
    "$env:USERPROFILE\Zotero"
)
foreach ($path in $appStatePaths) {
    Remove-IfExists -Path $path
}
Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\Temp" -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "scoped_dir*" } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Clearing Windows user MRU state..."
$registryStatePaths = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\CIDSizeMRU",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\FirstFolder",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\LastVisitedPidlMRU",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Search\RecentApps",
    "HKCU:\Software\Microsoft\Windows\Shell\BagMRU",
    "HKCU:\Software\Microsoft\Windows\Shell\Bags",
    "HKCU:\Software\Microsoft\Windows\ShellNoRoam\BagMRU",
    "HKCU:\Software\Microsoft\Windows\ShellNoRoam\Bags"
)
foreach ($path in $registryStatePaths) {
    Remove-RegistryKeyIfExists -Path $path
}

$vscodeSettingsPath = Join-Path $env:APPDATA "Code\User\settings.json"
New-Item -ItemType Directory -Force -Path (Split-Path -Path $vscodeSettingsPath -Parent) | Out-Null
@{
    "telemetry.telemetryLevel" = "off"
    "update.mode" = "none"
    "extensions.autoUpdate" = $false
    "extensions.autoCheckUpdates" = $false
} | ConvertTo-Json | Set-Content -Path $vscodeSettingsPath -Encoding UTF8

$windowsRecentPaths = @(
    "$env:APPDATA\Microsoft\Windows\Recent",
    "$env:APPDATA\Microsoft\Windows\Recent\AutomaticDestinations",
    "$env:APPDATA\Microsoft\Windows\Recent\CustomDestinations"
)
foreach ($path in $windowsRecentPaths) {
    Clear-DirectoryContents -Path $path
}

Write-Host "Resetting Spotube to a generic clean state..."
@'
import json
import pathlib
import sqlite3

app_dir = pathlib.Path(r"C:\Users\User\AppData\Roaming\oss.krtirtho\spotube")
app_dir.mkdir(parents=True, exist_ok=True)

prefs_path = app_dir / "shared_preferences.json"
prefs_path.write_text(
    json.dumps(
        {
            "doneGettingStarted": False,
            "flutter.windowSize": "{\"height\":802.0,\"width\":1202.0,\"maximized\":false}",
        }
    ),
    encoding="utf-8",
)

db_path = app_dir / "db.sqlite"
if db_path.exists():
    db_path.unlink()

conn = sqlite3.connect(db_path)
conn.execute(
    '''
    CREATE TABLE IF NOT EXISTS preferences_table (
      id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
      album_color_sync INTEGER NOT NULL DEFAULT 1,
      amoled_dark_theme INTEGER NOT NULL DEFAULT 0,
      check_update INTEGER NOT NULL DEFAULT 1,
      normalize_audio INTEGER NOT NULL DEFAULT 0,
      show_system_tray_icon INTEGER NOT NULL DEFAULT 0,
      system_title_bar INTEGER NOT NULL DEFAULT 0,
      skip_non_music INTEGER NOT NULL DEFAULT 0,
      close_behavior TEXT NOT NULL DEFAULT 'close',
      accent_color_scheme TEXT NOT NULL DEFAULT 'Slate:0xff64748b',
      layout_mode TEXT NOT NULL DEFAULT 'adaptive',
      locale TEXT NOT NULL DEFAULT '{"languageCode":"system","countryCode":"system"}',
      market TEXT NOT NULL DEFAULT 'US',
      search_mode TEXT NOT NULL DEFAULT 'youtube',
      download_location TEXT NOT NULL DEFAULT 'C:\\Users\\User\\Downloads\\Spotube',
      local_library_location TEXT NOT NULL DEFAULT '',
      theme_mode TEXT NOT NULL DEFAULT 'system',
      audio_source_id TEXT NULL,
      youtube_client_engine TEXT NOT NULL DEFAULT 'newPipe',
      discord_presence INTEGER NOT NULL DEFAULT 1,
      endless_playback INTEGER NOT NULL DEFAULT 1,
      enable_connect INTEGER NOT NULL DEFAULT 0,
      connect_port INTEGER NOT NULL DEFAULT -1,
      cache_music INTEGER NOT NULL DEFAULT 1
    )
    '''
)
conn.execute(
    """
    INSERT INTO preferences_table (
      id, album_color_sync, amoled_dark_theme, check_update,
      normalize_audio, show_system_tray_icon, system_title_bar,
      skip_non_music, close_behavior, accent_color_scheme,
      layout_mode, locale, market, search_mode, download_location,
      local_library_location, theme_mode, audio_source_id,
      youtube_client_engine, discord_presence, endless_playback,
      enable_connect, connect_port, cache_music
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        0, 1, 0, 1, 0, 0, 0, 0, "close", "Slate:0xff64748b",
        "adaptive", '{"languageCode":"system","countryCode":"system"}',
        "US", "youtube", r"C:\Users\User\Downloads\Spotube", "",
        "system", None, "newPipe", 1, 1, 0, -1, 1,
    ),
)
conn.commit()
conn.close()

for extra_name in ("spotube_downloads.json", "spotube_logs.txt"):
    extra_path = app_dir / extra_name
    if extra_path.exists():
        extra_path.unlink()
'@ | py -3 -

Write-Host "Resetting Actual Budget to a generic clean state..."
$actualPaths = @(
    "$env:APPDATA\Actual",
    "$env:LOCALAPPDATA\actual",
    "$env:APPDATA\actual",
    "$env:USERPROFILE\Documents\Actual"
)
foreach ($path in $actualPaths) {
    if (Test-Path $path) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Resetting LibreOffice user state..."
$libreOfficeUser = Join-Path $env:APPDATA "LibreOffice\4\user"
$libreOfficePaths = @(
    (Join-Path $libreOfficeUser "config"),
    (Join-Path $libreOfficeUser "backup"),
    (Join-Path $libreOfficeUser "temp"),
    (Join-Path $libreOfficeUser "autocorr"),
    (Join-Path $libreOfficeUser "basic"),
    (Join-Path $libreOfficeUser "registrymodifications.xcu")
)
foreach ($path in $libreOfficePaths) {
    Remove-IfExists -Path $path
}

$libreOfficeRegistry = Join-Path $libreOfficeUser "registrymodifications.xcu"
New-Item -ItemType Directory -Path $libreOfficeUser -Force | Out-Null
@'
<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <item oor:path="/org.openoffice.Setup/Office">
    <prop oor:name="ooSetupInstCompleted" oor:op="fuse"><value>true</value></prop>
  </item>
</oor:items>
'@ | Set-Content -LiteralPath $libreOfficeRegistry -Encoding UTF8

$loSearchRoots = @(
    "$env:USERPROFILE\Desktop",
    "$env:USERPROFILE\Documents",
    "$env:USERPROFILE\Downloads",
    "$env:TEMP"
)
foreach ($root in $loSearchRoots) {
    if (-not (Test-Path $root)) {
        continue
    }
    Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like ".~lock*" -or
            $_.Name -like "*.tmp" -or
            $_.Name -like "*.bak"
        } |
        Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
}

Write-Host "Removing task output leftovers..."
$taskStatePaths = @(
    "$env:USERPROFILE\Documents\Actual",
    "$env:USERPROFILE\Documents\blender_tasks",
    "$env:USERPROFILE\Documents\ops_handoff_workspace",
    "$env:USERPROFILE\Documents\release_cleanup_workspace",
    "$env:USERPROFILE\Downloads\_incoming",
    "$env:USERPROFILE\Downloads\http_objects",
    "$env:USERPROFILE\Downloads\Spotube"
)
foreach ($path in $taskStatePaths) {
    Remove-IfExists -Path $path
}

$taskOutputFiles = @(
    "$env:USERPROFILE\Documents\drawio_ellipse_vertical_divider_styled.drawio",
    "$env:USERPROFILE\Documents\drawio_square_center_helloworld.drawio",
    "$env:USERPROFILE\Documents\drawio_sum_loop_flowchart.drawio",
    "$env:USERPROFILE\Downloads\announcement.docx",
    "$env:USERPROFILE\Downloads\app.ini",
    "$env:USERPROFILE\Downloads\apple_and_orange_focus_blur_submission.jpg",
    "$env:USERPROFILE\Downloads\apple_and_orange_focus_blur_submission.jpg.jpg",
    "$env:USERPROFILE\Downloads\apple_and_orange_focus_blur_submission.jpg.png",
    "$env:USERPROFILE\Downloads\apple_and_orange_focus_blur_submission.png",
    "$env:USERPROFILE\Downloads\apple_and_orange_focus_blur_submission.png.jpg",
    "$env:USERPROFILE\Downloads\apple_and_orange_focus_blur_submission.png.png",
    "$env:USERPROFILE\Downloads\Apple_and_Orange.jpg",
    "$env:USERPROFILE\Downloads\Apple_and_Orange_expected.png",
    "$env:USERPROFILE\Downloads\Background_Scene.png",
    "$env:USERPROFILE\Downloads\Cartoon_Girl.png",
    "$env:USERPROFILE\Downloads\cartoon_girl_blend_submission.jpg",
    "$env:USERPROFILE\Downloads\cartoon_girl_blend_submission.jpg.jpg",
    "$env:USERPROFILE\Downloads\cartoon_girl_blend_submission.jpg.png",
    "$env:USERPROFILE\Downloads\cartoon_girl_blend_submission.png",
    "$env:USERPROFILE\Downloads\cartoon_girl_blend_submission.png.jpg",
    "$env:USERPROFILE\Downloads\cartoon_girl_blend_submission.png.png",
    "$env:USERPROFILE\Downloads\Composite_Expected.png",
    "$env:USERPROFILE\Downloads\conference.pptx",
    "$env:USERPROFILE\Downloads\diagram.png",
    "$env:USERPROFILE\Downloads\gimp_center_helloworld.png",
    "$env:USERPROFILE\Downloads\gimp_center_helloworld.png.png",
    "$env:USERPROFILE\Downloads\guest.txt",
    "$env:USERPROFILE\Downloads\hosts.txt",
    "$env:USERPROFILE\Downloads\http_only.pcapng",
    "$env:USERPROFILE\Downloads\ipv4_conversations.txt",
    "$env:USERPROFILE\Downloads\kickoff.pptx",
    "$env:USERPROFILE\Downloads\logo.png",
    "$env:USERPROFILE\Downloads\manual.docx",
    "$env:USERPROFILE\Downloads\protocol_hierarchy.txt",
    "$env:USERPROFILE\Downloads\quarterly.xlsx",
    "$env:USERPROFILE\Downloads\report.docx",
    "$env:USERPROFILE\Downloads\sales.xlsx",
    "$env:USERPROFILE\Downloads\sample.pcapng",
    "$env:USERPROFILE\Downloads\sample_object.html",
    "$env:USERPROFILE\Downloads\scores.xlsx",
    "$env:USERPROFILE\Downloads\tcp80.pcapng",
    "$env:USERPROFILE\Downloads\training.pptx"
)
foreach ($path in $taskOutputFiles) {
    Remove-IfExists -Path $path
}

Write-Host "Clearing temporary files, clipboard, and recycle bin..."
foreach ($path in @($env:TEMP, "$env:LOCALAPPDATA\Temp", "C:\Windows\Temp")) {
    Clear-DirectoryContents -Path $path
}
try {
    Set-Clipboard -Value " " -ErrorAction Stop
} catch {
    Write-Host "Warning: clipboard could not be cleared: $($_.Exception.Message)"
}
Clear-RecycleBin -Force -ErrorAction SilentlyContinue

Write-Host "Cleaning recent-user clutter..."
$desktop = "C:\Users\$env:USERNAME\Desktop"
$publicDesktop = "C:\Users\Public\Desktop"
$dependencyFolder = Join-Path $desktop "Dependencies"
$obsoleteDesktopItems = @(
    "Actual.lnk",
    "OpenShop clean.lnk",
    "Setup",
    "blender_gui_verify.bat",
    "blender_init_probe.ps1",
    "blender_mesa_verify.bat",
    "blender_root_compat.bat",
    "blender_root_verify.bat"
)
foreach ($root in @($desktop, $publicDesktop)) {
    foreach ($item in $obsoleteDesktopItems) {
        $path = Join-Path $root $item
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Force -Recurse -ErrorAction SilentlyContinue
        }
    }
}
New-Item -ItemType Directory -Force -Path $dependencyFolder | Out-Null
Get-ChildItem -LiteralPath $publicDesktop -Filter "*.lnk" -Force -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

$benchmarkAppShortcuts = @(
    @{ Name = "Actual Budget.lnk"; Target = @("$env:LOCALAPPDATA\Programs\desktop-electron\Actual.exe", "$env:LOCALAPPDATA\Programs\Actual\Actual.exe", "C:\Program Files\Actual\Actual.exe") },
    @{ Name = "Blender 2.79b.lnk"; Target = "C:\Tools\Blender279b\blender-2.79b-windows64\blender.exe" },
    @{ Name = "DeltaChat.lnk"; Target = @("C:\Program Files\DeltaChat\DeltaChat.exe", "$env:LOCALAPPDATA\Programs\DeltaChat\DeltaChat.exe") },
    @{ Name = "draw.io.lnk"; Target = "C:\Program Files\draw.io\draw.io.exe" },
    @{ Name = "GIMP 2.10.38.lnk"; Target = "C:\Program Files\GIMP 2\bin\gimp-2.10.exe" },
    @{ Name = "Google Chrome.lnk"; Target = "C:\Program Files\Google\Chrome\Application\chrome.exe" },
    @{ Name = "LibreOffice 26.2.lnk"; Target = "C:\Program Files\LibreOffice\program\soffice.exe" },
    @{ Name = "Microsoft Edge.lnk"; Target = @("C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "C:\Program Files\Microsoft\Edge\Application\msedge.exe") },
    @{ Name = "Marble.lnk"; Target = "C:\Program Files (x86)\Marble\marble-qt.exe" },
    @{ Name = "OpenShop.lnk"; Target = "$env:LOCALAPPDATA\Programs\OpenShop\OpenShop.exe" },
    @{ Name = "Spotube.lnk"; Target = @("C:\Program Files\Spotube\spotube.exe", "C:\Program Files\Spotube\Spotube.exe", "$env:LOCALAPPDATA\Programs\Spotube\Spotube.exe") },
    @{ Name = "Thunderbird.lnk"; Target = @("C:\Program Files\Mozilla Thunderbird\thunderbird.exe", "C:\Program Files (x86)\Mozilla Thunderbird\thunderbird.exe") },
    @{ Name = "VLC media player.lnk"; Target = @("C:\Program Files\VideoLAN\VLC\vlc.exe", "C:\Program Files (x86)\VideoLAN\VLC\vlc.exe") },
    @{ Name = "Visual Studio Code.lnk"; Target = "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe" },
    @{ Name = "Wireshark.lnk"; Target = "C:\Program Files\Wireshark\Wireshark.exe" },
    @{ Name = "Zotero.lnk"; Target = "C:\Program Files\Zotero\zotero.exe" }
)

foreach ($shortcutSpec in $benchmarkAppShortcuts) {
    New-AppShortcut -ShortcutName $shortcutSpec.Name -TargetPath $shortcutSpec.Target -ShortcutFolder $desktop
    New-AppShortcut -ShortcutName $shortcutSpec.Name -TargetPath $shortcutSpec.Target -ShortcutFolder $dependencyFolder
}

$desktopTaskFiles = @(
    "DeltaChatSendMessageOracleProof.json",
    "DeltaChatShareSyncOracleProof.json",
    "LaunchDebriefOracleProof.txt",
    "thunderbird_open_eval.py"
)
foreach ($root in @($desktop, $publicDesktop)) {
    foreach ($item in $desktopTaskFiles) {
        Remove-IfExists -Path (Join-Path $root $item)
    }
}
Remove-IfExists -Path (Join-Path $env:USERPROFILE "thunderbird_open_eval.py")

@'
import json
import pathlib
from datetime import datetime, timezone

status_path = pathlib.Path.home() / "cleanup-generic-state.last.json"
status_path.write_text(
    json.dumps(
        {
            "cleaned_at_utc": datetime.now(timezone.utc).isoformat(),
            "spotube_done_getting_started": False,
            "spotube_theme_mode": "system",
            "spotube_normalize_audio": 0,
            "spotube_market": "US",
            "spotube_youtube_client_engine": "newPipe",
            "spotube_endless_playback": 1,
            "actual_budget_reset": True,
            "app_user_state_reset": True,
            "desktop_task_files_removed": True,
            "libreoffice_user_state_reset": True,
            "registry_mru_state_reset": True,
            "temp_clipboard_recycle_bin_cleared": True,
            "task_output_leftovers_removed": True,
        },
        indent=2,
    ),
    encoding="utf-8",
)
'@ | py -3 -

Write-Host "Generic cleanup completed."
