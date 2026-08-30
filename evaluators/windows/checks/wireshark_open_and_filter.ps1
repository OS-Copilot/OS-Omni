$ErrorActionPreference = "Stop"

function Fail($message) {
  Write-Output "EVAL_RESULT:FAIL $message"
  exit 1
}

function Resolve-TShark {
  $candidates = @(
    "C:\Program Files\Wireshark\tshark.exe",
    "C:\Program Files (x86)\Wireshark\tshark.exe"
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { return $candidate }
  }
  $cmd = Get-Command tshark.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

$out = "C:\Users\User\Downloads\http_only.pcapng"
if (-not (Test-Path $out)) {
  Fail "http_only.pcapng not created"
}

$size = (Get-Item $out).Length
if ($size -lt 256) {
  Fail "output file too small to be a real filtered pcapng ($size bytes)"
}

$tshark = Resolve-TShark
if (-not $tshark) {
  Fail "tshark.exe not found; cannot validate pcap contents"
}

$totalText = & $tshark -r $out -T fields -e frame.number 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
  Fail "tshark could not read http_only.pcapng: $totalText"
}
$total = @($totalText -split "`r?`n" | Where-Object { $_.Trim() -ne "" }).Count
if ($total -le 0) {
  Fail "http_only.pcapng contains no packets"
}

$httpText = & $tshark -r $out -Y "http" -T fields -e frame.number 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
  Fail "tshark http filter failed: $httpText"
}
$http = @($httpText -split "`r?`n" | Where-Object { $_.Trim() -ne "" }).Count
if ($http -ne $total) {
  Fail "filtered pcap contains non-http packets total=$total http=$http"
}

Write-Output "EVAL_RESULT:PASS http_only.pcapng contains only HTTP packets count=$total size=$size"
