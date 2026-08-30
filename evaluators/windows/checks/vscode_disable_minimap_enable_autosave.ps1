$settingsPath = "$env:APPDATA\Code\User\settings.json"
if (-not (Test-Path $settingsPath)) {
  Write-Output "EVAL_RESULT:FAIL settings.json not found"
  exit 1
}

$raw = Get-Content $settingsPath -Raw
$cleaned = $raw -replace ',\s*}', '}' -replace ',\s*]', ']'

$minimapKeyCount = ([regex]::Matches($raw, '"editor\.minimap\.enabled"\s*:')).Count
$autoSaveKeyCount = ([regex]::Matches($raw, '"files\.autoSave"\s*:')).Count
if ($minimapKeyCount -ne 1) {
  Write-Output "EVAL_RESULT:FAIL editor.minimap.enabled should appear exactly once, got $minimapKeyCount"
  exit 1
}
if ($autoSaveKeyCount -ne 1) {
  Write-Output "EVAL_RESULT:FAIL files.autoSave should appear exactly once, got $autoSaveKeyCount"
  exit 1
}

try {
  $json = $cleaned | ConvertFrom-Json
} catch {
  Write-Output "EVAL_RESULT:FAIL cannot parse settings.json: $_"
  exit 1
}

$minimap = $json.'editor.minimap.enabled'
$autoSave = $json.'files.autoSave'

$codeProc = Get-Process -Name Code -ErrorAction SilentlyContinue |
  Where-Object { $_.MainWindowHandle -ne 0 } |
  Select-Object -First 1
if ($null -eq $codeProc) {
  Write-Output "EVAL_RESULT:FAIL VS Code is not open with a visible window"
  exit 1
}

if ($minimap -eq $false -and $autoSave -eq 'afterDelay') {
  Write-Output "EVAL_RESULT:PASS editor.minimap.enabled=false files.autoSave=afterDelay"
} else {
  Write-Output "EVAL_RESULT:FAIL editor.minimap.enabled=$minimap files.autoSave=$autoSave"
  exit 1
}
