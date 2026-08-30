$ErrorActionPreference = "Stop"

Start-Sleep -Milliseconds 1500

$referencePath = "C:\Users\User\Downloads\Composite_Expected.png"
$exportBase = "C:\Users\User\Downloads\cartoon_girl_blend_submission"
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

function New-ScaledBitmap {
  param(
    [Parameter(Mandatory = $true)] [System.Drawing.Bitmap] $Source,
    [int] $TargetWidth = 512,
    [int] $TargetHeight = 512
  )

  $scaled = New-Object System.Drawing.Bitmap $TargetWidth, $TargetHeight
  $graphics = [System.Drawing.Graphics]::FromImage($scaled)
  try {
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.DrawImage($Source, 0, 0, $TargetWidth, $TargetHeight)
  } finally {
    $graphics.Dispose()
  }
  return $scaled
}

$referenceImage = [System.Drawing.Bitmap]::FromFile($referencePath)
$submissionImage = [System.Drawing.Bitmap]::FromFile($exportPath)
try {
  $referenceAspect = [double]$referenceImage.Width / [double]$referenceImage.Height
  $submissionAspect = [double]$submissionImage.Width / [double]$submissionImage.Height
  $aspectDelta = [Math]::Abs($referenceAspect - $submissionAspect)
  if ($aspectDelta -gt 0.03) {
    Write-Output ("EVAL_RESULT:FAIL aspect ratio mismatch delta={0:N3}" -f $aspectDelta)
    exit 0
  }

  $referenceScaled = New-ScaledBitmap -Source $referenceImage
  $submissionScaled = New-ScaledBitmap -Source $submissionImage
  try {
    $sumAbsError = 0.0
    for ($y = 0; $y -lt $referenceScaled.Height; $y++) {
      for ($x = 0; $x -lt $referenceScaled.Width; $x++) {
        $rp = $referenceScaled.GetPixel($x, $y)
        $sp = $submissionScaled.GetPixel($x, $y)
        $sumAbsError += [Math]::Abs($rp.R - $sp.R)
        $sumAbsError += [Math]::Abs($rp.G - $sp.G)
        $sumAbsError += [Math]::Abs($rp.B - $sp.B)
      }
    }

    $mae = $sumAbsError / ($referenceScaled.Width * $referenceScaled.Height * 3.0)
    if ($mae -le 14.0) {
      Write-Output ("EVAL_RESULT:PASS mae={0:N2} aspect_delta={1:N3}" -f $mae, $aspectDelta)
    } else {
      Write-Output ("EVAL_RESULT:FAIL image mismatch mae={0:N2} aspect_delta={1:N3}" -f $mae, $aspectDelta)
    }
  } finally {
    $referenceScaled.Dispose()
    $submissionScaled.Dispose()
  }
} finally {
  $referenceImage.Dispose()
  $submissionImage.Dispose()
}
