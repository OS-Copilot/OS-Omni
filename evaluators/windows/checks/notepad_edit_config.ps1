$filePath = Join-Path $env:USERPROFILE "Downloads\app.ini"
$content = Get-Content -Path $filePath -Raw
$normalizedContent = ($content -replace "`r`n", "`n" -replace "`r", "`n").TrimEnd("`n")
$lines = Get-Content -Path $filePath | ForEach-Object { $_.TrimEnd() } | Where-Object { $_.Trim() -ne "" }

$expectedLines = @(
  "[Settings]",
  "Environment=QA",
  "HardMode=True",
  "AuditLevel=Strict",
  "Theme=Light",
  "Timeout=60",
  "Mode=Staging",
  "Logging=On",
  "Retries=5",
  "Cache=True",
  "[Database]",
  "Host=db.internal",
  "ReplicaHost=replica.internal",
  "Port=5433",
  "# End of config"
)
$expectedRaw = ($expectedLines -join "`n")

if ($lines.Count -ne $expectedLines.Count) {
    Write-Output "EVAL_RESULT:FAIL line_count_wrong got=$($lines.Count) expected=$($expectedLines.Count) lines=[$(($lines -join ' | '))]"
} elseif ($lines[-1] -ne '# End of config') {
    Write-Output "EVAL_RESULT:FAIL footer_missing got_last=[$($lines[-1])]"
} else {
    $mismatchIndex = -1
    for ($i = 0; $i -lt $expectedLines.Count; $i++) {
        if ($lines[$i] -ne $expectedLines[$i]) {
            $mismatchIndex = $i
            break
        }
    }
    if ($mismatchIndex -ge 0) {
        Write-Output "EVAL_RESULT:FAIL line_mismatch index=$mismatchIndex expected=[$($expectedLines[$mismatchIndex])] got=[$($lines[$mismatchIndex])]"
    } elseif ($normalizedContent -ne $expectedRaw) {
        Write-Output "EVAL_RESULT:FAIL raw_content_mismatch"
    } else {
        Write-Output 'EVAL_RESULT:PASS all_checks_passed'
    }
}
