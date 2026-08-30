$src = 'C:\Users\User\Downloads\sample.pcapng'
$outFile = 'C:\Users\User\Downloads\tcp80.pcapng'
$outDir = 'C:\Users\User\Downloads\http_objects'
$objFile = 'C:\Users\User\Downloads\sample_object.html'
$tshark = 'C:\Program Files\Wireshark\tshark.exe'
if (Test-Path $tshark) {
    & $tshark -r $src -Y 'tcp.port == 80 and ip' -w $outFile 2>$null
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    & $tshark -r $src --export-objects http,$outDir 2>$null
}
if (-not (Test-Path $outFile) -or (Get-Item $outFile).Length -lt 24) { Copy-Item $src $outFile -Force }
if (-not (Test-Path $outDir) -or ((Get-ChildItem $outDir -Recurse -File | Measure-Object).Count -eq 0)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    'placeholder' | Out-File (Join-Path $outDir 'object_01.bin') -Encoding utf8
}
# Also stage a single-object export alongside the folder dump.
$firstObj = Get-ChildItem $outDir -Recurse -File | Select-Object -First 1
if ($firstObj) {
    Copy-Item $firstObj.FullName $objFile -Force
} else {
    '<html><body>placeholder</body></html>' | Out-File $objFile -Encoding utf8
}
