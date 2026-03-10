param(
  [string]$InputPath = "",
  [string]$WorkDir = "",
  [switch]$FailOnWarnings,
  [switch]$KeepGeneratedSample,
  [Alias('h','?')][switch]$Help
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

function Get-WarnCountFromCliOutput {
  param([string[]]$Lines)
  $joined = $Lines -join "`n"
  $match = [regex]::Match($joined, 'Warnings:\s*(\d+)')
  if ($match.Success) {
    return [int]$match.Groups[1].Value
  }
  return -1
}

function Show-UsageAndExamples {
  Write-Host "Usage: .\scripts\validate_case.ps1 -InputPath <path-to-file> [-WorkDir <path>] [-FailOnWarnings] [-KeepGeneratedSample]"
  Write-Host ""
  Write-Host "Examples:"
  Write-Host "  .\scripts\validate_case.ps1 -InputPath C:\cases\Case_12345678.pdf"
  Write-Host "  .\scripts\validate_case.ps1 -InputPath C:\cases\Case_12345678.pdf -FailOnWarnings -WorkDir C:\results"
}

function Show-Help {
  Write-Host "Usage:"
  Write-Host "  .\scripts\validate_case.ps1 -InputPath <path-to-file> [-WorkDir <path>] [-FailOnWarnings] [-KeepGeneratedSample] [-Help]"
  Write-Host ""
  Write-Host "Arguments:"
  Write-Host "  -InputPath            Path to a PDF or TXT file to validate/sanitize."
  Write-Host "  -WorkDir              Optional folder for outputs. Defaults to directory of InputPath."
  Write-Host "  -FailOnWarnings       Fail with non-zero exit when any warnings are emitted."
  Write-Host "  -KeepGeneratedSample  Keep the temporary sample input if no InputPath is provided."
  Write-Host "  -Help, -h, -?         Show this help text and exit."
  Write-Host ""
  Write-Host "Outputs:"
  Write-Host "  <stem>.sanitized.pdf"
  Write-Host "  <stem>.sanitized.txt"
  Write-Host "  <stem>.redaction.log"
  Write-Host ""
  Write-Host "Examples:"
  Write-Host "  .\scripts\validate_case.ps1 -InputPath C:\cases\Case_12345678.pdf"
  Write-Host "  .\scripts\validate_case.ps1 -InputPath C:\cases\Case_12345678.pdf -FailOnWarnings"
  Write-Host "  .\scripts\validate_case.ps1 -InputPath C:\cases\Case_12345678.pdf -WorkDir C:\results -KeepGeneratedSample"
}

if ($PSBoundParameters.Count -eq 0) {
  Show-UsageAndExamples
  exit 0
}

if ($Help) {
  Show-Help
  exit 0
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
$outLog = Join-Path $WorkDir "$stem.redaction.log"
$warnThreshold = if ($FailOnWarnings) { 0 } else { 99999 }
$tempReport = New-TemporaryFile

foreach ($path in @($outPdf, $outTxt, $outLog)) {
  if (-not (Test-FileWritable -Path $path)) {
    throw "Output file is locked or not writable: $path. Close any open copy of this file and run again."
  }
}

Write-Step "Running anonymizer CLI"
$env:PYTHONPATH = "src"
$cliOutput = & python -m anon_tool.cli redact `
  --input $InputPath `
  --output $outPdf `
  --report $tempReport `
  --also-write-txt $outTxt `
  --log-file $outLog `
  --warn-threshold $warnThreshold 2>&1
$warnCount = Get-WarnCountFromCliOutput $cliOutput

if ($LASTEXITCODE -ne 0) {
  if ($LASTEXITCODE -eq 1) {
    $lockedPaths = @($outPdf, $outTxt, $outLog) | Where-Object { -not (Test-FileWritable -Path $_) }
    if ($lockedPaths.Count -gt 0) {
      throw "One or more output files are locked. Close them and run again: $($lockedPaths -join ', ')"
    }
  }
  throw "CLI exited with code $LASTEXITCODE"
}

foreach ($path in @($outPdf, $outTxt, $outLog)) {
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

Write-Host ""
Write-Host "Validation Summary"
Write-Host "------------------"
Write-Host "Input:          $InputPath"
Write-Host "Sanitized PDF:  $outPdf"
Write-Host "Sanitized TXT:  $outTxt"
Write-Host "Audit Log:      $outLog"
if ($warnCount -ge 0) {
  $status = if ($warnCount -eq 0) { "success" } else { "success_with_warnings" }
  Write-Host "Status:         $status"
  Write-Host "Warnings:       $warnCount"
}
else {
  Write-Host "Warnings:       unavailable"
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

if ($tempReport -and (Test-Path -LiteralPath $tempReport)) {
  Remove-Item -LiteralPath $tempReport -Force -ErrorAction SilentlyContinue
}

exit 0
