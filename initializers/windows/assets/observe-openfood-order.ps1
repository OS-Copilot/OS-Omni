param([string]$TracePath, [string]$RunId, [int]$Port = 9435)
$ErrorActionPreference = 'Stop'
$client = [System.Net.WebSockets.ClientWebSocket]::new()
$cancel = [System.Threading.CancellationTokenSource]::new(86400000)
$buffer = [byte[]]::new(65536)
$sequence = 0
$utf8 = [Text.UTF8Encoding]::new($false)
function Receive-Message {
    $stream = [IO.MemoryStream]::new()
    try {
        do {
            $received = $client.ReceiveAsync([ArraySegment[byte]]::new($buffer), $cancel.Token).GetAwaiter().GetResult()
            if ($received.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) { throw 'OpenFood page closed' }
            $stream.Write($buffer, 0, $received.Count)
        } while (-not $received.EndOfMessage)
        return [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
    } finally { $stream.Dispose() }
}
function Save-Event($message) {
    if ($message.method -ne 'Runtime.bindingCalled' -or $message.params.name -ne '__osomniObserveFoodState') { return }
    $state = $message.params.payload | ConvertFrom-Json
    if ($null -eq $state -or $null -eq $state.userId) { return }
    $script:sequence++
    $row = @{run_id=$RunId; seq=$script:sequence; state=$state} | ConvertTo-Json -Depth 40 -Compress
    [IO.File]::AppendAllText($TracePath, $row + "`n", $utf8)
}
function Send-Command($id, $method, $parameters) {
    $payload = [Text.Encoding]::UTF8.GetBytes((@{id=$id;method=$method;params=$parameters} | ConvertTo-Json -Depth 8 -Compress))
    $null = $client.SendAsync([ArraySegment[byte]]::new($payload), [Net.WebSockets.WebSocketMessageType]::Text, $true, $cancel.Token).GetAwaiter().GetResult()
    do {
        $reply = Receive-Message
        Save-Event $reply
    } while ($reply.id -ne $id)
    if ($reply.error -or $reply.result.exceptionDetails) { throw 'OpenFood observer setup failed' }
    return $reply.result
}
try {
    $pages = @()
    for ($attempt=0; $attempt -lt 40; $attempt++) {
        try {
            $pages = @(Invoke-RestMethod "http://127.0.0.1:$Port/json/list" | Where-Object { $_.type -eq 'page' -and $_.url.StartsWith('http://127.0.0.1:4320/') })
        } catch { $pages=@() }
        if ($pages.Count -eq 1) { break }
        Start-Sleep -Milliseconds 300
    }
    if ($pages.Count -ne 1) { throw 'Expected one OpenFood page on port 4320' }
    $null = $client.ConnectAsync([Uri]$pages[0].webSocketDebuggerUrl, $cancel.Token).GetAwaiter().GetResult()
    $null = Send-Command 1 'Runtime.enable' @{}
    $null = Send-Command 2 'Runtime.addBinding' @{name='__osomniObserveFoodState'}
    $expression = @'
(()=>{
 const key='openfood-static-state-v1';
 if(window.__osomniFoodObserver)throw Error('Observer already attached');
 const original=Storage.prototype.setItem;
 Storage.prototype.setItem=function(k,v){
   const result=original.call(this,k,v);
   if(this===localStorage && k===key)window.__osomniObserveFoodState(v);
   return result;
 };
 window.__osomniFoodObserver=true;
 const state=localStorage.getItem(key);
 if(state)window.__osomniObserveFoodState(state);
 const user=document.querySelector('[data-field="userId"]');
 return {userId:user?user.value:null,state:state?JSON.parse(state):null};
})()
'@
    $null = Send-Command 3 'Page.addScriptToEvaluateOnNewDocument' @{source=$expression}
    $result = Send-Command 4 'Runtime.evaluate' @{expression=$expression;returnByValue=$true}
    $ready = @{run_id=$RunId; initial=$result.result.value} | ConvertTo-Json -Depth 40 -Compress
    [IO.File]::WriteAllText($TracePath+'.ready', $ready, $utf8)
    while ($true) { Save-Event (Receive-Message) }
} catch {
    [IO.File]::WriteAllText($TracePath+'.error', $_.Exception.Message, $utf8)
} finally { $client.Dispose(); $cancel.Dispose() }
