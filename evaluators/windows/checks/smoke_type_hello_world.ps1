$target = Join-Path $env:USERPROFILE 'hello_world_oracle.txt'
if (-not (Test-Path $target)) {
  Write-Output 'EVAL_RESULT:FAIL hello_world_oracle.txt is missing'
  exit 1
}
$text = (Get-Content -LiteralPath $target -Raw -ErrorAction Stop).TrimEnd("`r","`n")
$notepad = Get-Process notepad -ErrorAction SilentlyContinue
if (-not $notepad) {
  Write-Output 'EVAL_RESULT:FAIL notepad.exe is not running'
  exit 1
}
if ($text -eq 'Hello World') {
  Write-Output 'EVAL_RESULT:PASS Notepad oracle file contains exact text'
} else {
  Write-Output "EVAL_RESULT:FAIL oracle file text was: [$text]"
  exit 1
}
