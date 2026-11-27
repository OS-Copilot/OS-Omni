param(
    [Parameter(Mandatory = $true)][string]$ScriptFolder,
    [ValidateRange(1, 65535)][int]$Port = 5000,
    [Parameter(Mandatory = $true)][string]$Token
)

$ErrorActionPreference = 'Stop'
$server = Join-Path $ScriptFolder 'server\helloworld_server.py'
if (-not (Test-Path -LiteralPath $server)) {
    throw "Guest runtime server missing: $server"
}
$userPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
$pythonArguments = @()
if (Test-Path -LiteralPath $userPython) {
    $pythonExecutable = $userPython
} else {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $pythonExecutable = $launcher.Source
        $pythonArguments = @('-3')
    } else {
        throw 'Standalone Python 3 is missing; do not use an application-bundled Python from PATH.'
    }
}
$log = Join-Path $env:TEMP 'os-omni-runtime-watchdog.log'
$arguments = $pythonArguments + @($server, '--host', '0.0.0.0', '--port', [string]$Port, '--token', $Token)
# Restart only this child, with a finite startup budget. Do not log the token.
for ($attempt = 1; $attempt -le 5; $attempt++) {
    Add-Content -LiteralPath $log -Value "Runtime launch attempt $attempt, port $Port"
    # Windows PowerShell 5.1 treats redirected native stderr as ErrorRecords.
    # Flask writes normal startup messages there; they must not abort the watcher.
    $ErrorActionPreference = 'Continue'
    & $pythonExecutable @arguments >> $log 2>&1
    $runtimeExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    Add-Content -LiteralPath $log -Value "Runtime exited with code $runtimeExit"
    if ($runtimeExit -eq 0) { exit 0 }
    Start-Sleep -Seconds 3
}
throw 'Runtime failed repeatedly; inspect the guest watchdog log.'
