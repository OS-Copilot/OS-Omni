"""Android phone mirrored into the Windows desktop (scrcpy) for single-screen cross-device tasks.

The host side is shared with Linux (platforms.linux.android_companion): the emulator runs on
the host, a forwarder exposes its adbd port to the guest, and initializers and evaluators reach
the phone with host adb. Only the guest side differs: the Windows guest connects its own adb
(the one bundled with scrcpy) and opens the scrcpy window with PowerShell.

The guest image needs scrcpy 3.1 for Windows in ``C:\\OS-Omni\\scrcpy`` and inbound firewall
allow rules for its adb.exe and scrcpy.exe, so no firewall prompt appears on the desktop.

Programs are started without inheriting the runtime's output pipes: a daemon that inherits
them (adb's server, scrcpy) keeps the /run_powershell request open until it exits. scrcpy is
started through wscript with a hidden console, since ``-WindowStyle Hidden`` would also hide
its phone window.
"""

from __future__ import annotations

from platforms.linux.android_companion import WINDOW_TITLE, CompanionSettings

SCRCPY_DIR = r"C:\OS-Omni\scrcpy"


# Exit code 0 if a phone window exists (it is restored and brought to the front), 1 otherwise.
RESTORE_WINDOW_PS1 = f"""$title = '{WINDOW_TITLE}'
Add-Type -Namespace OsOmni -Name Window -MemberDefinition @"
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
"@
$p = Get-Process scrcpy -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowTitle -eq $title }} | Select-Object -First 1
if (-not $p) {{ exit 1 }}
# Started hidden, so the process's first ShowWindow call takes the hidden start flag instead: call twice.
[OsOmni.Window]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[OsOmni.Window]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[OsOmni.Window]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
exit 0"""


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def scrcpy_powershell(settings: CompanionSettings, *, x: int, y: int, height: int) -> str:
    """Guest PowerShell that (re)connects adb to the phone and opens the scrcpy window."""
    target = f"{settings.forward_host}:{settings.forward_port}"
    scrcpy_args = (f"-s {target} --window-title \"{WINDOW_TITLE}\" --window-x {x} --window-y {y} "
                   f"--window-height {height} --keyboard=uhid --no-audio --shortcut-mod=rsuper")
    return "\n".join([
        f"$dir = {_ps_quote(SCRCPY_DIR)}",
        f"$target = {_ps_quote(target)}",
        f"$title = {_ps_quote(WINDOW_TITLE)}",
        "$adb = Join-Path $dir 'adb.exe'",
        "$log = Join-Path $env:TEMP 'osomni_scrcpy.log'",
        "$out = Join-Path $env:TEMP 'osomni_adb.txt'",
        "function Invoke-Adb([string[]]$adbArgs, [int]$ms = 30000) {",
        "  $p = Start-Process -FilePath $adb -ArgumentList $adbArgs -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError \"$out.err\"",
        "  if (-not $p.WaitForExit($ms)) { $p.Kill() }",
        "  return (Get-Content -Raw $out -ErrorAction SilentlyContinue)",
        "}",
        "function Test-Port([int]$port) {",
        "  try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', $port); $c.Close(); return $true } catch { return $false }",
        "}",
        "function Get-PhoneWindow { Get-Process scrcpy -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq $title } }",
        "for ($attempt = 1; $attempt -le 3; $attempt++) {",
        "  Get-Process scrcpy -ErrorAction SilentlyContinue | Stop-Process -Force",
        "  if (-not (Test-Port 5037)) {",
        "    Start-Process -FilePath $adb -ArgumentList 'start-server' -WindowStyle Hidden",
        "    for ($i = 0; $i -lt 20 -and -not (Test-Port 5037); $i++) { Start-Sleep -Milliseconds 500 }",
        "  }",
        "  Invoke-Adb @('disconnect', $target) 10000 | Out-Null",
        "  for ($i = 0; $i -lt 20; $i++) { if ((Invoke-Adb @('connect', $target) 10000) -match 'connected to') { break }; Start-Sleep 1 }",
        "  Invoke-Adb @('-s', $target, 'wait-for-device') 30000 | Out-Null",
        "  $cmd = 'cmd /c \"\"' + (Join-Path $dir 'scrcpy.exe') + '\" " + scrcpy_args.replace("'", "''") + " > \"' + $log + '\" 2>&1\"'",
        "  $vbs = Join-Path $dir 'android_phone.vbs'",
        "  Set-Content -Encoding ASCII $vbs ('CreateObject(\"WScript.Shell\").Run \"' + $cmd.Replace('\"', '\"\"') + '\", 0, False')",
        "  Start-Process -FilePath wscript.exe -ArgumentList ('\"' + $vbs + '\"')",
        # A Desktop shortcut brings the phone window back: it restores a minimized window, and
        # reopens the window if the agent closed it.
        "  $restore = Join-Path $dir 'restore_phone.ps1'",
        "  Set-Content -Encoding ASCII $restore @'",
        *RESTORE_WINDOW_PS1.splitlines(),
        "'@",
        "  $open = Join-Path $dir 'open_phone.vbs'",
        "  Set-Content -Encoding ASCII $open @(",
        "    'Set sh = CreateObject(\"WScript.Shell\")',",
        "    ('If sh.Run(\"powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"\"' + $restore + '\"\"\", 0, True) <> 0 Then sh.Run \"wscript.exe \"\"' + $vbs + '\"\"\", 0, False'))",
        "  $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) ($title + '.lnk')))",
        "  $lnk.TargetPath = 'wscript.exe'; $lnk.Arguments = '\"' + $open + '\"'; $lnk.IconLocation = (Join-Path $dir 'scrcpy.exe') + ',0'; $lnk.Save()",
        # Ready only if the window appears and is still open a few seconds later.
        "  for ($i = 0; $i -lt 30 -and -not (Get-PhoneWindow); $i++) { Start-Sleep 1 }",
        "  Start-Sleep 4",
        "  if (Get-PhoneWindow) { 'SCRCPY_READY'; exit 0 }",
        "  \"scrcpy attempt $attempt failed\"; Get-Content $log -ErrorAction SilentlyContinue | Select-Object -Last 20",
        "  Start-Sleep 3",
        "}",
        "exit 1",
    ])


def file_sha256_powershell(path: str) -> str:
    """Guest PowerShell printing a file's lowercase SHA-256, or nothing if it is missing.

    The file is opened with read/write sharing: LibreOffice keeps an open document locked,
    and Get-FileHash cannot read it then.
    """
    return (f"$p = {_ps_quote(path)}; if (Test-Path -LiteralPath $p -PathType Leaf) {{ "
            "$s = [IO.File]::Open($p, 'Open', 'Read', 'ReadWrite'); "
            "try { (Get-FileHash -Algorithm SHA256 -InputStream $s).Hash.ToLower() } finally { $s.Dispose() } }")
