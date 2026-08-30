$workspace = "C:\Users\User\Documents\ops_handoff_workspace"

function Fail($message) {
  Write-Output "EVAL_RESULT:FAIL $message"
  exit 1
}

function Require-Contains($path, $needle, $label) {
  if (-not (Test-Path $path)) {
    Fail "$label missing"
  }
  $raw = Get-Content $path -Raw
  if ($raw -notlike "*$needle*") {
    Fail "$label missing expected text: $needle"
  }
}

function Require-NotContains($path, $needle, $label) {
  if (-not (Test-Path $path)) {
    Fail "$label missing"
  }
  $raw = Get-Content $path -Raw
  if ($raw -like "*$needle*") {
    Fail "$label still contains old text: $needle"
  }
}

Require-Contains "$workspace\scripts\prepare_report.py" 'REPORT_NAME = "Weekly Ops Digest"' "scripts/prepare_report.py"
Require-Contains "$workspace\scripts\prepare_report.py" 'MAX_ITEMS = 5' "scripts/prepare_report.py"
Require-Contains "$workspace\scripts\prepare_report.py" 'FOOTER_TEXT = "Prepared for Friday handoff"' "scripts/prepare_report.py"
Require-NotContains "$workspace\scripts\prepare_report.py" 'REPORT_NAME = "Daily Ops Digest"' "scripts/prepare_report.py"
Require-NotContains "$workspace\scripts\prepare_report.py" 'MAX_ITEMS = 3' "scripts/prepare_report.py"
Require-NotContains "$workspace\scripts\prepare_report.py" 'FOOTER_TEXT = "Prepared for daily review"' "scripts/prepare_report.py"
Require-Contains "$workspace\scripts\cleanup_data.py" 'ARCHIVE_FOLDER = "processed"' "scripts/cleanup_data.py"
Require-Contains "$workspace\scripts\cleanup_data.py" 'RETENTION_DAYS = 30' "scripts/cleanup_data.py"
Require-Contains "$workspace\scripts\cleanup_data.py" 'DRY_RUN = False' "scripts/cleanup_data.py"
Require-NotContains "$workspace\scripts\cleanup_data.py" 'ARCHIVE_FOLDER = "archive"' "scripts/cleanup_data.py"
Require-NotContains "$workspace\scripts\cleanup_data.py" 'RETENTION_DAYS = 14' "scripts/cleanup_data.py"
Require-NotContains "$workspace\scripts\cleanup_data.py" 'DRY_RUN = True' "scripts/cleanup_data.py"
Require-Contains "$workspace\requirements.txt" 'requests==2.32.3' "requirements.txt"
Require-Contains "$workspace\requirements.txt" 'python-dateutil==2.9.0' "requirements.txt"
Require-NotContains "$workspace\requirements.txt" 'requests==2.31.0' "requirements.txt"
Require-Contains "$workspace\notes\summary_template.md" '# Ops Handoff Summary' "notes/summary_template.md"
Require-Contains "$workspace\notes\summary_template.md" 'Owner: Friday Operations' "notes/summary_template.md"
Require-NotContains "$workspace\notes\summary_template.md" '# Daily Summary' "notes/summary_template.md"
Require-NotContains "$workspace\notes\summary_template.md" 'Owner: Morning Operations' "notes/summary_template.md"

$requirementsLines = Get-Content "$workspace\requirements.txt" -ErrorAction Stop |
  ForEach-Object { $_.Trim() } |
  Where-Object { $_ -ne "" }
$requestLines = @($requirementsLines | Where-Object { $_ -match '^requests==' })
if ($requestLines.Count -ne 1 -or $requestLines[0] -ne 'requests==2.32.3') {
  Fail "requirements.txt should contain exactly one requests version pinned to 2.32.3"
}
$dateutilLines = @($requirementsLines | Where-Object { $_ -match '^python-dateutil==' })
if ($dateutilLines.Count -ne 1 -or $dateutilLines[0] -ne 'python-dateutil==2.9.0') {
  Fail "requirements.txt should contain exactly one python-dateutil version pinned to 2.9.0"
}
$settingsPath = "$workspace\.vscode\settings.json"
if (-not (Test-Path $settingsPath)) {
  Fail ".vscode/settings.json missing"
}
try {
  $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
} catch {
  Fail ".vscode/settings.json is not valid JSON"
}
if ($settings.'editor.formatOnSave' -ne $true) {
  Fail ".vscode/settings.json editor.formatOnSave expected true"
}
if ($settings.'files.autoSave' -ne 'afterDelay') {
  Fail ".vscode/settings.json files.autoSave expected afterDelay"
}
if ($settings.'python.analysis.typeCheckingMode' -ne 'basic') {
  Fail ".vscode/settings.json typeCheckingMode expected basic"
}

$docPath = "$workspace\docs\ops-handoff.md"
if (-not (Test-Path $docPath)) {
  Fail "docs/ops-handoff.md missing"
}
$expected = @(
  "# Ops Handoff",
  "- Report: Weekly Ops Digest",
  "- Max items: 5",
  "- Archive folder: processed",
  "- Retention days: 30",
  "- Auto Save: afterDelay"
) -join "`n"
$actual = ((Get-Content $docPath -Raw) -replace "`r`n", "`n").Trim()
if ($actual -ne $expected) {
  Fail "docs/ops-handoff.md content mismatch"
}

$hardPath = "$workspace\docs\hard-mode-validation.md"
if (-not (Test-Path $hardPath)) {
  Fail "docs/hard-mode-validation.md missing"
}
$hardActual = ((Get-Content $hardPath -Raw) -replace "`r`n", "`n").Trim()
if ($hardActual -ne "Ops handoff hard mode complete") {
  Fail "docs/hard-mode-validation.md content mismatch"
}

Write-Output "EVAL_RESULT:PASS ops handoff workspace updated"
