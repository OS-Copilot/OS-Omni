$scriptFolder = "\\host.lan\Data"
$pythonScriptFile = "$scriptFolder\server\helloworld_server.py"
$pythonServerPort = 5000
$watchdogScript = "$scriptFolder\watch-helloworld-server.ps1"

# Prevent sleep/hibernate that can drop the guest runtime mid-task.
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change standby-timeout-dc 0 | Out-Null
powercfg /change monitor-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-dc 0 | Out-Null
powercfg /hibernate off | Out-Null

# Install HelloWorld server dependencies (first boot only)
Write-Host "Installing HelloWorld server dependencies..."
py -3 -m pip install flask Pillow pyautogui uiautomation pywin32 psutil 2>$null

# Start the Caddy reverse proxy in a non-blocking manner
Write-Host "Running the Caddy reverse proxy from port 9222 to port 1337"
Start-Process -NoNewWindow -FilePath "powershell" -ArgumentList "-Command", "caddy reverse-proxy --from :9222 --to :1337"

# Start the HelloWorld unified runtime server
Write-Host "Running the HelloWorld server on port $pythonServerPort..."
if (Test-Path $watchdogScript) {
    Start-Process -WindowStyle Hidden -FilePath "powershell" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $watchdogScript,
        "-ScriptFolder", $scriptFolder,
        "-Port", "$pythonServerPort"
    )
} else {
    py -3 $pythonScriptFile --host 0.0.0.0 --port $pythonServerPort --token windowsbench-runtime-token
}
