# Renders a real-looking terminal screenshot.
# Args: -InputFile path to text, -Command the command run, -OutPath png path, -Width, -FontSize

param(
    [string]$InputFile,
    [string]$Command,
    [string]$OutPath,
    [int]$Width = 1200,
    [int]$FontSize = 13
)

if (-not (Test-Path $InputFile)) { throw "Input not found: $InputFile" }
$body = [System.IO.File]::ReadAllText($InputFile).TrimEnd("`r","`n")

Add-Type -AssemblyName System.Drawing

$font = New-Object System.Drawing.Font("Consolas", [float]$FontSize, [System.Drawing.FontStyle]::Regular)
$boldFont = New-Object System.Drawing.Font("Consolas", [float]$FontSize, [System.Drawing.FontStyle]::Bold)
$lineHeight = [int][math]::Ceiling($font.GetHeight()) + 2
$padding = 22
$titleHeight = 38

$bodyLines = $body -split "`n"
$cmdLine = "PS C:\Users\AG\Documents\GitHub\ai-engineering-course> $Command"
$totalLines = $bodyLines.Count + 2
$height = $titleHeight + ($totalLines * $lineHeight) + ($padding * 2)
if ($height -lt 240) { $height = 240 }
if ($height -gt 4000) { $height = 4000 }

$bmp = New-Object System.Drawing.Bitmap($Width, $height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit

# Background
$bg = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 1, 36, 86))  # Windows Terminal dark blue
$g.FillRectangle($bg, 0, 0, $Width, $height)

# Title bar
$tb = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 32, 32, 32))
$g.FillRectangle($tb, 0, 0, $Width, $titleHeight)

# Traffic lights
$dotColors = @(
    [System.Drawing.Color]::FromArgb(255, 255, 95, 86),
    [System.Drawing.Color]::FromArgb(255, 255, 189, 46),
    [System.Drawing.Color]::FromArgb(255, 39, 201, 63)
)
$i = 0
foreach ($c in $dotColors) {
    $b = New-Object System.Drawing.SolidBrush($c)
    $g.FillEllipse($b, 14 + ($i * 22), 13, 12, 12)
    $i++
}

# Title text
$titleBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 220, 220, 220))
$titleFont = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Regular)
$g.DrawString("Windows PowerShell", $titleFont, $titleBrush, 100, 10)

# Prompt + command
$promptBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 0, 175, 240))  # PS blue
$cmdBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 230, 230, 230))
$outBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 230, 230, 230))
$okBrush  = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 0, 200, 100))   # green for healthy
$warnBrush= New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 255, 200, 80))   # yellow

$y = [float]($titleHeight + $padding)
$g.DrawString($cmdLine, $boldFont, $promptBrush, [float]$padding, $y)
$y += $lineHeight

foreach ($line in $bodyLines) {
    $brush = $outBrush
    if ($line -match "(healthy|ok|OK|Status.*Up)") { $brush = $okBrush }
    elseif ($line -match "(starting|exited|Error|FAIL|warn)") { $brush = $warnBrush }
    $g.DrawString($line.TrimEnd("`r"), $font, $brush, [float]$padding, $y)
    $y += $lineHeight
    if ($y -gt ($height - $padding)) { break }
}

$bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()

Write-Host "saved: $OutPath ($Width x $height)"
