$scriptFolder = @(
    (Join-Path $env:LOCALAPPDATA "Temp\HelloWorldRuntime"),
    "\\host.lan\Data",
    "\\vmware-host\Shared Folders\Data"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $scriptFolder) {
    $scriptFolder = "\\host.lan\Data"
}
$pythonScriptFile = "$scriptFolder\server\helloworld_server.py"
$pythonServerPort = 5000
$launcherCmd = "$scriptFolder\start-helloworld-server.cmd"
$watchdogScript = "$scriptFolder\watch-helloworld-server.ps1"

# Keep the task desktop clean. Windows shows both the user desktop and public
# desktop, so app installers can otherwise create visible dependency shortcuts.
$userDesktop = Join-Path $env:USERPROFILE "Desktop"
$publicDesktop = "C:\Users\Public\Desktop"
$dependencyFolder = Join-Path $userDesktop "Dependencies"
New-Item -ItemType Directory -Force -Path $dependencyFolder | Out-Null
$dependencySetupLink = Join-Path $dependencyFolder "Setup"
if (-not (Test-Path $dependencySetupLink)) {
    New-Item -ItemType SymbolicLink -Path $dependencySetupLink -Value $scriptFolder -ErrorAction SilentlyContinue | Out-Null
}
Get-ChildItem -LiteralPath $publicDesktop -Filter "*.lnk" -Force -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

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
        [string]$ShortcutFolder = $userDesktop
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

foreach ($desktopRoot in @($userDesktop, $publicDesktop)) {
    foreach ($shortcutName in @("Actual.lnk", "OpenShop clean.lnk", "Setup")) {
        $shortcutPath = Join-Path $desktopRoot $shortcutName
        if (Test-Path $shortcutPath) {
            Remove-Item -LiteralPath $shortcutPath -Force -Recurse -ErrorAction SilentlyContinue
        }
    }
}

# Windows merges the user and public desktops in Explorer. Keep benchmark app
# shortcuts in the Windows user's Desktop only, otherwise screenshots can show
# duplicate icons depending on which installer-created public shortcuts exist.
$benchmarkAppShortcuts = @(
    @{ Name = "Actual Budget.lnk"; Target = @("$env:LOCALAPPDATA\Programs\desktop-electron\Actual.exe", "$env:LOCALAPPDATA\Programs\Actual\Actual.exe", "C:\Program Files\Actual\Actual.exe") },
    @{ Name = "Blender 2.79b.lnk"; Target = "C:\Tools\Blender279b\blender-2.79b-windows64\blender.exe" },
    @{ Name = "DeltaChat.lnk"; Target = @("C:\Program Files\DeltaChat\DeltaChat.exe", "$env:LOCALAPPDATA\Programs\DeltaChat\DeltaChat.exe") },
    @{ Name = "draw.io.lnk"; Target = "C:\Program Files\draw.io\draw.io.exe" },
    @{ Name = "GIMP 2.10.38.lnk"; Target = "C:\Program Files\GIMP 2\bin\gimp-2.10.exe" },
    @{ Name = "Google Chrome.lnk"; Target = "C:\Program Files\Google\Chrome\Application\chrome.exe" },
    @{ Name = "LibreOffice 26.2.lnk"; Target = "C:\Program Files\LibreOffice\program\soffice.exe" },
    @{ Name = "Microsoft Edge.lnk"; Target = @("C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "C:\Program Files\Microsoft\Edge\Application\msedge.exe") },
    @{ Name = "OpenShop.lnk"; Target = "$env:LOCALAPPDATA\Programs\OpenShop\OpenShop.exe" },
    @{ Name = "Spotube.lnk"; Target = @("C:\Program Files\Spotube\spotube.exe", "C:\Program Files\Spotube\Spotube.exe", "$env:LOCALAPPDATA\Programs\Spotube\Spotube.exe") },
    @{ Name = "Thunderbird.lnk"; Target = @("C:\Program Files\Mozilla Thunderbird\thunderbird.exe", "C:\Program Files (x86)\Mozilla Thunderbird\thunderbird.exe") },
    @{ Name = "VLC media player.lnk"; Target = @("C:\Program Files\VideoLAN\VLC\vlc.exe", "C:\Program Files (x86)\VideoLAN\VLC\vlc.exe") },
    @{ Name = "Visual Studio Code.lnk"; Target = "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe" },
    @{ Name = "Wireshark.lnk"; Target = "C:\Program Files\Wireshark\Wireshark.exe" },
    @{ Name = "Zotero.lnk"; Target = "C:\Program Files\Zotero\zotero.exe" }
)

foreach ($shortcutSpec in $benchmarkAppShortcuts) {
    New-AppShortcut -ShortcutName $shortcutSpec.Name -TargetPath $shortcutSpec.Target -ShortcutFolder $userDesktop
    New-AppShortcut -ShortcutName $shortcutSpec.Name -TargetPath $shortcutSpec.Target -ShortcutFolder $dependencyFolder
}

# Prevent sleep/hibernate that can drop the runtime mid-task.
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change standby-timeout-dc 0 | Out-Null
powercfg /change monitor-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-dc 0 | Out-Null
powercfg /hibernate off | Out-Null

# Install runtime deps (first boot may need this; repeat is harmless).
if (Get-Command caddy -ErrorAction SilentlyContinue) {
    Write-Host "Running the Caddy reverse proxy from port 9222 to port 1337"
    Start-Process -NoNewWindow -FilePath "powershell" -ArgumentList "-NoProfile", "-Command", "caddy reverse-proxy --from :9222 --to :1337"
} else {
    Write-Host "Caddy not found; skipping reverse proxy startup."
}

Write-Host "Running the HelloWorld server on port $pythonServerPort..."
if (-not (Test-Path $watchdogScript)) {
    Write-Host "HelloWorld watchdog not found: $watchdogScript"
    exit 1
}

$existingWatchdog = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*watch-helloworld-server.ps1*" } |
    Select-Object -First 1
if (-not $existingWatchdog) {
    Start-Process -WindowStyle Hidden -FilePath "powershell" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $watchdogScript,
        "-ScriptFolder", $scriptFolder,
        "-Port", "$pythonServerPort"
    )
} else {
    Write-Host "HelloWorld watchdog already running: PID $($existingWatchdog.ProcessId)"
}
