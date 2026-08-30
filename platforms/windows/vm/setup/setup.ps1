$ErrorActionPreference = "Continue" # until downloading from mirrors is more stable

# Section - General Setup
$desktopDependencyFolder = "C:\Users\User\Desktop\Dependencies"
$shortcutShared = Join-Path $desktopDependencyFolder "Setup"
$scriptFolder = "\\host.lan\Data"
$toolsFolder = "C:\Users\$env:USERNAME\Tools"

# Load the shared setup-tools module
Import-Module (Join-Path $scriptFolder -ChildPath "setup-tools.psm1")

# Create a shortcut to the shared folder if it doesn't exist
if (-not (Test-Path $shortcutShared)) {
    New-Item -ItemType Directory -Path $desktopDependencyFolder -Force | Out-Null
    New-Item -ItemType SymbolicLink -Path $shortcutShared -Value $scriptFolder
}

# Check if profile exists
if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force
}

# Create a folder where we store all the standalone executables
if (-not (Test-Path $toolsFolder)) {
    New-Item -ItemType Directory -Path $toolsFolder -Force
    $envPath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
    $newPath = "$envPath;$toolsFolder"
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "Machine")
}

# Section - Tools Installation

# Set TLS version to 1.2 or higher
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13

function Install-BlenderSoftwareOpenGL {
    param([string]$BlenderExe)

    if (-not (Test-Path $BlenderExe)) {
        return
    }

    $blenderDir = Split-Path -Path $BlenderExe -Parent
    $requiredDlls = @("opengl32.dll", "libglapi.dll", "libgallium_wgl.dll")
    $missingDll = $requiredDlls | Where-Object { -not (Test-Path (Join-Path $blenderDir $_)) } | Select-Object -First 1
    if ($null -eq $missingDll) {
        Write-Host "Blender Mesa3D software OpenGL runtime is already installed."
        return
    }

    $mesaArchive = Join-Path $env:TEMP "mesa3d-24.0.3-release-msvc.7z"
    $mesaExtract = Join-Path $env:TEMP "mesa3d-24.0.3"
    Remove-Item -LiteralPath $mesaArchive -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $mesaExtract -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $mesaExtract | Out-Null

    $mesaUrls = @(
        "https://github.com/pal1000/mesa-dist-win/releases/download/24.0.3/mesa3d-24.0.3-release-msvc.7z"
    )
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $mesaUrls -outfile $mesaArchive
    if (-not $downloadResult) {
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
        $sevenZip = Get-Command 7z -ErrorAction SilentlyContinue
        if ($sevenZip) {
            & $sevenZip.Source x $mesaArchive "-o$mesaExtract" "x64\opengl32.dll" "x64\libglapi.dll" "x64\libgallium_wgl.dll" -y | Out-Null
            $extracted = Test-Path (Join-Path $mesaExtract "x64\opengl32.dll")
        }
    }

    if ($extracted) {
        foreach ($dll in $requiredDlls) {
            Copy-Item -LiteralPath (Join-Path $mesaExtract "x64\$dll") -Destination (Join-Path $blenderDir $dll) -Force
        }
        [Environment]::SetEnvironmentVariable("MESA_LOADER_DRIVER_OVERRIDE", "llvmpipe", "Machine")
        [Environment]::SetEnvironmentVariable("LIBGL_ALWAYS_SOFTWARE", "1", "Machine")
        Write-Host "Blender Mesa3D software OpenGL runtime has been installed."
    } else {
        Write-Warning "Failed to extract Mesa3D software OpenGL runtime."
    }

    Remove-Item -LiteralPath $mesaArchive -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $mesaExtract -Recurse -Force -ErrorAction SilentlyContinue
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

function Ensure-VisualCpp2013Runtime {
    $dllPaths = @(
        "$env:WINDIR\System32\MSVCP120.dll",
        "$env:WINDIR\SysWOW64\MSVCP120.dll"
    )
    $missingDll = $dllPaths | Where-Object { -not (Test-Path $_) } | Select-Object -First 1
    if (-not $missingDll) {
        Write-Host "Visual C++ 2013 runtime is already installed."
        return
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Warning "winget is not available; cannot install Visual C++ 2013 runtime."
        return
    }

    Write-Host "Installing Visual C++ 2013 runtime for Marble..."
    winget install --id Microsoft.VCRedist.2013.x64 -e --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
    winget install --id Microsoft.VCRedist.2013.x86 -e --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
}

# Load the tools config json listing mirrors and aliases used for installing tools
$toolsConfigJsonPath = Join-Path $scriptFolder -ChildPath "tools_config.json"
$toolsConfigJson = Get-Content -Path $toolsConfigJsonPath -Raw
$toolsList = Get-Tools -toolsConfigJson $toolsConfigJson

## - Python
$pythonToolName = "Python"
$userPythonPath = "$env:LOCALAPPDATA\Programs\Python"
$pythonDetails = Get-ToolDetails -toolsList $toolsList -toolName $pythonToolName
$pythonAlias = $pythonDetails.alias

# Check for Python installation
$pythonExecutablePath = Get-ChildItem -Path $userPythonPath -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName

# Force to install Python 3.10 as the pre-installed version on Windows may not work sometimes
Write-Host "Downloading Python $pythonVersion..."
$pythonInstallerFilePath = "$env:TEMP\python_installer.exe"
$downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $pythonDetails.mirrors -outfile $pythonInstallerFilePath
if (-not $downloadResult) {
    Write-Host "Failed to download Python. Please try again later or install manually."
} else {
    Write-Host "Installing Python for current user..."
    Start-Process -FilePath $pythonInstallerFilePath -Args "/quiet InstallAllUsers=0 PrependPath=0" -NoNewWindow -Wait
    $pythonExecutablePath = "$userPythonPath\Python310\python.exe"
    $setAliasExpression = "Set-Alias -Name $pythonAlias -Value `"$pythonExecutablePath`""
    Add-Content -Path $PROFILE -Value $setAliasExpression
    Invoke-Expression $setAliasExpression
}

## - Git
$gitToolName = "git"
$gitToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $gitToolName

# Check for Git installation
try {
    git --version | Out-Null
    Write-Host "Git is already installed."
} catch {
    Write-Host "Git is not installed. Downloading and installing Git..."
    $gitInstallerFilePath = "$env:TEMP\git_installer.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $gitToolDetails.mirrors -outfile $gitInstallerFilePath
    if (-not $downloadResult) {
        Write-Host "Failed to download Git. Please try again later or install manually."
    } else {
        Start-Process -FilePath $gitInstallerFilePath -Args "/VERYSILENT /NORESTART /NOCANCEL /SP-" -Wait
        Add-ToEnvPath -NewPath "C:\Program Files\Git\bin"

        Write-Host "Git has been installed."
    }
}

# - 7zip
$7ZipToolName = "7zip"
$7ZipToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $7ZipToolName
Write-Host "$7ZipToolDetails"

if (Get-Command 7z -ErrorAction SilentlyContinue) {
    Write-Host "7-Zip is already installed."
}
else {
    Write-Host "Installing 7-Zip..."

    $7ZipInstallerFilePath = "$env:TEMP\7_zip.exe"
    Write-Host "$($7ZipToolDetails.mirrors)"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $7ZipToolDetails.mirrors -outfile $7ZipInstallerFilePath
    if (-not $downloadResult) {
        Write-Host "Failed to download 7-Zip. Please try again later or install manually."
    } else {
        Start-Process -FilePath $7ZipInstallerFilePath -Args "/S" -Verb RunAs -Wait
        Remove-Item $7ZipInstallerFilePath

        # add 7z to PATH
        Add-ToEnvPath -NewPath "${env:ProgramFiles}\7-Zip"
    }
}

# - ffpmeg
$ffpmegToolName = "ffmpeg"
$ffpmegToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $ffpmegToolName

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Host "ffmpeg is already installed."
} else {
    Write-Host "ffmpeg is not installed. Installing it."
    $ffpmegInstallerFilePath = "C:\ffmpeg.7z"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $ffpmegToolDetails.mirrors -outfile $ffpmegInstallerFilePath
    if (-not $downloadResult) {
        Write-Host "Failed to download ffmpeg. Please try again later or install manually."
    } else {
        Write-Host "Extracting $ffpmegInstallerFilePath..."
        7z x -y -o"C:\" "C:\ffmpeg.7z"

        $ffmpegFolder = Get-ChildItem -Path "C:\" -Filter "ffmpeg-*" -Directory
        $ffmpegFolder = -join ("C:\",  $ffmpegFolder)
        #remove ffmpeg folder if exists
        if (Test-Path "C:\ffmpeg") {
            Remove-Item -Path "C:\ffmpeg" -Recurse -Force
        }
        Rename-Item -Path "$ffmpegFolder" -NewName "ffmpeg"

        Write-Host "Adding ffmpeg to PATH..."
        Add-ToEnvPath -NewPath "C:\ffmpeg\bin"

        Write-Host "ffmpeg is installed"
    }
}

# Disable Edge Auto Updates
Stop-Process -Name "MicrosoftEdgeUpdate" -Force -ErrorAction SilentlyContinue
$edgeUpdatePath = "${env:ProgramFiles(x86)}\Microsoft\EdgeUpdate"
Remove-Item -Path $edgeUpdatePath -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Edge Update processes terminated and directory removed."

# - Google Chrome
$chromeToolName = "Google Chrome"
$chromeToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $chromeToolName
$chromeExePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$chromeAlias = $chromeToolDetails.alias

# Check if Google Chrome is already installed by its alias
if (Get-Command $chromeAlias -ErrorAction SilentlyContinue) {
    Write-Host "Google Chrome is already installed."
} else {
    # Download the installer to the Temp directory
    $chromeInstallerFilePath = "$env:TEMP\chrome_installer.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $chromeToolDetails.mirrors -outfile $chromeInstallerFilePath
    if (-not $downloadResult) {
        Write-Host "Failed to download Google Chrome. Please try again later or install manually."
    } else {
        # Execute the installer silently with elevated permissions
        Start-Process -FilePath $chromeInstallerFilePath -ArgumentList "/silent", "/install" -Verb RunAs -Wait

        # Remove the installer file after installation
        Remove-Item -Path $chromeInstallerFilePath

        # Set alias
        $setAliasExpression = "Set-Alias -Name $chromeAlias -Value `"$chromeExePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression

        # Add Chrome to the system PATH environment variable
        Add-ToEnvPath -NewPath "${env:ProgramFiles}\Google\Chrome\Application"

        # Disable Google Chrome Auto Updates
        $chromeRegPath = "HKLM:\SOFTWARE\Policies\Google\Update"
        if (-not (Test-Path $chromeRegPath)) {
            New-Item -Path $chromeRegPath -Force
        }
        Set-ItemProperty -Path $chromeRegPath -Name "AutoUpdateCheckPeriodMinutes" -Value 0
        Set-ItemProperty -Path $chromeRegPath -Name "UpdateDefault" -Value 0
    }
}

# - LibreOffice
$libreOfficeToolName = "LibreOffice"
$libreOfficeToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $libreOfficeToolName

# Check for LibreOffice installation
$installedVersion = (Get-WmiObject -Query "SELECT * FROM Win32_Product WHERE Name like 'LibreOffice%'").Version
if (-not [string]::IsNullOrWhiteSpace($installedVersion)) {
    Write-Host "LibreOffice $version is already installed."
} else {
    Write-Host "LibreOffice is not installed. Downloading and installing LibreOffice..."
    $libreOfficeInstallerFilePath = "$env:TEMP\libreOffice_installer.exe"
    
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $libreOfficeToolDetails.mirrors -outfile $libreOfficeInstallerFilePath
    if (-not $downloadResult) {
        Write-Host "Failed to download LibreOffice. Please try again later or install manually."
    } else {
        Start-Process "msiexec.exe" -ArgumentList "/i `"$libreOfficeInstallerFilePath`" /quiet" -Wait -NoNewWindow
        Write-Host "LibreOffice has been installed."
    
        # Add LibreOffice to the system PATH environment variable
        Add-ToEnvPath -NewPath "C:\Program Files\LibreOffice\program"
    }
}

# - VLC
$vlcToolName = "VLC"
$vlcToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $vlcToolName
$vlcAlias = $vlcToolDetails.alias
$vlcExecutableFilePath = "C:\Program Files\VideoLAN\VLC\vlc.exe"

# Check if VLC is already installed by checking the VLC command
if (Test-Path $vlcExecutableFilePath) {
    Write-Host "VLC is already installed."
} else {
    # Download the installer to the Temp directory
    $vlcInstallerFilePath = "$env:TEMP\vlc_installer.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $vlcToolDetails.mirrors -outfile $vlcInstallerFilePath
    if (-not $downloadResult) {
        Write-Host "Failed to download VLC. Please try again later or install manually."
    } else {
        # Execute the installer silently with elevated permissions
        Start-Process -FilePath $vlcInstallerFilePath -ArgumentList "/S" -Verb RunAs -Wait

        # Remove the installer file after installation
        Remove-Item -Path $vlcInstallerFilePath

        # Set alias
        $setAliasExpression = "Set-Alias -Name $vlcAlias -Value `"$vlcExecutableFilePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression

        # Add VLC to the system PATH environment variable
        Add-ToEnvPath -NewPath "C:\Program Files\VideoLAN\VLC"
    }
}

# - GIMP
$gimpToolName = "GIMP"
$gimpToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $gimpToolName
$gimpAlias = $gimpToolDetails.alias
$gimpExecutablePath = "C:\Program Files\GIMP 2\bin\gimp-2.10.exe"

# Check if GIMP is already installed by checking the GIMP executable path
if (Test-Path $gimpExecutablePath) {
    Write-Host "GIMP is already installed."
} else {
    # Download the installer to the Temp directory
    $gimpInstallerFilePath = "$env:TEMP\gimp_installer.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $gimpToolDetails.mirrors -outfile $gimpInstallerFilePath
    if (-not $downloadResult) {
        Write-Host "Failed to download GIMP. Please try again later or install manually."
    } else {
        # Execute the installer silently with elevated permissions
        Start-Process -FilePath $gimpInstallerFilePath -ArgumentList "/VERYSILENT /ALLUSERS" -Verb RunAs -Wait

        # Remove the installer file after installation
        Remove-Item -Path $gimpInstallerFilePath

        # Set alias
        $setAliasExpression = "Set-Alias -Name $gimpAlias -Value `"$gimpExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression

        # Add GIMP to the system PATH environment variable
        Add-ToEnvPath -NewPath "C:\Program Files\GIMP 2\bin"
    }
}

# - VS Code
$vsCodeToolName = "VS Code"
$vsCodeToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $vsCodeToolName
$vsCodeAlias = $vsCodeToolDetails.alias
$vsCodeExecutablePath = "C:\Users\$env:USERNAME\AppData\Local\Programs\Microsoft VS Code\Code.exe"
$vsCodeBinPath = "C:\Users\$env:USERNAME\AppData\Local\Programs\Microsoft VS Code\bin"
$vsCodeSettingsPath = "${env:APPDATA}\Code\User\settings.json"
$vsCodeDesktopShortcutPath = Join-Path $desktopDependencyFolder "Visual Studio Code.lnk"
$vsCodeStartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$vsCodeStartMenuShortcutPath = Join-Path $vsCodeStartMenuDir "Visual Studio Code.lnk"

# Check if VS Code is already installed by checking the VS Code executable path
if (Test-Path $vsCodeExecutablePath) {
    Write-Host "VS Code is already installed."
} else {
    # Download the installer to the Temp directory
    $vsCodeInstallerFilePath = "$env:TEMP\VSCodeSetup.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $vsCodeToolDetails.mirrors -outfile $vsCodeInstallerFilePath
    if (-not $downloadResult) {
        Write-Host "Failed to download VS Code. Please try again later or install manually."
    } else {
        # Execute the installer silently with elevated permissions
        Start-Process -FilePath $vsCodeInstallerFilePath -ArgumentList "/VERYSILENT", "/mergetasks=!runcode" -Verb RunAs -Wait

        # Remove the installer file after installation
        Remove-Item -Path $vsCodeInstallerFilePath
    }
}

if (Test-Path $vsCodeExecutablePath) {
    # Set alias
    $setAliasExpression = "Set-Alias -Name $vsCodeAlias -Value `"$vsCodeExecutablePath`""
    Add-Content -Path $PROFILE -Value $setAliasExpression
    Invoke-Expression $setAliasExpression

    # Add VS Code to the system PATH environment variable
    Add-ToEnvPath -NewPath $vsCodeBinPath

    # Disable Visual Studio Code Auto Updates
    if (-not (Test-Path $vsCodeSettingsPath)) {
        $dirPath = Split-Path -Path $vsCodeSettingsPath -Parent
        if (-not (Test-Path $dirPath)) {
            New-Item -ItemType Directory -Path $dirPath -Force | Out-Null
        }
        $settingsObj = @{}
    } else {
        try {
            $settingsObj = Get-Content $vsCodeSettingsPath -Raw | ConvertFrom-Json -AsHashtable
        } catch {
            $settingsObj = @{}
        }
    }
    $settingsObj["update.mode"] = "none"
    $settingsObj | ConvertTo-Json | Set-Content $vsCodeSettingsPath

    if (-not (Test-Path $vsCodeStartMenuDir)) {
        New-Item -ItemType Directory -Path $vsCodeStartMenuDir -Force | Out-Null
    }

    foreach ($shortcutPath in @($vsCodeDesktopShortcutPath, $vsCodeStartMenuShortcutPath)) {
        if (-not (Test-Path $shortcutPath)) {
            try {
                New-Item -ItemType Directory -Path (Split-Path -Path $shortcutPath -Parent) -Force | Out-Null
                $wshShell = New-Object -ComObject WScript.Shell
                $shortcut = $wshShell.CreateShortcut($shortcutPath)
                $shortcut.TargetPath = $vsCodeExecutablePath
                $shortcut.WorkingDirectory = Split-Path -Path $vsCodeExecutablePath -Parent
                $shortcut.Save()
            } catch {
                Write-Warning "Failed to create VS Code shortcut at ${shortcutPath}: $($_.Exception.Message)"
            }
        }
    }
}

# - Thunderbird
$thunderbirdToolName = "Thunderbird"
$thunderbirdToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $thunderbirdToolName
$thunderbirdAlias = $thunderbirdToolDetails.alias
$thunderbirdExecutablePath = "C:\Program Files\Mozilla Thunderbird\thunderbird.exe"

# Check if Thunderbird is already installed by checking the Thunderbird executable path
if (Test-Path $thunderbirdExecutablePath) {
    Write-Host "Thunderbird is already installed."
} else {
    # Download the installer to the Temp directory
    $thunderbirdInstallerFilePath = "$env:TEMP\ThunderbirdSetup.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $thunderbirdToolDetails.mirrors -outfile $thunderbirdInstallerFilePath
    if (-not $downloadResult) {
        Write-Host "Failed to download Thunderbird. Please try again later or install manually."
    } else {
        # Execute the installer silently with elevated permissions
        Start-Process -FilePath $thunderbirdInstallerFilePath -ArgumentList "/S" -Verb RunAs -Wait

        # Remove the installer file after installation
        Remove-Item -Path $thunderbirdInstallerFilePath

        # Set alias
        $setAliasExpression = "Set-Alias -Name $thunderbirdAlias -Value `"$thunderbirdExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression

        # Add Thunderbird to the system PATH environment variable
        Add-ToEnvPath -NewPath "C:\Program Files\Mozilla Thunderbird"
    }
}

# - Delta Chat
$deltaChatToolName = "Delta Chat"
$deltaChatToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $deltaChatToolName
$deltaChatAlias = $deltaChatToolDetails.alias
$deltaChatCandidatePaths = @(
    "C:\Program Files\DeltaChat\DeltaChat.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\DeltaChat\DeltaChat.exe"
)
$deltaChatExecutablePath = $deltaChatCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($deltaChatExecutablePath) {
    Write-Host "Delta Chat is already installed."
} else {
    $deltaChatInstallerFilePath = "$env:TEMP\DeltaChatSetup.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $deltaChatToolDetails.mirrors -outfile $deltaChatInstallerFilePath
    if ($downloadResult) {
        try {
            Start-Process -FilePath $deltaChatInstallerFilePath -ArgumentList "/S" -Wait
        } catch {
            Write-Warning "Delta Chat installer exited with error: $($_.Exception.Message)"
        } finally {
            Remove-Item -Path $deltaChatInstallerFilePath -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "Failed to download Delta Chat from mirrors."
    }

    $deltaChatExecutablePath = $deltaChatCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $deltaChatExecutablePath -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "Trying winget fallback for Delta Chat..."
        winget install -e --id 9PJTXX7HN3PK --silent --accept-package-agreements --accept-source-agreements | Out-Null
        Start-Sleep -Seconds 2
        $deltaChatExecutablePath = $deltaChatCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    }

    if ($deltaChatExecutablePath) {
        $setAliasExpression = "Set-Alias -Name $deltaChatAlias -Value `"$deltaChatExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression
        Add-ToEnvPath -NewPath (Split-Path -Path $deltaChatExecutablePath -Parent)
        Write-Host "Delta Chat has been installed."
    } else {
        Write-Warning "Delta Chat installation did not produce expected executable path."
    }
}

# - Spotube
$spotubeToolName = "Spotube"
$spotubeToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $spotubeToolName
$spotubeAlias = $spotubeToolDetails.alias
$spotubeCandidatePaths = @(
    "C:\Program Files\Spotube\spotube.exe",
    "C:\Program Files\Spotube\Spotube.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Spotube\Spotube.exe"
)
$spotubeExecutablePath = $spotubeCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($spotubeExecutablePath) {
    Write-Host "Spotube is already installed."
} else {
    $spotubeInstallerFilePath = "$env:TEMP\SpotubeSetup.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $spotubeToolDetails.mirrors -outfile $spotubeInstallerFilePath
    if ($downloadResult) {
        try {
            Start-Process -FilePath $spotubeInstallerFilePath -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-" -Wait
        } catch {
            Write-Warning "Spotube installer exited with error: $($_.Exception.Message)"
        } finally {
            Remove-Item -Path $spotubeInstallerFilePath -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "Failed to download Spotube from mirrors."
    }

    $spotubeExecutablePath = $spotubeCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $spotubeExecutablePath -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "Trying winget fallback for Spotube..."
        winget install --id KRTirtho.Spotube -e --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
        Start-Sleep -Seconds 3
        $spotubeExecutablePath = $spotubeCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    }

    if ($spotubeExecutablePath) {
        $setAliasExpression = "Set-Alias -Name $spotubeAlias -Value `"$spotubeExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression
        Add-ToEnvPath -NewPath (Split-Path -Path $spotubeExecutablePath -Parent)

        $spotubeShortcutPath = Join-Path $desktopDependencyFolder "Spotube.lnk"
        if (-not (Test-Path $spotubeShortcutPath)) {
            try {
                New-Item -ItemType Directory -Path $desktopDependencyFolder -Force | Out-Null
                $wshShell = New-Object -ComObject WScript.Shell
                $shortcut = $wshShell.CreateShortcut($spotubeShortcutPath)
                $shortcut.TargetPath = $spotubeExecutablePath
                $shortcut.WorkingDirectory = Split-Path -Path $spotubeExecutablePath -Parent
                $shortcut.Save()
            } catch {
                Write-Warning "Failed to create Spotube desktop shortcut: $($_.Exception.Message)"
            }
        }

        Write-Host "Spotube has been installed."
    } else {
        Write-Warning "Spotube installation did not produce expected executable path."
    }
}

# - Blender
$blenderToolName = "Blender"
$blenderToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $blenderToolName
$blenderAlias = $blenderToolDetails.alias
$blenderRootPath = "C:\Tools\Blender279b"
$blenderExecutablePath = Join-Path $blenderRootPath "blender-2.79b-windows64\blender.exe"

if (Test-Path $blenderExecutablePath) {
    Write-Host "Blender is already installed."
} else {
    $blenderZipPath = "$env:TEMP\blender-2.79b-windows64.zip"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $blenderToolDetails.mirrors -outfile $blenderZipPath
    if ($downloadResult) {
        try {
            if (Test-Path $blenderRootPath) {
                Remove-Item -LiteralPath $blenderRootPath -Recurse -Force
            }
            New-Item -ItemType Directory -Path $blenderRootPath -Force | Out-Null
            Expand-Archive -LiteralPath $blenderZipPath -DestinationPath $blenderRootPath -Force
        } catch {
            Write-Warning "Blender extraction failed: $($_.Exception.Message)"
        } finally {
            Remove-Item -Path $blenderZipPath -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "Failed to download Blender from mirrors."
    }

    if (Test-Path $blenderExecutablePath) {
        $setAliasExpression = "Set-Alias -Name $blenderAlias -Value `"$blenderExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression
        Add-ToEnvPath -NewPath (Split-Path -Path $blenderExecutablePath -Parent)

        $blenderShortcutPath = Join-Path $desktopDependencyFolder "Blender 2.79b.lnk"
        if (-not (Test-Path $blenderShortcutPath)) {
            try {
                New-Item -ItemType Directory -Path $desktopDependencyFolder -Force | Out-Null
                $wshShell = New-Object -ComObject WScript.Shell
                $shortcut = $wshShell.CreateShortcut($blenderShortcutPath)
                $shortcut.TargetPath = $blenderExecutablePath
                $shortcut.WorkingDirectory = Split-Path -Path $blenderExecutablePath -Parent
                $shortcut.Save()
            } catch {
                Write-Warning "Failed to create Blender desktop shortcut: $($_.Exception.Message)"
            }
        }

        Write-Host "Blender has been installed."
    } else {
        Write-Warning "Blender installation did not produce expected executable path."
    }
}
Install-BlenderSoftwareOpenGL -BlenderExe $blenderExecutablePath
Ensure-BlenderRootCompat -BlenderExe $blenderExecutablePath

# - draw.io
$drawioToolName = "draw.io"
$drawioToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $drawioToolName
$drawioAlias = $drawioToolDetails.alias
$drawioCandidatePaths = @(
    "C:\Program Files\draw.io\draw.io.exe",
    "C:\Program Files (x86)\draw.io\draw.io.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\draw.io\draw.io.exe"
)
$drawioExecutablePath = $drawioCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($drawioExecutablePath) {
    Write-Host "draw.io is already installed."
} else {
    $drawioInstallerPath = "$env:TEMP\drawio_installer.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $drawioToolDetails.mirrors -outfile $drawioInstallerPath
    if ($downloadResult) {
        try {
            Start-Process -FilePath $drawioInstallerPath -ArgumentList "/S" -Wait
        } catch {
            Write-Warning "draw.io installer exited with error: $($_.Exception.Message)"
        } finally {
            Remove-Item -Path $drawioInstallerPath -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "Failed to download draw.io from mirrors."
    }

    $drawioExecutablePath = $drawioCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($drawioExecutablePath) {
        $setAliasExpression = "Set-Alias -Name $drawioAlias -Value `"$drawioExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression
        Add-ToEnvPath -NewPath (Split-Path -Path $drawioExecutablePath -Parent)
        Write-Host "draw.io has been installed."
    } else {
        Write-Warning "draw.io installation did not produce expected executable path."
    }
}

# - Wireshark
$wiresharkToolName = "Wireshark"
$wiresharkToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $wiresharkToolName
$wiresharkAlias = $wiresharkToolDetails.alias
$wiresharkExecutablePath = "C:\Program Files\Wireshark\Wireshark.exe"
$tsharkExecutablePath = "C:\Program Files\Wireshark\tshark.exe"

if (Test-Path $wiresharkExecutablePath) {
    Write-Host "Wireshark is already installed."
} else {
    $wiresharkInstallerPath = "$env:TEMP\wireshark_installer.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $wiresharkToolDetails.mirrors -outfile $wiresharkInstallerPath
    if ($downloadResult) {
        try {
            Start-Process -FilePath $wiresharkInstallerPath -ArgumentList "/S" -Wait
        } catch {
            Write-Warning "Wireshark installer exited with error: $($_.Exception.Message)"
        } finally {
            Remove-Item -Path $wiresharkInstallerPath -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "Failed to download Wireshark from mirrors."
    }

    if (Test-Path $wiresharkExecutablePath) {
        $setAliasExpression = "Set-Alias -Name $wiresharkAlias -Value `"$wiresharkExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression
        Add-ToEnvPath -NewPath (Split-Path -Path $wiresharkExecutablePath -Parent)
        Write-Host "Wireshark has been installed."
    } else {
        Write-Warning "Wireshark installation did not produce expected executable path."
    }
}

# - Zotero
$zoteroToolName = "Zotero"
$zoteroToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $zoteroToolName
$zoteroAlias = $zoteroToolDetails.alias
$zoteroCandidatePaths = @(
    "C:\Program Files\Zotero\zotero.exe",
    "C:\Program Files (x86)\Zotero\zotero.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Zotero\zotero.exe"
)
$zoteroExecutablePath = $zoteroCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($zoteroExecutablePath) {
    Write-Host "Zotero is already installed."
} else {
    $zoteroInstallerPath = "$env:TEMP\zotero_installer.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $zoteroToolDetails.mirrors -outfile $zoteroInstallerPath
    if ($downloadResult) {
        try {
            Start-Process -FilePath $zoteroInstallerPath -ArgumentList "/S" -Wait
        } catch {
            Write-Warning "Zotero installer exited with error: $($_.Exception.Message)"
        } finally {
            Remove-Item -Path $zoteroInstallerPath -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "Failed to download Zotero from mirrors."
    }

    $zoteroExecutablePath = $zoteroCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($zoteroExecutablePath) {
        $setAliasExpression = "Set-Alias -Name $zoteroAlias -Value `"$zoteroExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression
        Add-ToEnvPath -NewPath (Split-Path -Path $zoteroExecutablePath -Parent)
        Write-Host "Zotero has been installed."
    } else {
        Write-Warning "Zotero installation did not produce expected executable path."
    }
}

# - Marble
Ensure-VisualCpp2013Runtime
$marbleToolName = "Marble"
$marbleToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $marbleToolName
$marbleAlias = $marbleToolDetails.alias
$marbleCandidatePaths = @(
    "C:\Program Files\Marble\marble-qt.exe",
    "C:\Program Files\Marble\bin\marble-qt.exe",
    "C:\Program Files\Marble\Marble.exe",
    "C:\Program Files (x86)\Marble\marble-qt.exe",
    "C:\Program Files (x86)\Marble\bin\marble-qt.exe"
)
$marbleExecutablePath = $marbleCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($marbleExecutablePath) {
    Write-Host "Marble is already installed."
} else {
    $marbleInstallerFilePath = "$env:TEMP\MarbleSetup.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $marbleToolDetails.mirrors -outfile $marbleInstallerFilePath
    if ($downloadResult) {
        try {
            Start-Process -FilePath $marbleInstallerFilePath -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-" -Wait
        } catch {
            Write-Warning "Marble installer exited with error: $($_.Exception.Message)"
        } finally {
            Remove-Item -Path $marbleInstallerFilePath -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "Failed to download Marble from mirrors."
    }

    $marbleExecutablePath = $marbleCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $marbleExecutablePath -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "Trying winget fallback for Marble..."
        winget install --id KDE.Marble -e --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
        Start-Sleep -Seconds 3
        $marbleExecutablePath = $marbleCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    }

    if ($marbleExecutablePath) {
        $setAliasExpression = "Set-Alias -Name $marbleAlias -Value `"$marbleExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression
        Add-ToEnvPath -NewPath (Split-Path -Path $marbleExecutablePath -Parent)

        $marbleShortcutPath = Join-Path $desktopDependencyFolder "Marble.lnk"
        if (-not (Test-Path $marbleShortcutPath)) {
            try {
                New-Item -ItemType Directory -Path $desktopDependencyFolder -Force | Out-Null
                $wshShell = New-Object -ComObject WScript.Shell
                $shortcut = $wshShell.CreateShortcut($marbleShortcutPath)
                $shortcut.TargetPath = $marbleExecutablePath
                $shortcut.WorkingDirectory = Split-Path -Path $marbleExecutablePath -Parent
                $shortcut.Save()
            } catch {
                Write-Warning "Failed to create Marble desktop shortcut: $($_.Exception.Message)"
            }
        }

        Write-Host "Marble has been installed."
    } else {
        Write-Warning "Marble installation did not produce expected executable path."
    }
}

# - Actual Budget
$actualBudgetToolName = "Actual Budget"
$actualBudgetToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $actualBudgetToolName
$actualBudgetAlias = $actualBudgetToolDetails.alias
$actualBudgetCandidatePaths = @(
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Actual\Actual.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\actual\Actual.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\desktop-electron\Actual.exe",
    "C:\Program Files\Actual\Actual.exe",
    "$toolsFolder\actualbudget.exe",
    "$toolsFolder\Actual-windows-x64.exe"
)
$actualBudgetExecutablePath = $actualBudgetCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($actualBudgetExecutablePath) {
    Write-Host "Actual Budget is already installed."
} else {
    $actualBudgetInstallerFilePath = "$env:TEMP\ActualBudgetSetup.exe"
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $actualBudgetToolDetails.mirrors -outfile $actualBudgetInstallerFilePath
    if ($downloadResult) {
        try {
            # Actual's release binary may be installer or portable build depending on version.
            Start-Process -FilePath $actualBudgetInstallerFilePath -ArgumentList "/S" -Wait
        } catch {
            Write-Warning "Actual Budget installer exited with error: $($_.Exception.Message)"
        }

        $actualBudgetExecutablePath = $actualBudgetCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $actualBudgetExecutablePath) {
            try {
                Copy-Item -Path $actualBudgetInstallerFilePath -Destination "$toolsFolder\actualbudget.exe" -Force
                $actualBudgetExecutablePath = "$toolsFolder\actualbudget.exe"
            } catch {
                Write-Warning "Failed to copy Actual Budget binary to tools folder: $($_.Exception.Message)"
            }
        }

        Remove-Item -Path $actualBudgetInstallerFilePath -ErrorAction SilentlyContinue
    } else {
        Write-Host "Failed to download Actual Budget from mirrors."
    }

    if (-not $actualBudgetExecutablePath -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "Trying winget fallback for Actual Budget..."
        winget install -e --name "Actual Budget" --silent --accept-package-agreements --accept-source-agreements | Out-Null
        Start-Sleep -Seconds 3
        $actualBudgetExecutablePath = $actualBudgetCandidatePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    }

    if ($actualBudgetExecutablePath) {
        $setAliasExpression = "Set-Alias -Name $actualBudgetAlias -Value `"$actualBudgetExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression
        Add-ToEnvPath -NewPath (Split-Path -Path $actualBudgetExecutablePath -Parent)

        $actualBudgetShortcutPath = Join-Path $desktopDependencyFolder "Actual Budget.lnk"
        if (-not (Test-Path $actualBudgetShortcutPath)) {
            try {
                New-Item -ItemType Directory -Path $desktopDependencyFolder -Force | Out-Null
                $wshShell = New-Object -ComObject WScript.Shell
                $shortcut = $wshShell.CreateShortcut($actualBudgetShortcutPath)
                $shortcut.TargetPath = $actualBudgetExecutablePath
                $shortcut.WorkingDirectory = Split-Path -Path $actualBudgetExecutablePath -Parent
                $shortcut.Save()
            } catch {
                Write-Warning "Failed to create Actual Budget desktop shortcut: $($_.Exception.Message)"
            }
        }

        Write-Host "Actual Budget has been installed."
    } else {
        Write-Warning "Actual Budget installation did not produce expected executable path."
    }
}

# - Caddy Proxy
$caddyProxyToolName = "Caddy Proxy"
$caddyProxyToolDetails = Get-ToolDetails -toolsList $toolsList -toolName $caddyProxyToolName
$caddyProxyAlias = $caddyProxyToolDetails.alias
$caddyProxyExecutablePath = "C:\Users\$env:USERNAME\caddy_windows_amd64.exe"

# Check if Caddy is already installed by checking the Caddy executable path
if (Test-Path $caddyProxyExecutablePath) {
    Write-Host "Caddy Server is already installed."
} else {
    # Download the installer to the Temp directory
    $downloadResult = Invoke-DownloadFileFromAvailableMirrors -mirrorUrls $caddyProxyToolDetails.mirrors -outfile $caddyProxyExecutablePath
    if (-not $downloadResult) {
        Write-Host "Failed to download Caddy Proxy. Please try again later or install manually."
    } else {
        # Set alias
        $setAliasExpression = "Set-Alias -Name $caddyProxyAlias -Value `"$caddyProxyExecutablePath`""
        Add-Content -Path $PROFILE -Value $setAliasExpression
        Invoke-Expression $setAliasExpression
    }
}

# - Windows Arena Server Setup 

$pythonServerPort = 5000
$onLogonTaskName = "WindowsArena_OnLogon"
$requirementsFile = "$scriptFolder\server\requirements.txt"
$helloworldRequirementsFile = "$scriptFolder\server\helloworld_requirements.txt"

# Ensure pip is updated to the latest version
Install-PythonPackages -Package "pip" -Arguments "--upgrade"

Install-PythonPackages -Package "wheel"
Install-PythonPackages -Package "pywinauto"

# Install Python packages from requirements.txt using Python's pip module
if (Test-Path $requirementsFile) {
    Write-Host "Installing required Python packages using pip from requirements file..."
    Install-PythonPackages -RequirementsPath $requirementsFile
} else {
    Write-Error "Requirements file not found: $requirementsFile"
    exit
}

# Install HelloWorld runtime requirements (UIA / pywin32 / psutil) used by helloworld_server.py
if (Test-Path $helloworldRequirementsFile) {
    Write-Host "Installing HelloWorld runtime packages from helloworld_requirements.txt..."
    Install-PythonPackages -RequirementsPath $helloworldRequirementsFile
} else {
    Write-Warning "HelloWorld requirements file not found: $helloworldRequirementsFile"
}

# Add a firewall rule to allow incoming connections on the specified port for the Python executable
$pythonServerRuleName = "PythonHTTPServer-$pythonServerPort"
if (-not (Get-NetFirewallRule -Name $pythonServerRuleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $pythonServerRuleName -Direction Inbound -Program $pythonExecutablePath -Protocol TCP -LocalPort $pythonServerPort -Action Allow -Profile Any
    Write-Host "Firewall rule added to allow traffic on port $pythonServerPort for Python"
} else {
    Write-Host "Firewall rule already exists. $pythonServerRuleName "
}

# Add a firewall rule to allow incoming connections on the specified port for the Python executable
$caddyProxyRuleName = "Allow-Caddy-Proxy"
if (-not (Get-NetFirewallRule -Name $caddyProxyRuleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $caddyProxyRuleName -Direction Inbound -Program $caddyProxyExecutablePath -Action Allow -Profile Any
    Write-Host "Firewall rule added to allow traffic on port $caddyProxyRuleName"
} else {
    Write-Host "Firewall rule already exists. $caddyProxyRuleName "
}

$onLogonScriptPath = "$scriptFolder\on-logon.ps1"
# Check if the scheduled task exists before unregistering it
if (Get-ScheduledTask -TaskName $onLogonTaskName -ErrorAction SilentlyContinue) {
    Write-Host "Scheduled task $onLogonTaskName already exists."
} else {
    Write-Host "Registering new task $onLogonTaskName..."
    Register-LogonTask -TaskName $onLogonTaskName -ScriptPath $onLogonScriptPath -LocalUser "User"
}

Start-Sleep -Seconds 10
Start-ScheduledTask -TaskName $onLogonTaskName
