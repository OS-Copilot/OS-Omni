param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [string]$AppDirectory = 'C:\OS-Omni\Apps\OpenTrip'
)
$ErrorActionPreference = 'Stop'
# Run inside a disposable/checkpointed guest, with no benchmark in progress.
$resources = Join-Path $AppDirectory 'resources'
$staging = Join-Path $env:TEMP ('opentrip-baseline-' + [guid]::NewGuid().ToString('N'))
Expand-Archive -LiteralPath $Archive -DestinationPath $staging
$manifest = Get-Content (Join-Path $staging 'osomni-build-manifest.json') -Raw | ConvertFrom-Json
if ($manifest.revision -ne '044ab5a8e95597ffa7a4354c8736de43fa153c7e') {
    throw 'Unexpected OpenTrip baseline revision'
}
foreach ($entry in $manifest.installed_sha256.PSObject.Properties) {
    $path = Join-Path $staging $entry.Name
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) {
        throw "OpenTrip payload integrity failure: $($entry.Name)"
    }
}
$processes = @(Get-Process -Name opentrip -ErrorAction SilentlyContinue)
foreach ($process in $processes) { [void]$process.CloseMainWindow() }
foreach ($process in $processes) {
    if (!$process.WaitForExit(8000)) { $process.Kill(); $process.WaitForExit() }
}
$stamp = (Get-Date).ToString('yyyyMMdd-HHmmss-ffff')
$backup = Join-Path $resources ("baseline-backup-" + $stamp)
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($name in @('app', 'app.asar')) {
    $path = Join-Path $resources $name
    if (Test-Path -LiteralPath $path) { Move-Item -LiteralPath $path -Destination $backup }
}
try {
    Move-Item -LiteralPath $staging -Destination (Join-Path $resources 'app')
} catch {
    foreach ($item in Get-ChildItem -LiteralPath $backup) {
        Move-Item -LiteralPath $item.FullName -Destination $resources
    }
    throw
}
Write-Output "Installed pinned OpenTrip baseline; previous application preserved at $backup"
