$filePath = Join-Path $env:USERPROFILE "Downloads\guest.txt"
$content = Get-Content -Path $filePath -Raw
$normalized = $content -replace "`r",""
$lines = Get-Content -Path $filePath | ForEach-Object { $_.TrimEnd() }
$expectedLines = @(
  "Welcome to the system.",
  "Session owner: guest_ops",
  "Access level: temporary",
  "This is a guest log.",
  "Task completed",
  "Reviewed by: shift_lead",
  "Priority: medium",
  "Queue: overnight",
  "# handoff ready",
  "Audit: hard mode complete",
  "Escalation: none",
  "Checksum: HW-4827"
)
$expected = ($expectedLines -join "`n")

$lineCountOk = $lines.Count -eq $expectedLines.Count
$allLinesMatch = $true
if ($lineCountOk) {
    for ($i = 0; $i -lt $expectedLines.Count; $i++) {
        if ($lines[$i] -ne $expectedLines[$i]) {
            $allLinesMatch = $false
            break
        }
    }
} else {
    $allLinesMatch = $false
}

$rawExact = $normalized.TrimEnd() -eq $expected
if ($lineCountOk -and $allLinesMatch -and $rawExact) {
    Write-Output 'EVAL_RESULT:PASS all_checks_passed'
} else {
    Write-Output "EVAL_RESULT:FAIL lineCountOk=$lineCountOk allLinesMatch=$allLinesMatch rawExact=$rawExact got=[$($normalized.TrimEnd())]"
}
