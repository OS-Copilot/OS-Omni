$script = @'
import ctypes
import psutil
from ctypes import wintypes

hwnd = ctypes.windll.user32.GetForegroundWindow()
if not hwnd:
    print("EVAL_RESULT:FAIL no foreground window")
    raise SystemExit(1)

length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
title_buffer = ctypes.create_unicode_buffer(length + 1)
ctypes.windll.user32.GetWindowTextW(hwnd, title_buffer, length + 1)

pid = wintypes.DWORD()
ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
try:
    proc = psutil.Process(pid.value)
except Exception:
    print("EVAL_RESULT:FAIL no foreground process")
    raise SystemExit(1)

name = proc.name()
title = title_buffer.value or ""
is_calculator = name.lower().startswith("calculator")
is_calculator_host = name.lower() == "applicationframehost.exe" and "calculator" in title.lower()
if not (is_calculator or is_calculator_host):
    print(f"EVAL_RESULT:FAIL foreground process is {name}, title is [{title}], expected Calculator")
    raise SystemExit(1)

print(f"EVAL_RESULT:PASS Calculator is visible in the foreground via {name}")
'@
$tmp = Join-Path $env:USERPROFILE 'calculator_eval.py'
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
