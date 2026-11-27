$ErrorActionPreference = 'Stop'
$targets = @(Invoke-RestMethod 'http://127.0.0.1:9434/json/list')
$pages = @($targets | Where-Object { $_.type -eq 'page' -and $_.url.StartsWith('http://127.0.0.1:4340/') })
if ($pages.Count -ne 1) { throw 'Expected one OpenBank page on the evaluator backend' }
$client = [System.Net.WebSockets.ClientWebSocket]::new()
$cancel = [System.Threading.CancellationTokenSource]::new(15000)
function Invoke-PageCommand($id, $method, $parameters) {
    $message = @{ id = $id; method = $method; params = $parameters } | ConvertTo-Json -Depth 8 -Compress
    $payload = [Text.Encoding]::UTF8.GetBytes($message)
    $null = $client.SendAsync([ArraySegment[byte]]::new($payload), [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cancel.Token).GetAwaiter().GetResult()
    $buffer = [byte[]]::new(65536)
    do {
        $stream = [IO.MemoryStream]::new()
        try {
            do {
                $received = $client.ReceiveAsync([ArraySegment[byte]]::new($buffer), $cancel.Token).GetAwaiter().GetResult()
                $stream.Write($buffer, 0, $received.Count)
            } while (-not $received.EndOfMessage)
            $reply = [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
        } finally { $stream.Dispose() }
    } while ($reply.id -ne $id)
    if ($reply.error -or $reply.result.errorText -or $reply.result.exceptionDetails) { throw 'OpenBank page command failed' }
    return $reply.result
}
try {
    $null = $client.ConnectAsync([Uri]$pages[0].webSocketDebuggerUrl, $cancel.Token).GetAwaiter().GetResult()
    $null = Invoke-PageCommand 1 'Page.navigate' @{ url = 'http://127.0.0.1:4340/index.html' }
    $expression = "({authenticated:document.body.innerText.toLowerCase().includes('welcome back') && document.body.innerText.toLowerCase().includes('accounts'),url:location.href})"
    $confirmed = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 300
        $result = Invoke-PageCommand ($attempt + 2) 'Runtime.evaluate' @{ expression = $expression; returnByValue = $true }
        if ($result.result.value.authenticated -and $result.result.value.url -eq 'http://127.0.0.1:4340/index.html') {
            $confirmed = $true
            break
        }
    }
    if (-not $confirmed) { throw 'OpenBank authenticated page was not confirmed' }
    Write-Output 'OPENBANK_GUI_AUTHENTICATED'
} finally {
    $client.Dispose()
    $cancel.Dispose()
}
