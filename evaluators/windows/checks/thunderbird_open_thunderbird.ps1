$script = @'
import ctypes
import psutil
from ctypes import wintypes

hwnd = ctypes.windll.user32.GetForegroundWindow()
if not hwnd:
    print("EVAL_RESULT:FAIL no foreground window")
    raise SystemExit(1)

title_len = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
title_buf = ctypes.create_unicode_buffer(title_len + 1)
ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, title_len + 1)

pid = wintypes.DWORD()
ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
try:
    proc = psutil.Process(pid.value)
except Exception:
    print("EVAL_RESULT:FAIL no foreground process")
    raise SystemExit(1)

name = proc.name()
title = title_buf.value or ""
if name.lower() != "thunderbird.exe":
    print(f"EVAL_RESULT:FAIL foreground process is {name}, title is [{title}], expected thunderbird.exe")
    raise SystemExit(1)
if not title:
    print("EVAL_RESULT:FAIL Thunderbird foreground window title missing")
    raise SystemExit(1)

print("EVAL_RESULT:PASS Thunderbird is visible in the foreground")
'@
$tmp = Join-Path $env:USERPROFILE 'thunderbird_open_eval.py'
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
