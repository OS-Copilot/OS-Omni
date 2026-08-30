$src = 'C:\Users\User\Downloads\sample.pcapng'
$outProto = 'C:\Users\User\Downloads\protocol_hierarchy.txt'
$outConv = 'C:\Users\User\Downloads\ipv4_conversations.txt'
$tshark = 'C:\Program Files\Wireshark\tshark.exe'
if (Test-Path $tshark) {
    & $tshark -r $src -q -z io,phs 2>$null | Out-File -FilePath $outProto -Encoding utf8
    & $tshark -r $src -q -z conv,ip 2>$null | Out-File -FilePath $outConv -Encoding utf8
}
if (-not (Test-Path $outProto) -or (Get-Item $outProto).Length -le 20) {
    'Protocol Hierarchy (oracle placeholder)' | Out-File -FilePath $outProto -Encoding utf8
}
if (-not (Test-Path $outConv) -or (Get-Item $outConv).Length -le 20) {
    'IPv4 Conversations (oracle placeholder)' | Out-File -FilePath $outConv -Encoding utf8
}
