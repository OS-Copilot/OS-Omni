# Read actual current renderer state; LevelDB is not a reliable current-state API.
$ErrorActionPreference = 'Stop'
$pages = @(Invoke-RestMethod 'http://127.0.0.1:9435/json/list' | Where-Object { $_.type -eq 'page' -and $_.url.StartsWith('http://127.0.0.1:4320/') })
if($pages.Count -ne 1){throw 'Expected one OpenFood page for live state evaluation'}
$client=[Net.WebSockets.ClientWebSocket]::new()
$cancel=[Threading.CancellationTokenSource]::new(15000)
try {
 $null=$client.ConnectAsync([Uri]$pages[0].webSocketDebuggerUrl,$cancel.Token).GetAwaiter().GetResult()
 $expression="JSON.stringify(JSON.parse(localStorage.getItem('openfood-static-state-v1')||'{}'))"
 $bytes=[Text.Encoding]::UTF8.GetBytes((@{id=1;method='Runtime.evaluate';params=@{expression=$expression;returnByValue=$true}}|ConvertTo-Json -Depth 8 -Compress))
 $null=$client.SendAsync([ArraySegment[byte]]::new($bytes),[Net.WebSockets.WebSocketMessageType]::Text,$true,$cancel.Token).GetAwaiter().GetResult()
 $buffer=[byte[]]::new(65536)
 do {
  $stream=[IO.MemoryStream]::new()
  try {
   do {$part=$client.ReceiveAsync([ArraySegment[byte]]::new($buffer),$cancel.Token).GetAwaiter().GetResult();$stream.Write($buffer,0,$part.Count)}while(!$part.EndOfMessage)
   $reply=[Text.Encoding]::UTF8.GetString($stream.ToArray())|ConvertFrom-Json
  } finally {$stream.Dispose()}
 }while($reply.id -ne 1)
 if($reply.error -or $reply.result.exceptionDetails){throw 'OpenFood live page inspection failed'}
 $env:OPENFOOD_LIVE_STATE=$reply.result.result.value
 if(!$env:OPENFOOD_LIVE_STATE){throw 'OpenFood live state unavailable'}
} finally {$client.Dispose();$cancel.Dispose()}

$python = @'

import json
import os
import re
import struct

root = 'live-renderer:4320'
state = json.loads(os.environ['OPENFOOD_LIVE_STATE'])
if not isinstance(state, dict):
    raise ValueError('OpenFood current page did not return an object')
documents = [state]
# Current builds keep immutable identifiers in the shipped ASAR, separately
# from mutable Chromium storage. Never infer missing seed records from that
# mutable document or overwrite actual mutable state with seed defaults.
with open(r"C:\OS-Omni\Apps\OpenFood\resources\app.asar", "rb") as archive:
    prefix = archive.read(16)
    header_size = struct.unpack_from("<I", prefix, 4)[0]
    json_size = struct.unpack_from("<I", prefix, 12)[0]
    header = json.loads(archive.read(json_size))
    entry = header["files"]["shared"]["files"]["seed-data.json"]
    archive.seek(8 + header_size + int(entry["offset"]))
    seed = json.loads(archive.read(entry["size"]))
for key in ("restaurants", "users", "courierTasks"):
    state[key] = seed.get(key, [])

restaurant_id_by_name = {}
menu_id_by_name = {}
user_id_by_name = {}

for restaurant in state.get("restaurants") or []:
    if not isinstance(restaurant, dict):
        continue
    restaurant_id = str(restaurant.get("id") or "")
    restaurant_name = str(restaurant.get("name") or "")
    if restaurant_name:
        restaurant_id_by_name[restaurant_name] = restaurant_id
    for item in restaurant.get("menu") or []:
        if isinstance(item, dict) and item.get("name"):
            menu_id_by_name["{}|{}".format(restaurant_id, item.get("name"))] = str(item.get("id") or "")

# Packaged builds keep menu items separately, keyed by restaurantId. Keep
# support for older nested menus without fabricating mutable application state.
for item in seed.get("menu") or []:
    if isinstance(item, dict) and item.get("name") and item.get("restaurantId"):
        menu_id_by_name["{}|{}".format(item["restaurantId"], item["name"])] = str(item.get("id") or "")

for user in state.get("users") or []:
    if isinstance(user, dict) and user.get("name"):
        user_id_by_name[str(user.get("name"))] = str(user.get("id") or "")

print(json.dumps({
    "state": state,
    "menu_id_by_name": menu_id_by_name,
    "restaurant_id_by_name": restaurant_id_by_name,
    "user_id_by_name": user_id_by_name,
    "document_count": len(documents),
    "storage_root": root,
    "courier_route_seeds": seed.get("courierTasks", []),
}))
'@

$python | & python -
