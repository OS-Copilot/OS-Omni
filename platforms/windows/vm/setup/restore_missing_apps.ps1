$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Download-FromMirrors {
    param(
        [string[]]$Urls,
        [string]$OutFile
    )

    foreach ($url in $Urls) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $OutFile -UseBasicParsing -Headers @{ "User-Agent" = "Mozilla/5.0" }
            if (Test-Path $OutFile) {
                return $true
            }
        } catch {
        }
    }
    return $false
}

function Remove-IfExists {
    param([string]$Path)
    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Force -Recurse -ErrorAction SilentlyContinue
    }
}

function Ensure-DependencyShortcut {
    param(
        [string]$ShortcutName,
        [string]$TargetPath,
        [string]$WorkingDirectory
    )

    if (-not (Test-Path $TargetPath)) {
        return
    }

    $folder = Join-Path $env:USERPROFILE "Desktop\Dependencies"
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $shortcutPath = Join-Path $folder $ShortcutName
    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Save()
}

function Ensure-VisualCpp2013Runtime {
    $dllPaths = @(
        "$env:WINDIR\System32\MSVCP120.dll",
        "$env:WINDIR\SysWOW64\MSVCP120.dll"
    )
    $missingDll = $dllPaths | Where-Object { -not (Test-Path $_) } | Select-Object -First 1
    if (-not $missingDll) {
        Write-Output "VCRUNTIME2013_OK=True"
        return
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Warning "winget is not available; cannot install Visual C++ 2013 runtime."
        Write-Output "VCRUNTIME2013_OK=False"
        return
    }

    winget install --id Microsoft.VCRedist.2013.x64 -e --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
    winget install --id Microsoft.VCRedist.2013.x86 -e --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
    $missingDll = $dllPaths | Where-Object { -not (Test-Path $_) } | Select-Object -First 1
    Write-Output "VCRUNTIME2013_OK=$($null -eq $missingDll)"
}

function Install-BlenderSoftwareOpenGL {
    param([string]$BlenderExe)

    if (-not (Test-Path $BlenderExe)) {
        return
    }

    $blenderDir = Split-Path -Path $BlenderExe -Parent
    $requiredDlls = @("opengl32.dll", "libglapi.dll", "libgallium_wgl.dll")
    $missingDll = $requiredDlls | Where-Object { -not (Test-Path (Join-Path $blenderDir $_)) } | Select-Object -First 1
    if ($null -eq $missingDll) {
        Write-Output "BLENDER_MESA_OK=True"
        return
    }

    $mesaArchive = Join-Path $env:TEMP "mesa3d-24.0.3-release-msvc.7z"
    $mesaExtract = Join-Path $env:TEMP "mesa3d-24.0.3"
    Remove-IfExists $mesaArchive
    Remove-IfExists $mesaExtract
    New-Item -ItemType Directory -Force -Path $mesaExtract | Out-Null

    $mesaUrls = @(
        "https://github.com/pal1000/mesa-dist-win/releases/download/24.0.3/mesa3d-24.0.3-release-msvc.7z"
    )
    if (-not (Download-FromMirrors -Urls $mesaUrls -OutFile $mesaArchive)) {
        Write-Warning "Failed to download Mesa3D software OpenGL runtime."
        return
    }

    $extracted = $false
    if (Get-Command tar -ErrorAction SilentlyContinue) {
        try {
            & tar -xf $mesaArchive -C $mesaExtract "x64/opengl32.dll" "x64/libglapi.dll" "x64/libgallium_wgl.dll"
            $extracted = Test-Path (Join-Path $mesaExtract "x64\opengl32.dll")
        } catch {
            $extracted = $false
        }
    }

    if (-not $extracted) {
        $sevenZip = Join-Path $env:TEMP "7zr.exe"
        if (Download-FromMirrors -Urls @("https://www.7-zip.org/a/7zr.exe") -OutFile $sevenZip) {
            & $sevenZip x $mesaArchive "-o$mesaExtract" "x64\opengl32.dll" "x64\libglapi.dll" "x64\libgallium_wgl.dll" -y | Out-Null
            $extracted = Test-Path (Join-Path $mesaExtract "x64\opengl32.dll")
        }
    }

    if ($extracted) {
        foreach ($dll in $requiredDlls) {
            Copy-Item -LiteralPath (Join-Path $mesaExtract "x64\$dll") -Destination (Join-Path $blenderDir $dll) -Force
        }
        [Environment]::SetEnvironmentVariable("MESA_LOADER_DRIVER_OVERRIDE", "llvmpipe", "Machine")
        [Environment]::SetEnvironmentVariable("LIBGL_ALWAYS_SOFTWARE", "1", "Machine")
    } else {
        Write-Warning "Failed to extract Mesa3D software OpenGL runtime."
    }

    Remove-IfExists $mesaArchive
    Remove-IfExists $mesaExtract
    $mesaReady = -not ($requiredDlls | Where-Object { -not (Test-Path (Join-Path $blenderDir $_)) } | Select-Object -First 1)
    Write-Output "BLENDER_MESA_OK=$mesaReady"
}

function Ensure-BlenderRootCompat {
    param([string]$BlenderExe)

    if (-not (Test-Path $BlenderExe)) {
        return
    }

    $blenderDir = Split-Path -Path $BlenderExe -Parent
    $blenderRoot = Split-Path -Path $blenderDir -Parent
    $rootExe = Join-Path $blenderRoot "blender.exe"
    $rootDataDir = Join-Path $blenderRoot "2.79"
    $dataDir = Join-Path $blenderDir "2.79"

    if (-not (Test-Path $rootExe)) {
        New-Item -ItemType SymbolicLink -Path $rootExe -Target $BlenderExe -Force | Out-Null
    }
    if ((Test-Path $dataDir) -and -not (Test-Path $rootDataDir)) {
        New-Item -ItemType SymbolicLink -Path $rootDataDir -Target $dataDir -Force | Out-Null
    }
    Get-ChildItem -Path $blenderDir -Filter "*.dll" -ErrorAction SilentlyContinue | ForEach-Object {
        $target = Join-Path $blenderRoot $_.Name
        if (-not (Test-Path $target)) {
            New-Item -ItemType SymbolicLink -Path $target -Target $_.FullName -Force | Out-Null
        }
    }
}

Write-Output "RESTORE_START"

$helloPath = Join-Path $env:USERPROFILE "Desktop\hello.txt"
Remove-IfExists $helloPath
Write-Output "HELLO_REMOVED=$(-not (Test-Path $helloPath))"

$desktopRoots = @(
    (Join-Path $env:USERPROFILE "Desktop"),
    "C:\Users\Public\Desktop"
)
$dependencyDesktopItems = @(
    "Actual Budget.lnk",
    "Blender 2.79b.lnk",
    "draw.io.lnk",
    "LibreOffice 26.2.lnk",
    "Marble.lnk",
    "OpenShop.lnk",
    "OpenShop clean.lnk",
    "Setup",
    "Spotube.lnk",
    "Visual Studio Code.lnk",
    "Wireshark.lnk",
    "Zotero.lnk",
    "blender_gui_verify.bat",
    "blender_init_probe.ps1",
    "blender_mesa_verify.bat",
    "blender_root_compat.bat",
    "blender_root_verify.bat"
)
foreach ($root in $desktopRoots) {
    foreach ($item in $dependencyDesktopItems) {
        Remove-IfExists (Join-Path $root $item)
    }
}
New-Item -ItemType Directory -Force -Path (Join-Path $env:USERPROFILE "Desktop\Dependencies") | Out-Null

# OpenShop from local build payload
$openShopSrc = "\\host.lan\Data\_openshop_install\win-unpacked"
$openShopDst = Join-Path $env:LOCALAPPDATA "Programs\OpenShop"
$openShopExe = Join-Path $openShopDst "OpenShop.exe"

if (-not (Test-Path $openShopExe)) {
    if (-not (Test-Path $openShopSrc)) {
        throw "OpenShop payload not found: $openShopSrc"
    }
    New-Item -ItemType Directory -Force -Path $openShopDst | Out-Null
    Copy-Item -Path (Join-Path $openShopSrc "*") -Destination $openShopDst -Recurse -Force
    if (-not (Test-Path $openShopExe)) {
        throw "OpenShop payload copy failed: OpenShop.exe missing"
    }
}
$startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$startMenuShortcut = Join-Path $startMenuDir "OpenShop.lnk"
$wshShell = New-Object -ComObject WScript.Shell
$shortcut = $wshShell.CreateShortcut($startMenuShortcut)
$shortcut.TargetPath = $openShopExe
$shortcut.WorkingDirectory = $openShopDst
$shortcut.Save()
Ensure-DependencyShortcut -ShortcutName "OpenShop.lnk" -TargetPath $openShopExe -WorkingDirectory $openShopDst
Write-Output "OPENSHOP_OK=$(Test-Path $openShopExe)"

# Blender
$blenderExe = "C:\Tools\Blender279b\blender-2.79b-windows64\blender.exe"
if (-not (Test-Path $blenderExe)) {
    $blenderZip = Join-Path $env:TEMP "blender-2.79b-windows64.zip"
    $blenderRoot = "C:\Tools\Blender279b"
    if (Download-FromMirrors -Urls @("https://download.blender.org/release/Blender2.79/blender-2.79b-windows64.zip") -OutFile $blenderZip) {
        Remove-IfExists $blenderRoot
        New-Item -ItemType Directory -Force -Path $blenderRoot | Out-Null
        Expand-Archive -LiteralPath $blenderZip -DestinationPath $blenderRoot -Force
        Remove-IfExists $blenderZip
    }
}
Install-BlenderSoftwareOpenGL -BlenderExe $blenderExe
Ensure-BlenderRootCompat -BlenderExe $blenderExe
Ensure-DependencyShortcut -ShortcutName "Blender 2.79b.lnk" -TargetPath $blenderExe -WorkingDirectory (Split-Path $blenderExe -Parent)
Write-Output "BLENDER_OK=$(Test-Path $blenderExe)"

# Zotero
$zoteroExe = "C:\Program Files\Zotero\zotero.exe"
if (-not (Test-Path $zoteroExe)) {
    $zoteroInstaller = Join-Path $env:TEMP "zotero_setup.exe"
    if (Download-FromMirrors -Urls @("https://download.zotero.org/client/release/7.0.15/Zotero-7.0.15_x64_setup.exe") -OutFile $zoteroInstaller) {
        Start-Process -FilePath $zoteroInstaller -ArgumentList "/S" -Wait
        Remove-IfExists $zoteroInstaller
    }
}
Ensure-DependencyShortcut -ShortcutName "Zotero.lnk" -TargetPath $zoteroExe -WorkingDirectory (Split-Path $zoteroExe -Parent)
Write-Output "ZOTERO_OK=$(Test-Path $zoteroExe)"

Ensure-VisualCpp2013Runtime

# Spotube
$spotubeExe = "C:\Program Files\Spotube\spotube.exe"
if (-not (Test-Path $spotubeExe)) {
    $spotubeInstaller = Join-Path $env:TEMP "SpotubeSetup.exe"
    if (Download-FromMirrors -Urls @(
        "https://github.com/KRTirtho/spotube/releases/download/v5.1.1/Spotube-windows-x86_64-setup.exe",
        "https://github.com/KRTirtho/spotube/releases/latest/download/Spotube-windows-x86_64-setup.exe"
    ) -OutFile $spotubeInstaller) {
        Start-Process -FilePath $spotubeInstaller -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-" -Wait
        Remove-IfExists $spotubeInstaller
    }
}
Ensure-DependencyShortcut -ShortcutName "Spotube.lnk" -TargetPath $spotubeExe -WorkingDirectory (Split-Path $spotubeExe -Parent)
Write-Output "SPOTUBE_OK=$(Test-Path $spotubeExe)"

# LibreOffice
$libreOfficeExe = "C:\Program Files\LibreOffice\program\soffice.exe"
if (-not (Test-Path $libreOfficeExe)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id TheDocumentFoundation.LibreOffice -e --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
    }
}
Ensure-DependencyShortcut -ShortcutName "LibreOffice 26.2.lnk" -TargetPath $libreOfficeExe -WorkingDirectory (Split-Path $libreOfficeExe -Parent)
Write-Output "LIBREOFFICE_OK=$(Test-Path $libreOfficeExe)"

# draw.io
$drawioExe = "C:\Program Files\draw.io\draw.io.exe"
if (-not (Test-Path $drawioExe)) {
    $drawioInstaller = Join-Path $env:TEMP "drawio_installer.exe"
    if (Download-FromMirrors -Urls @("https://github.com/jgraph/drawio-desktop/releases/download/v29.7.9/draw.io-29.7.9-windows-installer.exe") -OutFile $drawioInstaller) {
        Start-Process -FilePath $drawioInstaller -ArgumentList "/S" -Wait
        Remove-IfExists $drawioInstaller
    }
}
Ensure-DependencyShortcut -ShortcutName "draw.io.lnk" -TargetPath $drawioExe -WorkingDirectory (Split-Path $drawioExe -Parent)
Write-Output "DRAWIO_OK=$(Test-Path $drawioExe)"

# Wireshark
$wiresharkExe = "C:\Program Files\Wireshark\Wireshark.exe"
if (-not (Test-Path $wiresharkExe)) {
    $wiresharkInstaller = Join-Path $env:TEMP "wireshark_installer.exe"
    if (Download-FromMirrors -Urls @("https://www.wireshark.org/download/win64/Wireshark-4.4.14-x64.exe") -OutFile $wiresharkInstaller) {
        Start-Process -FilePath $wiresharkInstaller -ArgumentList "/S" -Wait
        Remove-IfExists $wiresharkInstaller
    }
}
Ensure-DependencyShortcut -ShortcutName "Wireshark.lnk" -TargetPath $wiresharkExe -WorkingDirectory (Split-Path $wiresharkExe -Parent)
Write-Output "WIRESHARK_OK=$(Test-Path $wiresharkExe)"

Write-Output "RESTORE_DONE"
