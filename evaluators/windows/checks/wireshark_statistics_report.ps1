$ErrorActionPreference = "Stop"
function Fail($message) { Write-Output "EVAL_RESULT:FAIL $message"; exit 1 }
function Resolve-TShark {
  foreach ($candidate in @("C:\Program Files\Wireshark\tshark.exe", "C:\Program Files (x86)\Wireshark\tshark.exe")) {
    if (Test-Path $candidate) { return $candidate }
  }
  $cmd = Get-Command tshark.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}
$expected = @'
[{"kind":"pcap","path":"C:\\Users\\User\\Downloads\\arp_only.pcapng","all_match_filter":"arp"},{"kind":"pcap","path":"C:\\Users\\User\\Downloads\\icmp_only.pcapng","all_match_filter":"icmp"},{"kind":"pcap","path":"C:\\Users\\User\\Downloads\\syn_only.pcapng","all_match_filter":"tcp.flags.syn == 1 && tcp.flags.ack == 0"},{"kind":"pcap","path":"C:\\Users\\User\\Downloads\\dns_all_for_link.pcapng","all_match_filter":"dns"},{"kind":"pcap","path":"C:\\Users\\User\\Downloads\\http_request_only.pcapng","all_match_filter":"http.request"},{"kind":"pcap","path":"C:\\Users\\User\\Downloads\\http_response_only.pcapng","all_match_filter":"http.response"},{"kind":"pcap","path":"C:\\Users\\User\\Downloads\\udp_only.pcapng","all_match_filter":"udp"},{"kind":"pcap","path":"C:\\Users\\User\\Downloads\\tcp80_only.pcapng","all_match_filter":"tcp.port == 80"}]
'@ | ConvertFrom-Json
$tshark = Resolve-TShark
if (-not $tshark) { Fail "tshark.exe not found" }
foreach ($item in $expected) {
  $path = $item.path
  if (-not (Test-Path -LiteralPath $path)) { Fail "missing artifact: $path" }
  if ($item.kind -eq "text") {
    $got = (Get-Content -LiteralPath $path -Raw) -replace "`r`n", "`n"
    $want = $item.equals -replace "`r`n", "`n"
    if ($got.TrimEnd("`n") -ne $want.TrimEnd("`n")) { Fail "text artifact mismatch: $path" }
    continue
  }
  $size = (Get-Item -LiteralPath $path).Length
  if ($size -lt 24) { Fail "pcap artifact too small: $path" }
  $read = & $tshark -r $path -T fields -e frame.number 2>&1 | Out-String
  if ($LASTEXITCODE -ne 0) { Fail "tshark cannot read $path : $read" }
  if ($item.PSObject.Properties.Name -contains "all_match_filter") {
    $total = @($read -split "`r?`n" | Where-Object { $_.Trim() -ne "" }).Count
    if ($total -gt 0) {
      $filteredText = & $tshark -r $path -Y $item.all_match_filter -T fields -e frame.number 2>&1 | Out-String
      if ($LASTEXITCODE -ne 0) { Fail "filter failed for $path : $($item.all_match_filter)" }
      $filtered = @($filteredText -split "`r?`n" | Where-Object { $_.Trim() -ne "" }).Count
      if ($filtered -ne $total) { Fail "artifact contains packets outside filter $($item.all_match_filter): $path" }
    }
  }
}
Write-Output "EVAL_RESULT:PASS Linux-aligned Wireshark bundle artifacts verified"
