$ErrorActionPreference = "Stop"
$exportPath = "C:\Users\User\Downloads\gimp_center_helloworld.png"
$exportPathAlt = "$exportPath.png"

for ($i = 0; $i -lt 24; $i++) {
  if ((Test-Path $exportPath) -or (Test-Path $exportPathAlt)) {
    break
  }
  Start-Sleep -Milliseconds 500
}

if ((-not (Test-Path $exportPath)) -and (Test-Path $exportPathAlt)) {
  $exportPath = $exportPathAlt
}

if (-not (Test-Path $exportPath)) {
  Write-Output "EVAL_RESULT:FAIL export file was not created"
  exit 0
}

Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing
[void][Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
[void][Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]
[void][Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType=WindowsRuntime]

function Await-WinRT {
  param(
    [Parameter(Mandatory = $true)] $Operation,
    [Parameter(Mandatory = $true)] [Type] $ResultType
  )

  $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } |
    Select-Object -First 1
  $genericMethod = $method.MakeGenericMethod($ResultType)
  $task = $genericMethod.Invoke($null, @($Operation))
  return $task.GetAwaiter().GetResult()
}

$file = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($exportPath)) ([Windows.Storage.StorageFile])
$stream = Await-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$ocrEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $ocrEngine) {
  Write-Output "EVAL_RESULT:FAIL Windows OCR engine is unavailable"
  exit 0
}

$ocrResult = Await-WinRT ($ocrEngine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$targetRect = $null
foreach ($line in $ocrResult.Lines) {
  $normalizedLine = (($line.Text -replace '[^A-Za-z]', '')).ToLowerInvariant()
  if ($normalizedLine -eq "helloworld") {
    $targetRect = $line.BoundingRect
    break
  }
}

if ($null -eq $targetRect) {
  foreach ($line in $ocrResult.Lines) {
    foreach ($word in $line.Words) {
      $normalizedWord = (($word.Text -replace '[^A-Za-z]', '')).ToLowerInvariant()
      if ($normalizedWord -eq "helloworld") {
        $targetRect = $word.BoundingRect
        break
      }
    }
    if ($null -ne $targetRect) {
      break
    }
  }
}

if ($null -eq $targetRect) {
  $recognized = ($ocrResult.Text -replace '\s+', ' ').Trim()
  Write-Output "EVAL_RESULT:FAIL text 'Helloworld' was not detected by OCR recognized='$recognized'"
  exit 0
}

$image = [System.Drawing.Image]::FromFile($exportPath)
try {
  $width = [double]$image.Width
  $height = [double]$image.Height
} finally {
  $image.Dispose()
}

$canvasCenterX = $width / 2.0
$canvasCenterY = $height / 2.0
$textCenterX = [double]$targetRect.X + ([double]$targetRect.Width / 2.0)
$textCenterY = [double]$targetRect.Y + ([double]$targetRect.Height / 2.0)
$deltaX = [Math]::Abs($textCenterX - $canvasCenterX)
$deltaY = [Math]::Abs($textCenterY - $canvasCenterY)
$toleranceX = [Math]::Max(40.0, $width * 0.08)
$toleranceY = [Math]::Max(30.0, $height * 0.08)

if ($deltaX -le $toleranceX -and $deltaY -le $toleranceY) {
  Write-Output ("EVAL_RESULT:PASS size={0}x{1} text_center=({2:N1},{3:N1}) canvas_center=({4:N1},{5:N1})" -f $width, $height, $textCenterX, $textCenterY, $canvasCenterX, $canvasCenterY)
} else {
  Write-Output ("EVAL_RESULT:FAIL not centered dx={0:N1} dy={1:N1} tolerance=({2:N1},{3:N1})" -f $deltaX, $deltaY, $toleranceX, $toleranceY)
}
