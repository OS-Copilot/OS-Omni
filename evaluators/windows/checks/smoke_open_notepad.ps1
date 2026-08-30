$script = @'
import psutil

matches = []
for proc in psutil.process_iter(["name"]):
    try:
        if (proc.info["name"] or "").lower() == "notepad.exe":
            title = proc.name()
            matches.append(proc.pid)
    except Exception:
        continue

if not matches:
    print("EVAL_RESULT:FAIL notepad.exe is not running")
    raise SystemExit(1)

print(f"EVAL_RESULT:PASS Notepad is open (pids={matches})")
'@
$tmp = Join-Path $env:USERPROFILE 'notepad_eval.py'
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
py -3 -W ignore $tmp
$code = $LASTEXITCODE
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
exit $code
