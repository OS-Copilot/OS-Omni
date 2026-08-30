$ErrorActionPreference = "Stop"

$referencePath = "C:\Users\User\Downloads\Apple_and_Orange_expected.png"
$exportBase = "C:\Users\User\Downloads\apple_and_orange_focus_blur_submission"
$exportCandidates = @(
  "$exportBase.jpg",
  "$exportBase.jpg.png",
  "$exportBase.png.jpg",
  "$exportBase.png",
  "$exportBase.jpg.jpg",
  "$exportBase.png.png"
)

if (-not (Test-Path $referencePath)) {
  Write-Output "EVAL_RESULT:FAIL reference image not found"
  exit 0
}

Start-Sleep -Milliseconds 1500

$exportPath = $null
for ($i = 0; $i -lt 24; $i++) {
  $exportPath = $exportCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($null -ne $exportPath) {
    break
  }
  Start-Sleep -Milliseconds 500
}

if ($null -eq $exportPath) {
  Write-Output "EVAL_RESULT:FAIL export file was not created"
  exit 0
}

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

function Get-ImageStats {
  param(
    [Parameter(Mandatory = $true)] [string] $Path,
    [int] $TargetWidth = 256,
    [int] $TargetHeight = 256
  )

  $source = [System.Drawing.Bitmap]::FromFile($Path)
  try {
    $scaled = New-Object System.Drawing.Bitmap $TargetWidth, $TargetHeight
    try {
      $graphics = [System.Drawing.Graphics]::FromImage($scaled)
      try {
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.DrawImage($source, 0, 0, $TargetWidth, $TargetHeight)
      } finally {
        $graphics.Dispose()
      }

      $grayValues = New-Object 'double[]' ($TargetWidth * $TargetHeight)
      $colorDelta = 0.0
      $index = 0
      for ($y = 0; $y -lt $TargetHeight; $y++) {
        for ($x = 0; $x -lt $TargetWidth; $x++) {
          $pixel = $scaled.GetPixel($x, $y)
          $grayValues[$index] = (0.299 * $pixel.R) + (0.587 * $pixel.G) + (0.114 * $pixel.B)
          $colorDelta += [Math]::Abs($pixel.R - $pixel.G) + [Math]::Abs($pixel.G - $pixel.B) + [Math]::Abs($pixel.R - $pixel.B)
          $index++
        }
      }

      return [PSCustomObject]@{
        OriginalWidth = $source.Width
        OriginalHeight = $source.Height
        GrayValues = $grayValues
        MeanColorDelta = $colorDelta / ($TargetWidth * $TargetHeight * 3.0)
      }
    } finally {
      $scaled.Dispose()
    }
  } finally {
    $source.Dispose()
  }
}

$reference = Get-ImageStats -Path $referencePath
$submission = Get-ImageStats -Path $exportPath

$referenceAspect = [double]$reference.OriginalWidth / [double]$reference.OriginalHeight
$submissionAspect = [double]$submission.OriginalWidth / [double]$submission.OriginalHeight
$aspectDelta = [Math]::Abs($referenceAspect - $submissionAspect)
if ($aspectDelta -gt 0.12) {
  Write-Output ("EVAL_RESULT:FAIL aspect ratio mismatch delta={0:N3}" -f $aspectDelta)
  exit 0
}

$sumAbsError = 0.0
for ($i = 0; $i -lt $reference.GrayValues.Length; $i++) {
  $sumAbsError += [Math]::Abs($reference.GrayValues[$i] - $submission.GrayValues[$i])
}
$mae = $sumAbsError / $reference.GrayValues.Length

if ($submission.MeanColorDelta -gt 6.0) {
  Write-Output ("EVAL_RESULT:FAIL output is not black and white mean_color_delta={0:N2}" -f $submission.MeanColorDelta)
  exit 0
}

if ($mae -le 12.0) {
  Write-Output ("EVAL_RESULT:PASS mae={0:N2} aspect_delta={1:N3} mean_color_delta={2:N2}" -f $mae, $aspectDelta, $submission.MeanColorDelta)
} else {
  Write-Output ("EVAL_RESULT:FAIL image mismatch mae={0:N2} aspect_delta={1:N3} mean_color_delta={2:N2}" -f $mae, $aspectDelta, $submission.MeanColorDelta)
}
