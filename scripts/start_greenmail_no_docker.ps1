param(
  [string]$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$Version = "2.1.8",
  [int]$ApiPort = 8081,
  [int]$SmtpPort = 3025,
  [int]$ImapPort = 3143,
  [switch]$Restart
)

$ErrorActionPreference = "Stop"

$toolsDir = Join-Path $RootDir ".tools"
$javaDir = Join-Path $toolsDir "java"
$greenmailDir = Join-Path $toolsDir "greenmail"
$logDir = Join-Path $RootDir "logs"
New-Item -ItemType Directory -Force -Path $toolsDir, $javaDir, $greenmailDir, $logDir | Out-Null

function Get-JavaExe {
  $cmd = Get-Command java -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }

  $local = Get-ChildItem -Path $javaDir -Recurse -Filter java.exe -File -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
  if ($local) {
    return $local
  }

  return $null
}

function Invoke-Download {
  param(
    [string]$Uri,
    [string]$OutFile
  )
  Write-Host "Downloading $Uri"
  Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
}

function Ensure-Java {
  $javaExe = Get-JavaExe
  if ($javaExe) {
    return $javaExe
  }

  Write-Host "Java was not found. Downloading a portable Eclipse Temurin JRE 17..."
  $assetApi = "https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jre&os=windows&vendor=eclipse"
  $assets = Invoke-RestMethod -Uri $assetApi
  $zipUrl = $assets[0].binary.package.link
  if (-not $zipUrl) {
    throw "Could not resolve a Temurin JRE download URL from Adoptium."
  }

  $zipPath = Join-Path $toolsDir "temurin-jre17.zip"
  Invoke-Download -Uri $zipUrl -OutFile $zipPath
  Expand-Archive -Path $zipPath -DestinationPath $javaDir -Force

  $javaExe = Get-JavaExe
  if (-not $javaExe) {
    throw "Downloaded JRE, but java.exe was not found under $javaDir."
  }
  return $javaExe
}

function Ensure-GreenMailJar {
  $jar = Join-Path $greenmailDir "greenmail-standalone-$Version.jar"
  if (Test-Path $jar) {
    return $jar
  }

  $url = "https://repo1.maven.org/maven2/com/icegreen/greenmail-standalone/$Version/greenmail-standalone-$Version.jar"
  Invoke-Download -Uri $url -OutFile $jar
  return $jar
}

function Test-GreenMailReady {
  param([int]$Port)
  try {
    $payload = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/service/readiness" -TimeoutSec 3
    return ($payload | ConvertTo-Json -Compress)
  } catch {
    return $null
  }
}

if ($Restart) {
  Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*greenmail-standalone-$Version.jar*" } |
    ForEach-Object {
      Write-Host "Stopping existing GreenMail process $($_.ProcessId)"
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

$ready = Test-GreenMailReady -Port $ApiPort
if ($ready) {
  Write-Host "GreenMail is already ready on API port $ApiPort."
  Write-Host $ready
  exit 0
}

$javaExe = Ensure-Java
$jar = Ensure-GreenMailJar

$users = "benchsender@example.test:benchpass,benchrecv@example.test:benchpass,benchchat@example.test:benchpass,avery.design@example.test:benchpass,morgan.ops@example.test:benchpass,jordan.travel@example.test:benchpass"
$stdout = Join-Path $logDir "greenmail.out.log"
$stderr = Join-Path $logDir "greenmail.err.log"
$arguments = @(
  "-Djava.net.preferIPv4Stack=true",
  "-Dgreenmail.setup.test.smtp",
  "-Dgreenmail.setup.test.imap",
  "-Dgreenmail.hostname=0.0.0.0",
  "-Dgreenmail.api.hostname=0.0.0.0",
  "-Dgreenmail.api.port=$ApiPort",
  "-Dgreenmail.users=$users",
  "-Dgreenmail.users.login=email",
  "-Dgreenmail.verbose",
  "-jar",
  "`"$jar`""
)

Write-Host "Starting GreenMail without Docker..."
$process = Start-Process -FilePath $javaExe `
  -ArgumentList $arguments `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdout `
  -RedirectStandardError $stderr `
  -PassThru
Write-Host "GreenMail PID: $($process.Id)"

foreach ($port in @($ApiPort, $SmtpPort, $ImapPort)) {
  try {
    New-NetFirewallRule -DisplayName "HelloWorld GreenMail $port" `
      -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port `
      -ErrorAction Stop | Out-Null
  } catch {
    Write-Warning "Could not add firewall rule for port $port. If the VM cannot connect, run this script from an Administrator PowerShell."
  }
}

$deadline = (Get-Date).AddSeconds(45)
do {
  Start-Sleep -Seconds 1
  $ready = Test-GreenMailReady -Port $ApiPort
  if ($ready) {
    Write-Host "GreenMail is ready."
    Write-Host "API:  http://127.0.0.1:$ApiPort"
    Write-Host "SMTP: 0.0.0.0:$SmtpPort"
    Write-Host "IMAP: 0.0.0.0:$ImapPort"
    Write-Host $ready
    exit 0
  }
} while ((Get-Date) -lt $deadline)

Write-Error "Timed out waiting for GreenMail. See $stdout and $stderr."
