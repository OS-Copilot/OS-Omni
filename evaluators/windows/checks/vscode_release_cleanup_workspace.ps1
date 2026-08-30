$workspace = "C:\Users\User\Documents\release_cleanup_workspace"

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

Require-Contains "$workspace\README.md" "Project Atlas" "README.md"
Require-Contains "$workspace\README.md" "Status: Ready for release" "README.md"
Require-Contains "$workspace\src\api.js" 'const API_BASE = "https://api.acmeops.internal";' "src/api.js"
Require-Contains "$workspace\src\api.js" 'const REQUEST_TIMEOUT = 5000;' "src/api.js"
Require-Contains "$workspace\src\ui.js" 'export const pageTitle = "Weekly Release";' "src/ui.js"
Require-Contains "$workspace\src\ui.js" 'export const primaryButtonLabel = "Publish Update";' "src/ui.js"
Require-Contains "$workspace\src\auth.js" 'export const supportEmail = "release-team@acmeops.internal";' "src/auth.js"
Require-Contains "$workspace\src\auth.js" 'export const defaultRole = "publisher";' "src/auth.js"

$configPath = "$workspace\config\app.json"
if (-not (Test-Path $configPath)) {
  Fail "config/app.json missing"
}
try {
  $config = Get-Content $configPath -Raw | ConvertFrom-Json
} catch {
  Fail "config/app.json is not valid JSON"
}
if ($config.environment -ne "staging") {
  Fail "config/app.json environment expected staging"
}
if ($config.featureFlag -ne $true) {
  Fail "config/app.json featureFlag expected true"
}
if ($config.releaseOwner -ne "ops-release") {
  Fail "config/app.json releaseOwner expected ops-release"
}

$docPath = "$workspace\docs\release-checklist.md"
if (-not (Test-Path $docPath)) {
  Fail "docs/release-checklist.md missing"
}
$expected = @(
  "# Release Checklist",
  "- Verify staging API connectivity",
  "- Confirm publisher permissions",
  "- Review weekly release copy",
  "- Publish after final sign-off"
) -join "`n"
$actual = ((Get-Content $docPath -Raw) -replace "`r`n", "`n").Trim()
if ($actual -ne $expected) {
  Fail "docs/release-checklist.md content mismatch"
}

$hardPath = "$workspace\docs\hard-mode-validation.md"
if (-not (Test-Path $hardPath)) {
  Fail "docs/hard-mode-validation.md missing"
}
$hardActual = ((Get-Content $hardPath -Raw) -replace "`r`n", "`n").Trim()
if ($hardActual -ne "Release cleanup hard mode complete") {
  Fail "docs/hard-mode-validation.md content mismatch"
}

Write-Output "EVAL_RESULT:PASS release cleanup workspace updated"
