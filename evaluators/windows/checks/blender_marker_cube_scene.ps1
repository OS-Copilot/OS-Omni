$ErrorActionPreference = "Stop"
$scenePath = "C:\Users\User\Documents\blender_tasks\marker_cube_scene.blend"
$blenderExeCandidates = @(
  "C:\Tools\Blender279b\blender-2.79b-windows64\blender.exe",
  "C:\Program Files\Blender Foundation\Blender 2.79\blender.exe",
  "C:\Program Files\Blender Foundation\Blender\blender.exe",
  "$env:LOCALAPPDATA\Programs\Blender Foundation\Blender\blender.exe"
)
$blenderExe = $blenderExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $blenderExe) {
  $cmd = Get-Command blender.exe -ErrorAction SilentlyContinue
  if ($cmd) {
    $blenderExe = $cmd.Source
  }
}

function Fail($message) {
  Write-Output "EVAL_RESULT:FAIL $message"
  exit 1
}

function Assert-Close($actual, $expected, $label, $tolerance = 0.05) {
  if ([math]::Abs([double]$actual - [double]$expected) -gt $tolerance) {
    Fail "$label expected $expected but got $actual"
  }
}

function Assert-Vec($actual, $expected, $label, $tolerance = 0.05) {
  for ($i = 0; $i -lt $expected.Count; $i++) {
    Assert-Close $actual[$i] $expected[$i] "$label[$i]" $tolerance
  }
}

function Has-SceneObject($collection, $name) {
  return $collection.PSObject.Properties.Name -contains $name
}

function Get-SceneObject($collection, $name) {
  $prop = $collection.PSObject.Properties[$name]
  if ($null -eq $prop) {
    return $null
  }
  return $prop.Value
}

if (-not (Test-Path $scenePath)) {
  Fail "scene file missing"
}
if (-not $blenderExe -or -not (Test-Path $blenderExe)) {
  Fail "Blender executable missing"
}

$jsonPath = Join-Path $env:TEMP "inspect_marker_cube_scene.json"
$env:HW_SCENE_JSON_PATH = $jsonPath
$inspectScript = @'
import bpy, json, os

payload = {"objects": {}}
for obj in bpy.data.objects:
    mesh_stats = {}
    if obj.type == "MESH" and obj.data is not None:
        mesh_stats = {
            "vertex_count": len(obj.data.vertices),
            "face_count": len(obj.data.polygons),
        }
    payload["objects"][obj.name] = {
        "type": obj.type,
        "location": [float(v) for v in obj.location],
        "scale": [float(v) for v in obj.scale],
        "rotation": [float(v) for v in obj.rotation_euler],
        **mesh_stats,
    }

with open(os.environ["HW_SCENE_JSON_PATH"], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
print("SCENE_JSON_WRITTEN")
'@

$inspectPath = Join-Path $env:TEMP "inspect_marker_cube_scene.py"
Set-Content -LiteralPath $inspectPath -Value $inspectScript -Encoding utf8
if (Test-Path $jsonPath) {
  Remove-Item -LiteralPath $jsonPath -Force
}
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$raw = & $blenderExe --background $scenePath --python $inspectPath 2>&1 | Out-String
$ErrorActionPreference = $previousErrorActionPreference
if (-not (Test-Path $jsonPath)) {
  Fail "scene inspection output missing"
}

try {
  $scene = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
} catch {
  Fail "scene inspection JSON parse failed"
}

$objects = $scene.objects
if (-not (Has-SceneObject $objects "MarkerCube")) {
  Fail "MarkerCube missing"
}
if (Has-SceneObject $objects "Cube") {
  Fail "default Cube name still present"
}

$cube = Get-SceneObject $objects "MarkerCube"
if ($cube.type -ne "MESH") {
  Fail "MarkerCube type expected MESH"
}
if ($cube.vertex_count -ne 8) {
  Fail "MarkerCube expected 8 vertices but got $($cube.vertex_count)"
}
if ($cube.face_count -ne 6) {
  Fail "MarkerCube expected 6 faces but got $($cube.face_count)"
}

Assert-Vec $cube.location @(2.0, -1.0, 1.0) "MarkerCube.location"

Write-Output "EVAL_RESULT:PASS marker cube scene saved correctly"
