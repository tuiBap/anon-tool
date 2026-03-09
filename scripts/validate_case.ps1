param(
  [string]$InputPath = "",
  [string]$WorkDir = "",
  [switch]$FailOnWarnings,
  [switch]$KeepGeneratedSample
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host "[validate] $Message"
}

function Test-CommandExists {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-FileWritable {
  param([string]$Path)

  try {
    $directory = Split-Path -Parent $Path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
      New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    if (Test-Path -LiteralPath $Path) {
      $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
      $stream.Close()
      return $true
    }

    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    $stream.Close()
    Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    return $true
  }
  catch {
    return $false
  }
}

if (-not (Test-Path -LiteralPath ".\src\anon_tool\cli.py")) {
  throw "Run this script from repo root. Missing .\src\anon_tool\cli.py"
}

if (-not (Test-CommandExists "python")) {
  throw "Python is not available on PATH."
}

$generatedSample = $false
if ([string]::IsNullOrWhiteSpace($InputPath)) {
  $InputPath = ".\sample.validate.txt"
  $sample = @(
    "Created By David Bush dbush@opentext.com"
    "Phone: 847-267-9330"
    "Mailing Address: 720 Irwin Ave"
    "Symptoms: ArcSight Console freezes under heavy usage"
  ) -join [Environment]::NewLine
  Set-Content -LiteralPath $InputPath -Value $sample -Encoding UTF8
  $generatedSample = $true
  Write-Step "No input supplied; generated sample input at $InputPath"
}

if (-not (Test-Path -LiteralPath $InputPath)) {
  throw "Input file not found: $InputPath"
}

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
  $resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
  $WorkDir = Split-Path -Parent $resolvedInput
}

New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

$stem = [IO.Path]::GetFileNameWithoutExtension($InputPath)
$outPdf = Join-Path $WorkDir "$stem.sanitized.pdf"
$outTxt = Join-Path $WorkDir "$stem.sanitized.txt"
$outReport = Join-Path $WorkDir "$stem.report.json"
$outLog = Join-Path $WorkDir "$stem.redaction.log"
$warnThreshold = if ($FailOnWarnings) { 0 } else { 99999 }

foreach ($path in @($outPdf, $outTxt, $outReport, $outLog)) {
  if (-not (Test-FileWritable -Path $path)) {
    throw "Output file is locked or not writable: $path. Close any open copy of this file and run again."
  }
}

Write-Step "Running anonymizer CLI"
$env:PYTHONPATH = "src"
python -m anon_tool.cli redact `
  --input $InputPath `
  --output $outPdf `
  --report $outReport `
  --also-write-txt $outTxt `
  --log-file $outLog `
  --warn-threshold $warnThreshold

if ($LASTEXITCODE -ne 0) {
  if ($LASTEXITCODE -eq 1) {
    $lockedPaths = @($outPdf, $outTxt, $outReport, $outLog) | Where-Object { -not (Test-FileWritable -Path $_) }
    if ($lockedPaths.Count -gt 0) {
      throw "One or more output files are locked. Close them and run again: $($lockedPaths -join ', ')"
    }
  }
  throw "CLI exited with code $LASTEXITCODE"
}

foreach ($path in @($outPdf, $outTxt, $outReport, $outLog)) {
  if (-not (Test-Path -LiteralPath $path)) {
    throw "Expected output missing: $path"
  }
}

Write-Step "Running leak checks on sanitized text"
$txt = Get-Content -LiteralPath $outTxt -Raw -Encoding UTF8
$emailRegex = [regex]'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b'
$phoneRegex = [regex]'(?:(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]\d{4}\b'
$cardRegex = [regex]'\b(?:\d[ -]*?){13,19}\b'
$issues = @()

if ($emailRegex.IsMatch($txt)) { $issues += "Email-like token remains in sanitized text." }
if ($phoneRegex.IsMatch($txt)) { $issues += "Phone-like token remains in sanitized text." }
if ($cardRegex.IsMatch($txt)) { $issues += "Card-like token remains in sanitized text." }

$report = Get-Content -LiteralPath $outReport -Raw -Encoding UTF8 | ConvertFrom-Json

Write-Host ""
Write-Host "Validation Summary"
Write-Host "------------------"
Write-Host "Input:          $InputPath"
Write-Host "Sanitized PDF:  $outPdf"
Write-Host "Sanitized TXT:  $outTxt"
Write-Host "Report:         $outReport"
Write-Host "Audit Log:      $outLog"
Write-Host "Status:         $($report.status)"
Write-Host "Warnings:       $($report.warnings.Count)"
Write-Host "Category Counts:"
if ($report.counts_by_category) {
  foreach ($prop in $report.counts_by_category.PSObject.Properties) {
    Write-Host ("  - {0}: {1}" -f $prop.Name, $prop.Value)
  }
}
else {
  Write-Host "  - none"
}

if ($issues.Count -gt 0) {
  Write-Host ""
  Write-Host "FAIL"
  $issues | ForEach-Object { Write-Host " - $_" }
  exit 1
}

Write-Host ""
Write-Host "PASS"

if ($generatedSample -and -not $KeepGeneratedSample) {
  Remove-Item -LiteralPath $InputPath -Force -ErrorAction SilentlyContinue
}

exit 0
