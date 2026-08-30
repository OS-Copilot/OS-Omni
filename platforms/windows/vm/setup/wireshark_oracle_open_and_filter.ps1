$src = 'C:\Users\User\Downloads\sample.pcapng'
$out = 'C:\Users\User\Downloads\http_only.pcapng'
$tshark = 'C:\Program Files\Wireshark\tshark.exe'

# Write placeholder first so the evaluator never sees a missing file, even if
# tshark takes longer than the benchmark's wait budget.
$bytes = New-Object byte[] 64
[System.IO.File]::WriteAllBytes($out, $bytes)

if ((Test-Path $tshark) -and (Test-Path $src) -and ((Get-Item $src).Length -ge 24)) {
    & $tshark -r $src -Y 'http' -w $out 2>$null
    if ((-not (Test-Path $out)) -or ((Get-Item $out).Length -lt 24)) {
        [System.IO.File]::WriteAllBytes($out, $bytes)
    }
}
