# Read the current OpenFood local state together with the identifiers the
# evaluator needs to line its expectations up with the stored records.
#
# OpenFood is an Electron application: it keeps its state as a JSON document in a
# Chromium LevelDB under the user's application data.  This script makes a
# read-only copy of the write-ahead and sorted-table files, decodes the newest
# complete state document, and prints it alongside the restaurant, menu and user
# identifiers found in it.  The application's own directory is only read.
$ErrorActionPreference = "Stop"

$storageRoot = Join-Path $env:APPDATA "openfood\Local Storage\leveldb"
$copyRoot = Join-Path $env:TEMP "os_omni_openfood_local_state"
if (Test-Path -LiteralPath $copyRoot) { Remove-Item -LiteralPath $copyRoot -Recurse -Force }
New-Item -ItemType Directory -Path $copyRoot -Force | Out-Null
$copied = 0
if (Test-Path -LiteralPath $storageRoot) {
  Get-ChildItem -LiteralPath $storageRoot -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*.log" -or $_.Name -like "*.ldb" } |
    ForEach-Object {
      Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $copyRoot $_.Name) -Force -ErrorAction SilentlyContinue
      $copied++
    }
}

$python = @'
import json
import os
import re

root = os.environ["OPENFOOD_LOCAL_STATE_ROOT"]
documents = []
if os.path.isdir(root):
    for name in sorted(os.listdir(root)):
        if not name.endswith((".log", ".ldb")):
            continue
        try:
            raw = open(os.path.join(root, name), "rb").read()
        except OSError:
            continue
        text = raw.decode("utf-8", "ignore")
        for match in re.finditer(r'\{"view":', text):
            try:
                value, _ = json.JSONDecoder().raw_decode(text[match.start():])
            except ValueError:
                continue
            if isinstance(value, dict) and "createdOrders" in value:
                documents.append(value)

state = documents[-1] if documents else {}

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
}))
'@

$env:OPENFOOD_LOCAL_STATE_ROOT = $copyRoot
$python | & python -
