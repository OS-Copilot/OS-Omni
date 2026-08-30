$filePath = Join-Path $env:USERPROFILE "Downloads\hosts.txt"
$content = Get-Content -Path $filePath -Raw
$normalizedContent = ($content -replace "`r`n", "`n" -replace "`r", "`n").TrimEnd("`n")
$lines = Get-Content -Path $filePath | ForEach-Object { $_.TrimEnd() } | Where-Object { $_.Trim() -ne "" }

$prodCount = ([regex]::Matches($content, 'production')).Count
$stgCount = ([regex]::Matches($content, 'staging')).Count
$lineCountOk = $lines.Count -eq 20

$first10Ok = $true
for ($i = 1; $i -le 10; $i++) {
    if ($lines[$i-1] -ne "10.0.0.$i staging") {
        $first10Ok = $false
    }
}

$last10 = $lines[-10..-1] | ForEach-Object { $_.Trim() }
$expectedFinalLines = @(
    "10.0.0.21 node21", "10.0.0.22 node22", "10.0.0.23 node23", "10.0.0.24 node24",
    "10.0.0.25 node25", "10.0.0.26 node26", "10.0.0.27 node27", "10.0.0.28 node28",
    "# migration complete", "# verified-by: ops"
)
$expectedAllLines = @(
    "10.0.0.1 staging", "10.0.0.2 staging", "10.0.0.3 staging", "10.0.0.4 staging", "10.0.0.5 staging",
    "10.0.0.6 staging", "10.0.0.7 staging", "10.0.0.8 staging", "10.0.0.9 staging", "10.0.0.10 staging",
    "10.0.0.21 node21", "10.0.0.22 node22", "10.0.0.23 node23", "10.0.0.24 node24",
    "10.0.0.25 node25", "10.0.0.26 node26", "10.0.0.27 node27", "10.0.0.28 node28", 
    "# migration complete", "# verified-by: ops"
)
$expectedRaw = ($expectedAllLines -join "`n")

$linesMatch = $true
for ($i=0; $i -lt 10; $i++) {
    if ($last10[$i] -ne $expectedFinalLines[$i]) {
        $linesMatch = $false
    }
}
$rawExact = $normalizedContent -eq $expectedRaw

if ($prodCount -eq 0 -and $stgCount -eq 10 -and $lineCountOk -and $first10Ok -and $linesMatch -and $rawExact) {
    Write-Output 'EVAL_RESULT:PASS all_checks_passed'
} else {
    Write-Output "EVAL_RESULT:FAIL prodCount=$prodCount stgCount=$stgCount lineCountOk=$lineCountOk first10Ok=$first10Ok linesMatch=$linesMatch rawExact=$rawExact"
}
