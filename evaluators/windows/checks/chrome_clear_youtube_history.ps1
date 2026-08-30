# Kill Chrome process tree to unlock the History DB
taskkill /F /IM chrome.exe /T 2>$null
Start-Sleep -Seconds 3

$historyDb = "$env:LOCALAPPDATA\Google\Chrome\User Data\Default\History"
if (-not (Test-Path $historyDb)) {
    Write-Output "EVAL_RESULT:FAIL History DB not found"
    exit 1
}

# Copy to temp to avoid lock issues
$tempDb = "$env:TEMP\chrome_history_check.db"
Copy-Item $historyDb $tempDb -Force

# Fetch all URLs, count YouTube vs non-YouTube using Python (WAA style)
$counts = (py -3 -W ignore -c "import sqlite3,os; db=os.path.join(os.environ['TEMP'],'chrome_history_check.db'); conn=sqlite3.connect(db); c=conn.cursor(); c.execute('SELECT url FROM urls'); urls=[r[0] for r in c.fetchall()]; conn.close(); yt=sum(1 for u in urls if 'youtube' in u); oth=sum(1 for u in urls if 'youtube' not in u); print(f'{yt},{oth}')") | Select-Object -Last 1

Remove-Item $tempDb -Force -ErrorAction SilentlyContinue

$parts = $counts.Trim().Split(",")
$yt = [int]$parts[0]
$other = [int]$parts[1]

if ($yt -eq 0 -and $other -ge 4) {
    Write-Output "EVAL_RESULT:PASS YouTube=0, Others=$other"
} else {
    Write-Output "EVAL_RESULT:FAIL YouTube=$yt, Others=$other"
    exit 1
}
